"""Regression tests for bugs fixed in the commands package."""

import contextlib
import importlib
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from click.testing import CliRunner

from litdb.cli import cli


def run(*args, **kwargs):
    return CliRunner().invoke(cli, list(args), **kwargs)


# --- db helpers ---------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("text", ["", "   ", None])
def test_embed_text_handles_empty_text(text):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    from litdb.db import embed_text

    from .conftest import DIM, FakeModel

    splitter = RecursiveCharacterTextSplitter(chunk_size=100, chunk_overlap=10)
    emb = np.frombuffer(embed_text(FakeModel(), splitter, text), dtype=np.float32)
    assert emb.shape == (DIM,)


@pytest.mark.unit
def test_add_empty_text_file(real_db, tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    result = run("add", str(f))
    assert result.exit_code == 0, result.output
    assert real_db.execute(
        "select 1 from sources where source = ?", (str(f),)
    ).fetchone()


# --- add: routing -------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    ["W2288114809", "https://openalex.org/W2288114809", "doi:10.1/abc"],
)
def test_add_routes_works_to_add_work(source):
    with patch("litdb.commands.manage.add_work") as add_work:
        result = run("add", source)
    assert result.exit_code == 0, result.output
    assert add_work.call_args.args[0] == source


@pytest.mark.unit
def test_add_bare_orcid_adds_author():
    with patch("litdb.commands.manage.add_author") as add_author:
        run("add", "0000-0002-1825-009X")
    add_author.assert_called_once_with("https://orcid.org/0000-0002-1825-009X")


@pytest.mark.unit
def test_add_url_mentioning_orcid_is_a_web_page():
    resp = MagicMock(text="<html><body>hello</body></html>", headers={})
    with (
        patch("litdb.commands.manage.add_author") as add_author,
        patch("litdb.commands.manage.requests.get", return_value=resp) as get,
        patch("litdb.commands.manage.add_source") as add_source,
    ):
        result = run("add", "https://example.org/what-is-an-orcid")
    assert result.exit_code == 0, result.output
    add_author.assert_not_called()
    assert get.call_args.kwargs["timeout"]
    resp.raise_for_status.assert_called_once()
    assert add_source.call_args.args == (
        "https://example.org/what-is-an-orcid",
        "hello",
    )


@pytest.mark.unit
def test_add_extension_is_case_insensitive():
    with patch("litdb.commands.manage.add_pdf") as add_pdf:
        result = run("add", "PAPER.PDF")
    assert result.exit_code == 0, result.output
    add_pdf.assert_called_once_with(os.path.abspath("PAPER.PDF"))


@pytest.mark.unit
def test_add_with_tag_tags_the_stored_work(real_db):
    from litdb.db import add_source

    def fake_add_work(source, *args):
        add_source("https://doi.org/10.1/abc", "a paper")
        return "https://doi.org/10.1/abc"

    with patch("litdb.commands.manage.add_work", side_effect=fake_add_work):
        result = run("add", "10.1/ABC", "-t", "catalysis")
    assert result.exit_code == 0, result.output
    row = real_db.execute(
        """select tags.tag from tags
        join source_tag on source_tag.tag_id = tags.rowid
        join sources on sources.rowid = source_tag.source_id
        where sources.source = 'https://doi.org/10.1/abc'"""
    ).fetchone()
    assert row == ("catalysis",)


# --- remove, index, reindex, init -------------------------------------------


@pytest.mark.unit
def test_remove_deletes_fulltext_and_tags(real_db):
    from litdb.db import add_source

    add_source("a.txt", "unique words here")
    run("add-tag", "a.txt", "-t", "t")
    result = run("remove", "a.txt")
    assert result.exit_code == 0, result.output
    for table in ("sources", "fulltext"):
        assert real_db.execute(
            f"select count(*) from {table} where source = 'a.txt'"
        ).fetchone() == (0,)
    assert real_db.execute("select count(*) from source_tag").fetchone() == (0,)


@pytest.mark.unit
def test_index_does_not_reread_unchanged_bib(real_db, tmp_path):
    d = tmp_path / "papers"
    d.mkdir()
    bib = d / "refs.bib"
    bib.write_text("@article{a, doi={10.1/abc}}")
    os.utime(bib, (0, 0))  # older than any index date

    with patch("litdb.commands.manage.add_bibtex") as add_bibtex:
        run("index", str(d))
        run("index", str(d))
    assert add_bibtex.call_count == 1


@pytest.mark.unit
def test_reindex_does_every_directory(real_db, tmp_path):
    dirs = []
    for name in ("one", "two"):
        d = tmp_path / name
        d.mkdir()
        (d / f"{name}.md").write_text(f"notes {name}")
        dirs.append(d)
    real_db.executemany(
        "insert into directories(path, last_updated) values (?, NULL)",
        [(str(d),) for d in dirs],
    )
    real_db.commit()

    result = run("reindex")
    assert result.exit_code == 0, result.output
    for d in dirs:
        src = str(d / f"{d.name}.md")
        assert real_db.execute(
            "select 1 from sources where source = ?", (src,)
        ).fetchone(), src


