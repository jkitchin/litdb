"""Regression tests for bugs fixed in the streamlit app (litdb.app)."""

import importlib
import json
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from .conftest import FakeModel

WORK = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1/x",
    "title": None,
    "display_name": "Platinum catalysis",
    "type": "article",
    "publication_year": 2020,
    "authorships": [{"author": None}, {"author": {"display_name": "A. Author"}}],
    "abstract_inverted_index": {"is": [1], "Platinum": [0], "active": [2]},
}


@pytest.fixture
def app(real_db, tmp_path, monkeypatch):
    """litdb.app, imported with its db and config pointing at real_db."""
    cfg = {
        "root": str(tmp_path),
        "embedding": {"model": "fake"},
        "openalex": {"email": "test@example.com"},
        "llm": {"model": "fake-llm"},
    }
    sys.modules.pop("litdb.app", None)
    with (
        patch("litdb.utils.get_config", return_value=cfg),
        patch("litdb.db.get_db", return_value=real_db),
    ):
        module = importlib.import_module("litdb.app")
    monkeypatch.setattr(module, "get_model", lambda name: FakeModel(), raising=False)
    yield module
    sys.modules.pop("litdb.app", None)


def emb(*values):
    return np.array(values, dtype=np.float32).tobytes()


def insert(db, source, text, extra, embedding=None):
    db.execute(
        "insert into sources(source, text, extra, embedding) values (?, ?, ?, ?)",
        (source, text, json.dumps(extra) if extra is not None else None, embedding),
    )
    db.execute("insert into fulltext(source, text) values (?, ?)", (source, text))
    db.commit()


def run_tab(name, **session):
    """Return an AppTest that runs the tab function NAME of litdb.app."""
    at = AppTest.from_string(f"from litdb import app\napp.{name}()", default_timeout=30)
    for key, value in session.items():
        at.session_state[key] = value
    return at.run()


def button(at, label):
    return next(b for b in at.button if b.label == label)


# --- add_work -------------------------------------------------------------


def test_add_work_never_prompts_and_fails_when_not_found(app):
    """citing=True prompted with input(), which hangs the server, and a work
    OpenAlex did not know was reported as added."""
    with (
        patch("litdb.app._db_add_work", return_value=None) as add,
        pytest.raises(ValueError, match="not found"),
    ):
        app.add_work("10.1/x", citing=True)
    add.assert_called_once_with("https://doi.org/10.1/x", yes=True, citing=True)


# --- search helpers -------------------------------------------------------


def test_vector_search_is_ordered_by_distance(app, real_db):
    insert(real_db, "far", "x", {}, emb(-1, 1, -1, 1))
    insert(real_db, "near", "x", {}, emb(1, 1, 1, 1))
    insert(real_db, "mid", "x", {}, emb(1, 1, 1, 0))
    assert [r[0] for r in app.vector_search("q", 3)] == ["near", "mid", "far"]


def test_fulltext_search_with_fts5_punctuation(app, real_db):
    insert(real_db, "a", "density-functional theory", {})
    sql = "select source from fulltext where text match ? limit ?"
    assert app.fulltext_search(sql, "density-functional", 5) == [("a",)]


def test_snippet_is_escaped(app):
    """Snippets are rendered as HTML, so document text could inject markup."""
    snippet = f"<script>x</script> {app.SNIPPET_START}Pt{app.SNIPPET_END}"
    assert app.snippet_html(snippet) == "&lt;script&gt;x&lt;/script&gt; <b>Pt</b>"


def test_preview_and_citation_tolerate_missing_values(app):
    assert app.preview(None, 10) == ""
    assert app.preview("abc", 10) == "abc"
    citation = app.format_citation(json.dumps(WORK))
    assert citation.startswith("Unknown, A. Author. (2020)")


# --- OpenAlex and Semantic Scholar tabs ------------------------------------


def test_openalex_buttons_work_after_the_search(app):
    """The buttons were inside `if search_submitted`, so their click (a rerun
    with the form not submitted) did nothing."""
    get_data = MagicMock(return_value={"results": [WORK]})
    with (
        patch("litdb.openalex.get_data", get_data),
        patch("litdb.app.add_work") as add,
    ):
        at = AppTest.from_string(
            "from litdb import app\napp.tab_openalex_search()", default_timeout=30
        ).run()
        at.text_input[0].set_value("platinum, oxide")
        at.button[0].click().run()
        assert get_data.call_args.args[1]["search"] == "platinum, oxide"
        assert "Platinum is active" in " ".join(m.value for m in at.markdown)

        button(at, "📚 Add References").click().run()
    add.assert_called_once_with(WORK["doi"], references=True)
    assert any("References added" in s.value for s in at.success)


