"""Unit tests for litdb.db (schema setup and adding works)."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from litdb import db as litdb_db

DIM = 4


class FakeModel:
    """Stand-in for SentenceTransformer that returns fixed-size embeddings."""

    def encode(self, texts):
        if isinstance(texts, str):
            return np.ones(DIM, dtype=np.float32)
        return np.ones((len(texts), DIM), dtype=np.float32)


def make_config(root, **openalex):
    """Return a litdb config dict rooted at ROOT."""
    return {
        "root": str(root),
        "embedding": {"model": "fake", "chunk_size": 1000, "chunk_overlap": 200},
        "openalex": {"email": "test@example.com", **openalex},
    }


@pytest.fixture
def config(tmp_path):
    """Patch litdb.db to use a temporary root and a fake embedding model."""
    cfg = make_config(tmp_path)
    with (
        patch("litdb.db.get_config", return_value=cfg),
        patch("litdb.db.get_model", return_value=FakeModel()),
    ):
        yield cfg


def tables(db):
    return {
        name
        for (name,) in db.execute(
            "select name from sqlite_master where type = 'table'"
        ).fetchall()
    }


# --- get_db -----------------------------------------------------------------


@pytest.mark.unit
def test_get_db_creates_schema(config):
    db = litdb_db.get_db()
    assert {"sources", "images", "tags", "source_tag", "metadata"} <= tables(db)


@pytest.mark.unit
def test_get_db_initializes_an_empty_file(config, tmp_path):
    """A db file left empty by a failed first run is initialized, not reused."""
    import libsql

    libsql.connect(str(tmp_path / "litdb.libsql")).close()
    db = litdb_db.get_db()
    assert "sources" in tables(db)


@pytest.mark.unit
def test_failed_model_load_leaves_no_partial_schema(config, tmp_path):
    with (
        patch("litdb.db.get_model", side_effect=OSError("download failed")),
        pytest.raises(OSError),
    ):
        litdb_db.get_db()
    # The next run sets the database up properly.
    assert {"sources", "images"} <= tables(litdb_db.get_db())


@pytest.mark.unit
def test_get_db_enables_foreign_keys_on_new_db(config):
    db = litdb_db.get_db()
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


@pytest.mark.unit
def test_get_db_adds_metadata_table_to_old_db(config):
    """Databases from before the metadata table get it (update-embeddings needs it)."""
    db = litdb_db.get_db()
    db.execute("drop table metadata")
    db.commit()
    assert "metadata" in tables(litdb_db.get_db())


@pytest.mark.unit
def test_get_db_warns_when_embedding_config_changes(config, capsys):
    litdb_db.get_db()
    config["embedding"]["chunk_size"] = 500
    litdb_db.get_db()
    out = capsys.readouterr().out
    assert "Embedding config has changed" in out
    assert "chunk_size: 1000 -> 500" in out


# --- limits and the citing prompt -------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "limit, expected",
    [(None, [1, 2, 3]), (-1, [1, 2, 3]), (-5, [1, 2, 3]), (0, []), (2, [1, 2])],
)
def test_apply_limit(limit, expected):
    assert litdb_db._apply_limit([1, 2, 3], limit) == expected


@pytest.mark.unit
def test_confirm_citing_below_trigger_or_yes():
    assert litdb_db._confirm_citing(50, 100, yes=False)
    assert litdb_db._confirm_citing(500, 100, yes=True)


@pytest.mark.unit
@pytest.mark.parametrize("answer, expected", [("", False), ("n", False), ("y", True)])
def test_confirm_citing_prompt_defaults_to_no(answer, expected):
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", return_value=answer),
    ):
        assert litdb_db._confirm_citing(500, 100, yes=False) is expected


@pytest.mark.unit
def test_confirm_citing_non_interactive_is_no():
    with patch("sys.stdin.isatty", return_value=False):
        assert not litdb_db._confirm_citing(500, 100, yes=False)


def citing_pages(n_pages, per_page=2, count=500):
    """Return get_data results for N_PAGES pages of citing works."""
    pages = []
    for p in range(n_pages):
        cursor = f"c{p + 1}" if p < n_pages - 1 else None
        results = [
            {"id": f"https://openalex.org/W{p}{i}", "doi": None, "title": None}
            for i in range(per_page)
        ]
        pages.append(
            {"meta": {"count": count, "next_cursor": cursor}, "results": results}
        )
    return pages


@pytest.fixture
def citing_env():
    """Patch the helpers _add_citing_works uses; yield the add_source mock."""
    with (
        patch("litdb.db.get_text", return_value="text"),
        patch("litdb.db.get_citation", return_value="citation"),
        patch("litdb.db.dump_bibtex", return_value="@article{}"),
        patch("litdb.db.add_source") as add_source,
    ):
        yield add_source


WORK = {"id": "https://openalex.org/W1"}
CFG = make_config("/tmp")


@pytest.mark.unit
def test_citing_prompt_is_asked_once(citing_env):
    with (
        patch("litdb.db.get_data", side_effect=citing_pages(3)),
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", return_value="y") as ask,
    ):
        litdb_db._add_citing_works(WORK, {}, CFG, False, None, verbose=True)
    assert ask.call_count == 1
    assert citing_env.call_count == 6


@pytest.mark.unit
def test_citing_last_page_with_null_cursor_is_added(citing_env):
    with patch("litdb.db.get_data", side_effect=citing_pages(1)):
        litdb_db._add_citing_works(WORK, {}, CFG, False, -1, verbose=False)
    assert citing_env.call_count == 2


@pytest.mark.unit
def test_max_citing_zero_downloads_none(citing_env):
    with patch("litdb.db.get_data", side_effect=citing_pages(2)) as get:
        litdb_db._add_citing_works(WORK, {}, CFG, False, 0, verbose=False)
    citing_env.assert_not_called()
    get.assert_not_called()


@pytest.mark.unit
def test_max_citing_stops_across_pages(citing_env):
    with patch("litdb.db.get_data", side_effect=citing_pages(3)) as get:
        litdb_db._add_citing_works(WORK, {}, CFG, False, 3, verbose=False)
    assert citing_env.call_count == 3
    assert get.call_count == 2


# --- add_work, add_author, update_filter, add_bibtex ------------------------


@pytest.mark.unit
def test_add_work_verbose_with_null_title(citing_env, capsys):
    data = {"id": "https://openalex.org/W1", "title": None, "doi": None}
    with (
        patch("litdb.db.get_config", return_value=CFG),
        patch("litdb.db.get_data", return_value=data),
    ):
        litdb_db.add_work("W1", verbose=True)
    assert "Adding: No title" in capsys.readouterr().out
    citing_env.assert_called_once()


@pytest.mark.unit
def test_add_author_unknown_id(capsys):
    with (
        patch("litdb.db.get_config", return_value=CFG),
        patch(
            "litdb.db.get_data",
            return_value={"meta": {"next_cursor": None}, "results": []},
        ),
        patch("litdb.db.add_work") as add_work,
    ):
        litdb_db.add_author("A0")
    add_work.assert_not_called()
    assert "No author found for A0" in capsys.readouterr().out


@pytest.mark.unit
def test_update_filter_without_api_key(config):
    """litdb init omits api_key when you have none; update_filter must cope."""
    page = {
        "meta": {"next_cursor": None},
        "results": [{"id": "https://openalex.org/W1", "doi": None}],
    }
    with (
        patch("litdb.db.get_data", return_value=page) as get,
        patch("litdb.db.get_text", return_value="text"),
        patch("litdb.db.dump_bibtex", return_value="@article{}"),
    ):
        results = litdb_db.update_filter("author.id:A1", silent=True)
    assert "api_key" not in get.call_args.args[1]
    assert [r[0] for r in results] == ["https://openalex.org/W1"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "doi, expected",
    [
        ("10.1/abc", "https://doi.org/10.1/abc"),
        (" 10.1/abc ", "https://doi.org/10.1/abc"),
        ("doi:10.1/abc", "https://doi.org/10.1/abc"),
        ("DOI: 10.1/abc", "https://doi.org/10.1/abc"),
        ("https://doi.org/10.1/abc", "https://doi.org/10.1/abc"),
        ("not a doi", None),
    ],
)
def test_normalize_doi(doi, expected):
    assert litdb_db._normalize_doi(doi) == expected


@pytest.mark.unit
def test_add_bibtex_handles_padded_and_prefixed_dois(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{a, DOI = { 10.1/abc }, title={t}}\n"
        "@article{b, doi = {doi:10.2/xyz}}\n"
        "@article{c, title = {no doi}}\n"
    )
    with patch("litdb.db.add_work") as add_work:
        litdb_db.add_bibtex(str(bib))
    assert [c.args[0] for c in add_work.call_args_list] == [
        "https://doi.org/10.1/abc",
        "https://doi.org/10.2/xyz",
    ]


# --- get_config ---------------------------------------------------------------


@pytest.mark.unit
def test_get_config_without_config_exits_with_failure(tmp_path, monkeypatch):
    from litdb.utils import get_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LITDB_ROOT", raising=False)
    with pytest.raises(SystemExit) as exc:
        get_config()
    assert exc.value.code not in (0, None)


@pytest.mark.unit
def test_get_model_is_cached():
    litdb_db.get_model.cache_clear()
    with patch("litdb.db.SentenceTransformer", side_effect=lambda n: MagicMock()) as st:
        assert litdb_db.get_model("m") is litdb_db.get_model("m")
    st.assert_called_once_with("m")
    litdb_db.get_model.cache_clear()