@pytest.mark.unit
def test_init_refuses_to_overwrite_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "litdb.toml").write_text("[openalex]\nemail = 'x'\n")
    with patch("litdb.commands.manage.init_litdb") as init_litdb:
        result = run("init")
    assert result.exit_code != 0
    assert "already exists" in result.output
    init_litdb.assert_not_called()


# --- search -------------------------------------------------------------------


@contextlib.contextmanager
def vsearch_env(rows):
    """Patch vsearch's db, model and config; the db returns ROWS."""
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = rows
    model = MagicMock()
    model.encode.return_value = np.zeros((1, 3), dtype=np.float32)
    cfg = {"embedding": {"model": "m", "cross-encoder": "ce"}}
    with (
        patch("litdb.commands.search.get_search_db", return_value=db),
        patch("litdb.commands.search.get_model", return_value=model),
        patch("litdb.commands.search.get_config", return_value=cfg),
    ):
        yield db


@pytest.mark.unit
def test_vsearch_max_steps_stops_without_prompting():
    rows = [("https://doi.org/10.1/a", "t", "{}", 0.1)]
    with vsearch_env(rows), patch("builtins.input") as ask:
        result = run("vsearch", "q", "-i", "-m", "1")
    assert result.exit_code == 0, result.output
    ask.assert_not_called()


@pytest.mark.unit
def test_vsearch_iterative_only_expands_works():
    rows = [
        ("https://doi.org/10.1/a", "t", "{}", 0.1),
        ("/home/me/notes.pdf", "t", "{}", 0.2),
    ]
    with vsearch_env(rows), patch("litdb.commands.search.add_work") as add_work:
        result = run("vsearch", "q", "-i", "-m", "2")
    assert result.exit_code == 0, result.output
    assert [c.args[0] for c in add_work.call_args_list] == ["https://doi.org/10.1/a"]


@pytest.mark.unit
def test_vsearch_cross_encode_puts_best_first():
    rows = [("worse", "t1", "{}", 0.1), ("better", "t2", "{}", 0.2)]
    ce = MagicMock()
    ce.predict.return_value = np.array([0.2, 0.9])
    with (
        vsearch_env(rows),
        patch("sentence_transformers.cross_encoder.CrossEncoder", return_value=ce),
    ):
        result = run("vsearch", "q", "-x", "-f", "{{ source }} {{ score|round(2) }}\n")
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line]
    assert lines == ["better 0.9", "worse 0.2"]


@pytest.mark.unit
def test_vsearch_emacs_escapes_quotes():
    rows = [("s", 'He said "hi" \\ bye', "{}", 0.1)]
    with vsearch_env(rows):
        result = run("vsearch", "q", "--emacs")
    assert '\\"hi\\" \\\\ bye' in result.output


@pytest.mark.unit
def test_rich_output_keeps_bracketed_text(real_db):
    from litdb.db import add_source

    add_source("s1", "CO oxidation on [Pt] and [b]bold[/b]")
    result = run("show", "s1")
    assert "CO oxidation on [Pt] and [b]bold[/b]" in result.output


@pytest.mark.unit
@pytest.mark.parametrize("query", ["density-functional", "Pt(111)", "e.g."])
def test_fulltext_with_punctuation(real_db, query):
    from litdb.db import add_source

    add_source("s1", "density-functional theory of Pt(111), e.g. slabs")
    with patch("litdb.commands.search.get_search_db", return_value=real_db):
        result = run("fulltext", query)
    assert result.exit_code == 0, result.output
    assert "s1" in result.output


@pytest.mark.unit
def test_screenshot_runs_vsearch():
    with (
        patch("PIL.ImageGrab.grabclipboard", return_value=object()),
        patch("pytesseract.image_to_string", return_value="some text"),
        patch("litdb.commands.search.vsearch.callback") as vsearch,
    ):
        result = run("screenshot")
    assert result.exit_code == 0, result.output
    assert vsearch.call_args.kwargs["query"] == ("some text",)


# --- export -------------------------------------------------------------------


@pytest.mark.unit
def test_citation_unknown_source(real_db):
    result = run("citation", "missing")
    assert result.exit_code == 0, result.output
    assert "No entry found for missing" in result.output


@pytest.mark.unit
def test_bibtex_prints_only_bibtex(real_db):
    from litdb.db import add_source

    add_source("s1", "t", {"id": "W1"})
    with patch("litdb.commands.export.dump_bibtex", return_value="@article{x}"):
        result = run("bibtex", "s1")
    assert result.output.strip() == "@article{x}"


# --- openalex commands ----------------------------------------------------------


@pytest.mark.unit
def test_watch_adds_the_filter(real_db):
    with patch(
        "litdb.commands.openalex_commands.get_data", return_value={"results": [{}]}
    ):
        result = run("watch", "author.id:A1")
    assert result.exit_code == 0, result.output
    assert real_db.execute("select filter from queries").fetchall() == [
        ("author.id:A1",)
    ]