def test_semantic_scholar_ids(app):
    """externalIds may be null, and OpenAlex does not know arxiv urls."""
    assert app.semantic_scholar_id({"externalIds": None}) is None
    assert (
        app.semantic_scholar_id({"externalIds": {"ArXiv": "2101.00001"}})
        == "https://doi.org/10.48550/arXiv.2101.00001"
    )
    assert (
        app.semantic_scholar_id({"externalIds": {"DOI": "10.1/x"}})
        == "https://doi.org/10.1/x"
    )


# --- reviewers ------------------------------------------------------------


def test_reviewer_rows_tolerate_nulls(app):
    extra = json.dumps({"authorships": [{"author": None}, {"author": {"id": "A1"}}]})
    authors = {
        "results": [
            {
                "id": "A1",
                "display_name": "Ann",
                "summary_stats": None,
                "last_known_institutions": None,
                "affiliations": [{"institution": None}],
            }
        ]
    }
    with patch("litdb.openalex.get_data", return_value=authors):
        counts, rows = app.reviewer_rows([("s", "t", extra, 0.1), ("f", "t", None, 0)])
    assert counts == {"A1": 1}
    assert rows[0]["h_index"] == 0
    assert rows[0]["institution"] == "Unknown"


# --- chat -----------------------------------------------------------------


def test_chat_history_keeps_the_typed_prompt(app):
    """The prompt with the retrieved text was stored, redisplayed, and resent."""
    chunk = MagicMock()
    chunk.choices[0].delta.content = "answer"
    with (
        patch("litdb.app.get_rag_content", return_value=("RETRIEVED", "refs")),
        patch("litdb.app.completion", return_value=[chunk]) as completion,
    ):
        at = run_tab("tab_chat")
        at.chat_input[0].set_value("what is Pt?").run()
        sent = completion.call_args.kwargs["messages"]
        assert "RETRIEVED" in sent[-1]["content"]
        assert at.session_state["messages"][0] == {
            "role": "user",
            "content": "what is Pt?",
        }

        at.chat_input[0].set_value("and Pd?").run()
        sent = completion.call_args.kwargs["messages"]
    assert sent[0]["content"] == "what is Pt?"
    assert "RETRIEVED" in sent[-1]["content"]


# --- add content ----------------------------------------------------------


def test_doi_tab_buttons_use_the_stored_key(app):
    """The buttons of the added works were dead, and used the DOI as typed
    instead of the key the work was stored under."""
    with patch("litdb.app.add_work", return_value="https://doi.org/10.1/x") as add:
        at = run_tab("tab_add_content")
        at.selectbox[0].set_value("DOI").run()
        at.text_area[0].set_value("10.1/X")
        button(at, "Add DOI(s)").click().run()
        add.reset_mock()
        button(at, "📝 Add Citing").click().run()
    add.assert_called_once_with("https://doi.org/10.1/x", citing=True)


def test_orcid_tab_adds_the_author(app):
    """The tab reported success without adding anything."""
    with patch("litdb.app.add_source_item") as add:
        at = run_tab("tab_add_content")
        at.selectbox[0].set_value("ORCID").run()
        at.text_input[0].set_value("0000-0003-2625-9232")
        button(at, "Add Works").click().run()
    add.assert_called_once_with("0000-0003-2625-9232")


def test_bibtex_text_is_added(app):
    """The BibTeX tab reported success without adding anything."""
    seen = {}

    def add_bibtex(bibfile):
        with open(bibfile) as f:
            seen["text"] = f.read()

    with patch("litdb.db.add_bibtex", add_bibtex):
        app.add_bibtex_text("@article{a, doi={10.1/x}}")
    assert seen["text"] == "@article{a, doi={10.1/x}}"


def test_uploads_are_kept(app, tmp_path):
    """Uploads were added from a temporary file that was then deleted."""
    upload = MagicMock()
    upload.name = "paper.txt"
    upload.getvalue.return_value = b"one"
    first = app.save_upload(upload)
    upload.getvalue.return_value = b"two"
    second = app.save_upload(upload)
    assert first == str(tmp_path / "uploads" / "paper.txt")
    assert second == str(tmp_path / "uploads" / "paper-1.txt")
    with open(first, "rb") as f:
        assert f.read() == b"one"


