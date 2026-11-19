"""Regression tests for bugs fixed in litdb.summary."""

import json
from unittest import mock

import pytest

from litdb import summary


@pytest.mark.unit
def test_parse_does_not_rewrite_valid_json():
    text = '{"1": ["Pt3Ni alloys with a 3:1 ratio", "time 10:30"]}'
    assert summary.robust_json_parse(text) == json.loads(text)


@pytest.mark.unit
def test_parse_skips_bracketed_preamble():
    text = 'Topics for articles [1] and [2]:\n{"1": ["a"], "2": ["b"]}'
    assert summary.robust_json_parse(text) == {"1": ["a"], "2": ["b"]}


@pytest.mark.unit
def test_parse_braces_inside_strings():
    text = 'Here: {"1": ["set {A} } of things"]} done'
    assert summary.robust_json_parse(text) == {"1": ["set {A} } of things"]}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({"type": "article", "type_crossref": None}, True),
        ({"type": "preprint"}, True),
        ({"type_crossref": "journal-article"}, True),
        ({"type_crossref": "posted-content"}, True),
        ({"type": "editorial"}, False),
        ({}, False),
    ],
)
def test_is_article(extra, expected):
    """OpenAlex no longer returns type_crossref; type must be used."""
    assert summary.is_article(extra) is expected


@pytest.mark.unit
def test_get_articles_since_uses_openalex_type(real_db, monkeypatch):
    rows = [
        ("new", "t", {"type": "article", "type_crossref": None}),
        ("pre", None, {"type": "preprint"}),
        ("ed", "t", {"type": "editorial"}),
        ("file", "t", None),
    ]
    for source, text, extra in rows:
        real_db.execute(
            "insert into sources(source, text, extra, date_added) "
            "values (?, ?, ?, date('now'))",
            (source, text, json.dumps(extra) if extra else None),
        )
    real_db.commit()
    monkeypatch.setattr(summary, "get_db", lambda: real_db)
    articles = summary.get_articles_since("yesterday")
    assert [(s, t) for s, t, _ in articles] == [("new", "t"), ("pre", "")]


@pytest.mark.unit
def test_aggregate_topics_tolerates_prose_and_bad_values():
    reply = 'Sure!\n{"Catalysis": ["Pt", "Pd"], "Bad": "not a list"}\nDone.'
    with mock.patch.object(summary, "get_completion", return_value=reply):
        assert summary.aggregate_topics(["Pt"], "m") == {"Catalysis": ["Pt", "Pd"]}


@pytest.mark.unit
def test_format_org_mode_escapes_headings_and_lists_other():
    article = ("doi1", "t", {"citation": "Smith 2024"})
    out = summary.format_org_mode(
        {"Catalysis": ["Pt"]},
        {"Catalysis": {"Pt": [article]}},
        {("Catalysis", "Pt"): "Intro\n* a bullet\n** bold start"},
        other=[("doi2", "t", {"citation": None})],
    )
    lines = out.splitlines()
    assert [ln for ln in lines if ln.startswith("*")] == [
        "* Catalysis",
        "** Pt",
        "*** References",
        "* Other articles",
    ]
    assert "1. doi2" in lines


@pytest.mark.unit
def test_generate_summary_keeps_misclassified_articles(tmp_path, monkeypatch):
    articles = [
        ("a", "text a", {"citation": "A 2024"}),
        ("b", "text b", {"citation": "B 2024"}),
        ("c", "text c", {"citation": "C 2024"}),
    ]
    monkeypatch.setattr(summary, "get_config", dict)
    monkeypatch.setattr(summary, "get_articles_since", lambda since: articles)
    monkeypatch.setattr(
        summary,
        "extract_topics_batch",
        lambda arts, model: (["Pt"], {}),
    )
    monkeypatch.setattr(
        summary, "aggregate_topics", lambda topics, model: {"Catalysis": ["Pt"]}
    )
    monkeypatch.setattr(
        summary,
        "classify_articles_batch",
        lambda arts, structure, model: {
            "a": ("Catalysis", "Pt"),
            "b": ("Catalysis", "Platinum"),  # not in the structure
            "c": (None, None),
        },
    )
    summarized = []
    monkeypatch.setattr(
        summary,
        "generate_subtopic_summary",
        lambda arts, sub, model: summarized.append(sub) or "Summary.",
    )
    out = tmp_path / "news.org"
    summary.generate_summary(output_file=str(out), model="m")
    text = out.read_text()
    assert summarized == ["Pt"]
    assert "A 2024" in text
    assert "B 2024" in text
    assert "C 2024" in text
