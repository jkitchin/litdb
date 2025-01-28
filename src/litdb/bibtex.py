# From https://raw.githubusercontent.com/ourresearch/openalex-formatter/refs/heads/main/bibtex.py
import bibtexparser
from bibtexparser.bibdatabase import BibDatabase

entry_type_by_crossref_type = {
    "book-section": "inbook",
    "monograph": "article",
    "report": "article",
    "peer-review": "misc",
    "book-track": "inbook",
    "review": "article",  # new line added
    "preprint": "article",  # new line added
    "article": "article",  # new line added
    "journal-article": "article",
    "book-part": "inbook",
    "other": "misc",
    "paratext": "misc",  # new line added
    "book": "book",
    "journal-volume": "misc",
    "book-set": "misc",
    "reference-entry": "misc",
    "proceedings-article": "inproceedings",
    "journal": "misc",
    "component": "misc",
    "book-chapter": "inbook",
    "proceedings-series": "misc",
    "report-series": "misc",
    "proceedings": "proceedings",
    "standard": "misc",
    "reference-book": "book",
    "posted-content": "unpublished",
    "journal-issue": "misc",
    "dissertation": "phdthesis",
    "grant": "misc",
    "dataset": "misc",
    "book-series": "misc",
    "edited-book": "book",
    "standard-series": "misc",
}


def dump_bibtex(work):
    # entry_type = entry_type_by_crossref_type.get(work.get('type'))
    entry_type = entry_type_by_crossref_type.get(work.get("type_crossref"))

    # work_id = work.get('id')
    work_id = work.get("doi") or work.get("id")

    if not (entry_type and work_id):
        print(f"Unable to generate a bibtex entry for {work_id} ({entry_type})")
        return None

    entry = {
        "ENTRYTYPE": entry_type,
        "ID": work_id,
        "biburl": f"{work_id}.bib".replace("openalex.org", "api.openalex.org/works"),
    }

    if doi := work.get("doi"):
        entry["doi"] = doi.replace("https://doi.org/", "")

    bib_db = BibDatabase()
    _populate_entry(entry, work)

    bib_db.entries.append(entry)
    return bibtexparser.dumps(bib_db)


def _populate_entry(entry, work):
    entry_type = entry["ENTRYTYPE"]

    if entry_type == "article":
        _set_if(entry, "author", _author(work))
        _set_if(entry, "title", work.get("title"))
        _set_if(entry, "journal", _journal_name(work))
        _set_if(entry, "year", _year(work))
        _set_if(entry, "volume", _volume(work))
        _set_if(entry, "number", _issue(work))
        _set_if(entry, "pages", _pages(work))
    elif entry_type == "book":
        _set_if(entry, "author", _author(work))
        _set_if(entry, "title", work.get("title"))
        _set_if(entry, "publisher", _publisher(work))
        _set_if(entry, "year", _year(work))
    elif entry_type == "inbook":
        _set_if(entry, "author", _author(work))
        _set_if(entry, "title", work.get("title"))
        _set_if(entry, "publisher", _publisher(work))
        _set_if(entry, "booktitle", _book_title(work))
        _set_if(entry, "year", _year(work))
        _set_if(entry, "pages", _pages(work))
    elif entry_type == "inproceedings":
        _set_if(entry, "author", _author(work))
        _set_if(entry, "title", work.get("title"))
        _set_if(entry, "booktitle", _publisher(work))
        _set_if(entry, "year", _year(work))
        _set_if(entry, "pages", _pages(work))
    elif entry_type == "misc":
        _set_if(entry, "author", _author(work))
        _set_if(entry, "title", work.get("title"))
        _set_if(entry, "howpublished", (work.get("host_venue") or {}).get("url"))
        _set_if(entry, "year", _year(work))
    elif entry_type == "phdthesis":
        _set_if(entry, "author", _author(work))
        _set_if(entry, "title", work.get("title"))
        _set_if(entry, "school", _school(work))
        _set_if(entry, "year", _year(work))
    elif entry_type == "proceedings":
        _set_if(entry, "editor", _author(work))
        _set_if(entry, "title", work.get("title"))
        _set_if(entry, "series", _host_venue_display_name(work))
        _set_if(entry, "volume", _volume(work))
        _set_if(entry, "publisher", _publisher(work))
        _set_if(entry, "year", _year(work))
    elif entry_type == "unpublished":
        _set_if(entry, "author", _author(work))
        _set_if(entry, "title", work.get("title"))
        _set_if(entry, "year", _year(work))
        _set_if(entry, "howpublished", (work.get("host_venue") or {}).get("url"))


def _set_if(entry, key, value):
    if value is not None:
        entry[key] = value


def _year(work):
    return work.get("publication_year") and str(work.get("publication_year"))


def _book_title(work):
    return (work.get("host_venue") or {}).get("display_name")


def _school(work):
    return ((work.get("authorships") or [{}])[0].get("institutions") or [{}])[0].get(
        "display_name"
    )


def _author(work):
    return " and ".join(
        [
            dn
            for dn in [
                (a.get("author") or {}).get("display_name")
                for a in (work.get("authorships") or [])
            ]
            if dn
        ]
    )


def _journal_name(work):
    pl = work.get("primary_location") or {}
    src = pl.get("source") or {}
    return src.get("display_name", "Unknown")


def _publisher(work):
    return (work.get("host_venue") or {}).get("publisher")


def _host_venue_display_name(work):
    return (work.get("host_venue") or {}).get("display_name")


def _volume(work):
    return (work.get("biblio") or {}).get("volume")


def _issue(work):
    return (work.get("biblio") or {}).get("issue")


def _pages(work):
    first_page = (work.get("biblio") or {}).get("first_page")
    last_page = (work.get("biblio") or {}).get("last_page")

    if first_page and last_page:
        return f"{first_page}--{last_page}"
    elif first_page:
        return first_page
    return None