def test_files_to_index_skips_unchanged_bib(real_db, tmp_path):
    from litdb.commands.manage import _files_to_index, _record_indexed

    d = tmp_path / "docs"
    d.mkdir()
    (d / "refs.bib").write_text("")
    (d / "notes.md").write_text("x")
    assert [f.name for f in _files_to_index(real_db, d)] == ["notes.md", "refs.bib"]
    _record_indexed(real_db, d)
    real_db.execute(
        "insert into sources(source, text) values (?, 'x')", (str(d / "notes.md"),)
    )
    import os

    os.utime(d / "refs.bib", (0, 0))
    assert _files_to_index(real_db, d) == []


# --- filters, stats, export ------------------------------------------------


def test_save_and_delete_query(app, real_db):
    """Save Query and Delete only showed messages."""
    assert app.save_query("author.id:A1", "me")
    assert not app.save_query("author.id:A1", "again")
    assert real_db.execute("select filter, description from queries").fetchall() == [
        ("author.id:A1", "me")
    ]
    app.delete_query("author.id:A1")
    assert real_db.execute("select * from queries").fetchall() == []


def test_tag_counts_count_sources(app, real_db):
    """The tags table has one row per tag, so every count was 1."""
    from litdb.db import tag_source

    for source in ("a", "b"):
        insert(real_db, source, "x", {})
        tag_source(real_db, source, "pt")
    tag_source(real_db, "a", "pd")
    assert app.tag_counts() == [("pt", 2), ("pd", 1)]


def test_bibtex_export(app, real_db):
    """BibTeX export showed a fixed example entry."""
    insert(real_db, WORK["doi"], "x", WORK)
    insert(real_db, "/a/file.pdf", "x", None)
    text, skipped = app.bibtex_entries(app.export_rows("All sources"))
    assert "10.1/x" in text
    assert skipped == ["/a/file.pdf"]


def test_raw_sql_runs_once_and_commits(app, real_db):
    """The statement was executed twice and never committed."""
    columns, rows = app.run_sql("insert into tags(tag) values ('t')")
    assert columns is None
    assert real_db.execute("select count(*) from tags").fetchone()[0] == 1
    columns, rows = app.run_sql("select tag from tags")
    assert (columns, rows) == (["tag"], [("t",)])


# --- research and COA ------------------------------------------------------


def test_research_back_button_does_not_rerun_the_research(app):
    """After a failure, Back to Input was shown in the running step, so clicking
    it ran the research again."""
    with patch("litdb.research.deep_research", side_effect=RuntimeError("boom")) as dr:
        at = run_tab(
            "tab_research",
            research_step="running",
            research_type="Deep Research (gpt_researcher)",
            research_query="q",
        )
        assert any("boom" in e.value for e in at.error)
        button(at, "Back to Input").click().run()
    assert dr.call_count == 1
    assert at.session_state["research_step"] == "input"


def test_nsf_coa_uses_the_returned_file(app, tmp_path):
    """get_coa saves to ~/Downloads, but the tab looked in a temp directory."""
    import pandas as pd

    xlsx = tmp_path / "coa.xlsx"
    pd.DataFrame({"name": ["A", "B"]}).to_excel(xlsx, sheet_name="Table 4", index=False)
    with patch("litdb.coa.get_coa", return_value=str(xlsx)):
        at = run_tab("tab_nsf_coa")
        at.text_input[0].set_value("0000-0003-2625-9232")
        button(at, "Generate COA").click().run()
    assert not at.error
    assert any("COA generated" in s.value for s in at.success)


@pytest.mark.parametrize(
    "tab",
    [
        "tab_search",
        "tab_openalex_search",
        "tab_semantic_scholar_search",
        "tab_suggest_reviewers",
        "tab_chat",
        "tab_add_content",
        "tab_library_browser",
        "tab_manage_filters",
        "tab_stats_analytics",
        "tab_export",
        "tab_research",
        "tab_nsf_coa",
    ],
)
def test_every_tab_renders(app, real_db, tab):
    insert(real_db, "a", None, {"title": None}, emb(1, 1, 1, 1))
    at = run_tab(tab)
    assert not at.exception