@pytest.mark.unit
def test_watch_rejects_invalid_filter(real_db):
    with patch(
        "litdb.commands.openalex_commands.get_data", return_value={"results": []}
    ):
        result = run("watch", "bogus")
    assert "does not seem valid" in result.output
    assert real_db.execute("select count(*) from queries").fetchone() == (0,)


@pytest.mark.unit
@pytest.mark.parametrize("command", ["citing", "related"])
def test_citing_related_unknown_doi(real_db, command):
    with patch(
        "litdb.commands.openalex_commands.get_data", return_value={"results": []}
    ):
        result = run(command, "10.1/missing")
    assert result.exit_code == 0, result.output
    assert "does not seem valid" in result.output


@pytest.mark.unit
def test_follow_remove_does_not_download_and_handles_all(real_db):
    real_db.executemany(
        "insert into queries(filter) values (?)",
        [
            ("author.orcid:https://orcid.org/0000-0000-0000-0001",),
            ("author.orcid:https://orcid.org/0000-0000-0000-0002",),
        ],
    )
    real_db.commit()
    with patch("litdb.commands.openalex_commands.add_author") as add_author:
        result = run("follow", "-r", "0000-0000-0000-0001", "0000-0000-0000-0002")
    assert result.exit_code == 0, result.output
    add_author.assert_not_called()
    assert real_db.execute("select count(*) from queries").fetchone() == (0,)


@pytest.mark.unit
def test_unpaywall_request_and_null_locations():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"title": "T", "is_oa": False, "oa_locations": None}
    cfg = {"openalex": {"email": "test@example.com"}}
    with (
        patch("litdb.commands.openalex_commands.get_config", return_value=cfg),
        patch(
            "litdb.commands.openalex_commands.requests.get", return_value=resp
        ) as get,
    ):
        result = run("unpaywall", "https://doi.org/10.1/abc")
    assert result.exit_code == 0, result.output
    url, params = get.call_args.args
    assert url == "https://api.unpaywall.org/v2/10.1/abc"
    assert params == {"email": "test@example.com"}


# --- crossref / fromtext -----------------------------------------------------------


@pytest.mark.unit
def test_crossref_author_names():
    from litdb.commands.data_processing import _crossref_author

    assert _crossref_author({"given": "A", "family": "B"}) == "A B"
    assert _crossref_author({"family": "B"}) == "B"
    assert _crossref_author({"name": "The Consortium"}) == "The Consortium"


@pytest.mark.unit
def test_parse_selection():
    from litdb.commands.data_processing import _parse_selection

    assert _parse_selection("0  2", 3) == [0, 2]
    assert _parse_selection("", 3) == []
    for bad in ("3", "x", "-1"):
        with pytest.raises(ValueError):
            _parse_selection(bad, 3)


# --- review, web, cli import -------------------------------------------------------


@pytest.mark.unit
def test_review_bad_date(real_db):
    result = run("review", "-s", "not a date at all")
    assert result.exit_code != 0
    assert "Could not understand the date" in result.output


@pytest.mark.unit
def test_web_encodes_query():
    with patch("litdb.commands.utilities.webbrowser.open") as wopen:
        run("web", "C&H", "bonds", "-g")
    urls = [c.args[0] for c in wopen.call_args_list]
    assert "https://www.google.com/search?q=C%26H+bonds" in urls


@pytest.mark.unit
def test_importing_cli_does_not_open_the_db():
    import litdb.cli

    with patch("litdb.db.get_db") as get_db:
        importlib.reload(litdb.cli)
    get_db.assert_not_called()


@pytest.mark.unit
def test_remove_keeps_vector_search_working(real_db):
    """libsql's vector index loses neighbors of deleted rows unless rebuilt."""
    from litdb.db import remove_source

    rng = np.random.default_rng(0)
    vecs = rng.normal(size=(200, 4)).astype(np.float32)
    real_db.executemany(
        "insert into sources(source, text, embedding) values (?, '', ?)",
        [(f"s{i}", v.tobytes()) for i, v in enumerate(vecs)],
    )
    real_db.commit()

    failures = 0
    for victim in range(0, 200, 20):
        remove_source(real_db, f"s{victim}")
        q = (vecs[victim] + 0.001).tobytes()
        real_db.execute(
            "insert into sources(source, text, embedding) values (?, '', ?)",
            (f"new{victim}", q),
        )
        real_db.commit()
        top = real_db.execute(
            """select source from vector_top_k('embedding_idx', ?, 3)
            join sources on sources.rowid = id""",
            (q,),
        ).fetchall()
        failures += (f"new{victim}",) not in top
    assert failures == 0


@pytest.mark.unit
def test_sql_commits_changes(real_db, tmp_path):
    import libsql

    result = run("sql", "insert into tags(tag) values ('x')")
    assert result.exit_code == 0, result.output
    other = libsql.connect(str(tmp_path / "litdb.libsql"))
    assert other.execute("select tag from tags").fetchall() == [("x",)]
