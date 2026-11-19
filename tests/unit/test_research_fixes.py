"""Regression tests for bugs fixed in litdb.research and the research command."""

import os
import sys
from types import ModuleType, SimpleNamespace
from typing import ClassVar
from unittest import mock

import numpy as np
import pytest
from click.testing import CliRunner

from litdb import research
from litdb.commands.research_commands import research as research_cmd


class FakeResearcher:
    """Records how GPTResearcher was constructed."""

    instances: ClassVar[list] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.cfg = None
        FakeResearcher.instances.append(self)

    async def conduct_research(self):
        return "result"

    async def write_report(self):
        return "report"

    def get_research_context(self):
        return []

    def get_costs(self):
        return 0.0

    def get_research_images(self):
        return []

    def get_research_sources(self):
        return []


@pytest.fixture
def fake_gptr(monkeypatch):
    module = ModuleType("gpt_researcher")
    module.GPTResearcher = FakeResearcher
    monkeypatch.setitem(sys.modules, "gpt_researcher", module)
    monkeypatch.setattr(research, "get_config", dict)
    FakeResearcher.instances.clear()
    return FakeResearcher.instances


@pytest.mark.unit
def test_litdb_documents_are_used(fake_gptr, monkeypatch):
    """gpt_researcher ignores documents unless report_source says to use them."""
    monkeypatch.setattr(research, "litdb_documents", lambda q: ["doc"])
    research.deep_research("q", skip_refinement=True)
    kwargs = fake_gptr[0].kwargs
    assert kwargs["documents"] == ["doc"]
    assert kwargs["report_source"] == "langchain_documents"


@pytest.mark.unit
def test_web_source_skips_litdb_documents(fake_gptr, monkeypatch):
    monkeypatch.setattr(
        research, "litdb_documents", mock.Mock(side_effect=AssertionError)
    )
    research.deep_research("q", skip_refinement=True, source="web")
    assert fake_gptr[0].kwargs["report_source"] == "web"


@pytest.mark.unit
def test_research_env_keeps_environment_settings(monkeypatch):
    monkeypatch.setattr(research, "get_config", dict)
    monkeypatch.setenv("SMART_LLM", "openai:gpt-4o")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box:11434")
    research.research_env()
    assert os.environ["SMART_LLM"] == "openai:gpt-4o"
    assert os.environ["OLLAMA_BASE_URL"] == "http://gpu-box:11434"
    assert os.environ["FAST_LLM"] == "ollama:llama3.3"


@pytest.mark.unit
def test_research_env_toml_overrides_environment(monkeypatch):
    monkeypatch.setattr(
        research, "get_config", lambda: {"gpt-researcher": {"SMART_LLM": "x:y"}}
    )
    monkeypatch.setenv("SMART_LLM", "openai:gpt-4o")
    research.research_env()
    assert os.environ["SMART_LLM"] == "x:y"


def _llm_reply(text):
    return {"choices": [{"message": {"content": text}}]}


@pytest.fixture
def litdb_env(real_db, monkeypatch):
    """litdb_documents with a real db, fake embedding model, LLM and OpenAlex."""
    real_db.execute(
        "insert into sources(source, text, extra, embedding) values (?, ?, '{}', ?)",
        ("paper", "platinum catalysis", np.zeros(4, dtype=np.float32).tobytes()),
    )
    real_db.execute(
        "insert into fulltext(source, text) values ('paper', 'platinum catalysis')"
    )
    real_db.commit()
    monkeypatch.setattr(research, "get_db", lambda: real_db)
    # The default litdb.toml: no [gpt-researcher] or [llm] section.
    monkeypatch.setattr(
        research,
        "get_config",
        lambda: {"embedding": {"model": "fake"}, "openalex": {}},
    )
    monkeypatch.setattr(
        research,
        "get_model",
        lambda name: mock.Mock(encode=lambda x: np.zeros((1, 4), dtype=np.float32)),
    )
    oa = mock.Mock(return_value={"results": []})
    monkeypatch.setattr(research, "oa_query", oa)
    return oa


