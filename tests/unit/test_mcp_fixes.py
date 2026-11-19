"""Regression tests for bugs fixed in litdb.mcp_server."""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import requests

pytest.importorskip("mcp")

from litdb import mcp_server

from .conftest import FakeModel


def emb(*values):
    return np.array(values, dtype=np.float32).tobytes()


@pytest.fixture
def mcp_db(real_db, tmp_path, monkeypatch):
    """The real_db, used by the MCP tools through the litdb env variable."""
    monkeypatch.setenv("litdb", str(tmp_path / "litdb.libsql"))
    return real_db


def insert(db, source, text, extra, embedding):
    db.execute(
        "insert into sources(source, text, extra, embedding) values (?, ?, ?, ?)",
        (source, text, json.dumps(extra) if extra is not None else None, embedding),
    )
    db.execute("insert into fulltext(source, text) values (?, ?)", (source, text))
    db.commit()


WORK = {
    "display_name": "Platinum catalysis",
    "authorships": [{"author": None}, {"author": {"display_name": "A. Author"}}],
    "abstract_inverted_index": {"Platinum": [0], "is": [1], "active": [2]},
    "primary_location": None,
    "publication_year": 2020,
}


def test_vsearch_embeds_query_with_the_db_model(mcp_db):
    """vsearch used all-MiniLM-L6-v2 whatever model made the db's embeddings."""
    insert(mcp_db, "a", "text", WORK, emb(1, 0, 0, 0))
    with patch("litdb.mcp_server.get_model", return_value=FakeModel()) as gm:
        mcp_server.vsearch("platinum", 1)
    gm.assert_called_once_with("fake")


def test_vsearch_shows_abstract_and_tolerates_null_author(mcp_db):
    """The abstract key never exists; OpenAlex stores an inverted index."""
    insert(mcp_db, "a", "full text", WORK, emb(1, 1, 1, 1))
    with patch("litdb.mcp_server.get_model", return_value=FakeModel()):
        out = mcp_server.vsearch("platinum", 1)
    assert "Abstract: Platinum is active" in out
    assert "Unknown, A. Author" in out
    assert "Error" not in out


def test_vsearch_orders_by_similarity(mcp_db):
    insert(mcp_db, "far", "x", {"display_name": "Far"}, emb(-1, 1, -1, 1))
    insert(mcp_db, "near", "x", {"display_name": "Near"}, emb(1, 1, 1, 1))
    insert(mcp_db, "mid", "x", {"display_name": "Mid"}, emb(1, 1, 1, 0))
    with patch("litdb.mcp_server.get_model", return_value=FakeModel()):
        out = mcp_server.vsearch("q", 3)
    assert out.index("Near") < out.index("Mid") < out.index("Far")


def test_fulltext_search_with_fts5_punctuation(mcp_db):
    """A hyphen is FTS5 syntax, so 'density-functional' raised an error."""
    insert(mcp_db, "a", "density-functional theory", WORK, emb(1, 0, 0, 0))
    out = mcp_server.fulltext_search("density-functional", 3)
    assert "Source: a" in out


def test_find_similar_excludes_the_source_when_not_first(mcp_db):
    """The source was assumed to be the first result, but ties can put it later."""
    for name in ("a", "b", "c"):
        insert(mcp_db, name, "x", {"display_name": name}, emb(1, 1, 1, 1))
    out = mcp_server.find_similar("c", 2)
    assert "Source: c" not in out
    assert "Source: a" in out and "Source: b" in out


def test_find_similar_without_embedding(mcp_db):
    insert(mcp_db, "a", "x", {}, None)
    assert "no embedding" in mcp_server.find_similar("a", 2)


def test_source_details_with_null_text(mcp_db):
    """text[:1000] on a null text was reported as a formatting error."""
    insert(mcp_db, "a", None, {"display_name": "T"}, emb(1, 0, 0, 0))
    out = mcp_server.get_source_details("a")
    assert out.startswith("Title: T")


def test_source_details_shows_abstract(mcp_db):
    insert(mcp_db, "a", "text", WORK, emb(1, 0, 0, 0))
    out = mcp_server.get_source_details("a")
    assert "Abstract:\nPlatinum is active" in out


def test_openalex_uses_search_param():
    """A comma in a default.search filter value splits the filter."""
    resp = MagicMock()
    resp.json.return_value = {"results": [WORK], "meta": {"count": 1}}
    with patch("litdb.mcp_server.requests.get", return_value=resp) as get:
        out = mcp_server.openalex("platinum, oxide", 1)
    params = get.call_args.args[1]
    assert params["search"] == "platinum, oxide"
    assert "filter" not in params
    assert "Platinum is active" in out


def test_openalex_http_error_is_reported():
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.HTTPError("503")
    with patch("litdb.mcp_server.requests.get", return_value=resp):
        assert "OpenAlex request failed" in mcp_server.openalex("q")


def test_install_stores_absolute_db_path(tmp_path, monkeypatch):
    """A relative path was stored as given, but Claude Desktop runs elsewhere."""
    (tmp_path / "litdb.libsql").write_text("")
    cfgfile = tmp_path / "claude.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["litdb_mcp", "install", "litdb.libsql"])
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "os.path.expanduser", lambda p: str(cfgfile) if "Claude" in p else p
    )
    monkeypatch.setattr("shutil.which", lambda name: "/bin/litdb_mcp")
    mcp_server.main()
    env = json.loads(cfgfile.read_text())["mcpServers"]["litdb"]["env"]
    assert env["litdb"] == str(tmp_path / "litdb.libsql")
    assert env["LITDB_ROOT"] == str(tmp_path)


def test_install_without_db_argument(monkeypatch, tmp_path):
    """sys.argv[2] raised IndexError."""
    monkeypatch.setattr("sys.argv", ["litdb_mcp", "install"])
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path / "c.json"))
    with pytest.raises(SystemExit, match="Usage"):
        mcp_server.main()