@pytest.mark.unit
def test_litdb_documents_without_gpt_researcher_config(litdb_env, monkeypatch):
    """The default litdb.toml has no [gpt-researcher] or [llm] section."""
    monkeypatch.setattr(
        research, "completion", lambda **kw: _llm_reply('{"queries": ["platinum"]}')
    )
    docs = research.litdb_documents("q")
    assert {d.metadata["type"] for d in docs} == {"vector search", "full-text"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "reply", ["no json here", '{"other": 1}', '{"queries": "a string"}', ""]
)
def test_litdb_documents_survives_bad_llm_json(litdb_env, monkeypatch, reply):
    monkeypatch.setattr(research, "completion", lambda **kw: _llm_reply(reply))
    docs = research.litdb_documents("q")
    assert [d.metadata["type"] for d in docs] == ["vector search"]


@pytest.mark.unit
def test_litdb_documents_fts_syntax_queries(litdb_env, monkeypatch):
    """FTS5 operators work, and invalid FTS5 falls back to plain words."""
    monkeypatch.setattr(
        research,
        "completion",
        lambda **kw: _llm_reply(
            '{"queries": ["platinum OR gold", "platinum (catalysis"]}'
        ),
    )
    docs = research.litdb_documents("q")
    assert [d.metadata["query"] for d in docs if d.metadata["type"] == "full-text"] == [
        "platinum OR gold",
        "platinum (catalysis",
    ]


@pytest.mark.unit
def test_oa_query_uses_search_param(monkeypatch):
    monkeypatch.setattr(research, "get_config", lambda: {"openalex": {}})
    with mock.patch.object(research, "get_data") as get_data:
        research.oa_query("CO, H2 and Pt")
    params = get_data.call_args.args[1]
    assert params["search"] == "CO, H2 and Pt"
    assert "filter" not in params


def _stream(*texts):
    return [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t))])
        for t in texts
    ]


@pytest.mark.unit
def test_refine_query_sends_questions_with_reply(monkeypatch, capsys):
    monkeypatch.setattr(research, "get_config", dict)
    calls = []

    def fake_completion(model, messages, stream):
        calls.append(list(messages))
        return _stream("Which ", "metal?") if len(calls) == 1 else _stream("Pt ", "CO")

    monkeypatch.setattr(research, "completion", fake_completion)
    with mock.patch("builtins.input", return_value="platinum"):
        assert research.refine_query("CO adsorption") == "Pt CO"
    assert {"role": "assistant", "content": "Which metal?"} in calls[1]
    assert "Pt CO\n" in capsys.readouterr().out


@pytest.mark.unit
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["q", "--source", "local"], "needs --doc-path"),
        (["q", "--doc-path", "docs"], "only used with --source local"),
    ],
)
def test_research_doc_path_requires_local_source(args, message):
    with mock.patch("litdb.commands.research_commands.deep_research") as dr:
        result = CliRunner().invoke(research_cmd, args)
    assert result.exit_code != 0
    assert message in result.output
    dr.assert_not_called()


@pytest.mark.unit
def test_research_passes_source(monkeypatch, tmp_path):
    monkeypatch.delenv("DOC_PATH", raising=False)
    with (
        mock.patch(
            "litdb.commands.research_commands.deep_research",
            return_value=("r", "", "", 0, [], []),
        ) as dr,
        mock.patch("litdb.commands.research_commands.Console"),
    ):
        result = CliRunner().invoke(
            research_cmd, ["q", "--source", "hybrid", "--doc-path", str(tmp_path)]
        )
    assert result.exit_code == 0, result.output
    assert dr.call_args.kwargs["source"] == "hybrid"
    assert os.environ["DOC_PATH"] == str(tmp_path)
