"""Setup and add things to the database."""

import json
import os
import sys
from pathlib import Path

import libsql

from .utils import get_config

import numpy as np
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from tqdm import tqdm
import datetime
import bibtexparser
from rich import print

from litdb.openalex import get_data, get_text
from litdb.bibtex import dump_bibtex


def get_db():
    """Get or create the database."""
    config = get_config()

    root = Path(config["root"])

    DB = str(root / "litdb.libsql")

    if os.path.exists(DB):
        db = libsql.connect(DB)
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db
    else:
        db = libsql.connect(DB)
        model = SentenceTransformer(config["embedding"]["model"])

        _, dim = model.encode(["test"]).shape

        db.execute(
            f"""create table if not exists
    sources(rowid integer primary key,
    source text unique,
    text text,
    extra text,
    embedding F32_BLOB({dim}),
    date_added text)"""
        )

        db.execute(
            """create virtual table if not exists
            fulltext using fts5(source, text)"""
        )

        db.execute(
            """create table if not exists
        tags(rowid integer primary key,
        tag text unique)"""
        )

        db.execute(
            """create table if not exists
        source_tag(rowid integer primary key,
        source_id integer,
        tag_id integer,
        foreign key(source_id) references sources(rowid) on delete cascade,
        foreign key(tag_id) references tags(rowid) on delete cascade)"""
        )

        db.execute(
            """create table if not exists
    queries(rowid integer primary key,
    filter text unique,
    description text,
    last_updated text)"""
        )

        db.execute(
            """create table if not exists
    directories(rowid integer primary key,
        path text unique,
        last_updated text)"""
        )

        db.execute(
            """create index if not exists embedding_idx
            ON sources (libsql_vector_idx(embedding))"""
        )

        db.execute(
            """create table if not exists
            prompt_history(rowid integer primary key,
            prompt text)"""
        )

        # For images
        model = SentenceTransformer("clip-ViT-B-32")
        _, dim = model.encode(["test"]).shape

        db.execute(
            f"""create table if not exists
            images(rowid integer primary key,
            source text unique,
            embedding F32_BLOB({dim}),
            date_added text)"""
        )

        db.execute(
            """create index if not exists image_idx
            ON images (libsql_vector_idx(embedding))"""
        )

        return db


def add_source(source, text, extra=None):
    """Add a row to the sources table.

    source : url or path to document
    text: string of the document contents
    extra: jsonable information, usually a dictionary.

    We generate a document level embedding by averaging the embeddings of the
    document chunks.
    """
    db = get_db()
    config = get_config()
    model = SentenceTransformer(config["embedding"]["model"])
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config["embedding"]["chunk_size"],
        chunk_overlap=config["embedding"]["chunk_overlap"],
    )

    chunks = splitter.split_text(text)
    embedding = model.encode(chunks).mean(axis=0).astype(np.float32).tobytes()

    c = db.execute(
        """insert or ignore into sources(source, text, extra, embedding, date_added) values (?, ?, ?, ?, ?)""",
        (
            source,
            text,
            json.dumps(extra),
            embedding,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )

    # I think we should only do this if the previous line succeeded
    if c.rowcount > 0:
        db.execute(
            """insert into fulltext(source, text) values (?, ?)""", (source, text)
        )

    db.commit()


def get_citation(openalex_data):
    """Generate a citation string from OpenAlex metadata with full author list.

    Args:
        openalex_data: dict containing OpenAlex work metadata

    Returns:
        str: formatted citation with all authors
    """
    if not openalex_data:
        return None

    try:
        parts = []

        # Title
        title = openalex_data.get("title") or openalex_data.get("display_name")
        if title:
            parts.append(title)

        # All authors (not truncated!)
        if openalex_data.get("authorships"):
            authors = [
                a["author"]["display_name"]
                for a in openalex_data["authorships"]
                if a.get("author", {}).get("display_name")
            ]
            if authors:
                parts.append(", ".join(authors))

        # Journal/venue
        host_venue = openalex_data.get("host_venue") or {}
        venue = host_venue.get("display_name")
        if venue:
            parts.append(venue)

        # Volume and issue
        biblio = openalex_data.get("biblio") or {}
        volume = biblio.get("volume")
        issue = biblio.get("issue")

        if volume and issue:
            parts.append(f"{volume}({issue})")
        elif volume:
            parts.append(str(volume))

        # Pages
        first_page = biblio.get("first_page")
        last_page = biblio.get("last_page")
        if first_page and last_page:
            parts.append(f"{first_page}-{last_page}")
        elif first_page:
            parts.append(str(first_page))

        # Year
        year = openalex_data.get("publication_year")
        if year:
            parts.append(f"({year})")

        # DOI or URL
        doi = openalex_data.get("doi")
        if doi:
            parts.append(doi)
        elif openalex_data.get("id"):
            parts.append(openalex_data["id"])

        return " ".join(parts) if parts else None

    except Exception as e:
        print(f"Error generating citation: {e}")
        return None


def add_work(
    workid,
    references=False,
    citing=False,
    related=False,
    yes=False,
    max_citing=None,
    max_references=None,
    max_related=None,
):
    """Add a single work to litdb.

    workid is the doi (full url), or it could be an OpenAlex workid. DOI is
    preferrable.

    if references is truthy, also add them.
    if citing is truthy, also add them.
    if related is truthy, also add them.
    if yes is truthy, bypass interactive prompts and proceed automatically.
    max_citing limits the number of citing works to download (None = use prompt logic, -1 = no limit).
    max_references limits the number of references to download (None = all, -1 = no limit).
    max_related limits the number of related works to download (None = all, -1 = no limit).

    """
    config = get_config()
    params = {"mailto": config["openalex"]["email"], "per_page": 200}
    if config["openalex"].get("api_key"):
        params.update(api_key=config["openalex"].get("api_key"))

    data = get_data("https://api.openalex.org/works/" + workid, params)

    # I check to make sure we got something
    source = data.get("id", None)
    if source is None:
        # I guess this could happen for a bad DOI.
        print(f"No id found for {workid}.\n{data}")
        return

    data["citation"] = get_citation(data)
    data["bibtex"] = dump_bibtex(data)

    add_source(workid, get_text(data), data)

    if references:
        # Apply limit: None or -1 means all, otherwise limit to max_references
        ref_works = data["referenced_works"]
        if max_references is not None and max_references != -1:
            ref_works = ref_works[:max_references]

        for wid in tqdm(ref_works):
            rdata = get_data("https://api.openalex.org/works/" + wid, params)
            source = rdata.get("doi") or rdata.get("id")
            if source is None:
                print(f"Something failed for {wid}. continuing")
                continue
            text = get_text(rdata)
            rdata["citation"] = get_citation(rdata)
            rdata["bibtex"] = dump_bibtex(rdata)
            add_source(source, text, rdata)

    if related:
        # Apply limit: None or -1 means all, otherwise limit to max_related
        rel_works = data["related_works"]
        if max_related is not None and max_related != -1:
            rel_works = rel_works[:max_related]

        for wid in tqdm(rel_works):
            rdata = get_data("https://api.openalex.org/works/" + wid, params)
            source = rdata.get("doi") or rdata.get("id")
            if source is None:
                print(f"Something failed for {wid}. continuing")
                continue
            text = get_text(rdata)
            rdata["citation"] = get_citation(rdata)
            rdata["bibtex"] = dump_bibtex(rdata)
            add_source(source, text, rdata)

    if citing:
        # Construct the citing works URL manually since OpenAlex API no longer includes cited_by_api_url
        work_id = data["id"].split("/")[-1]  # Extract work ID from the full URL
        CURL = f"https://api.openalex.org/works?filter=cites:{work_id}"
        next_cursor = "*"
        params.update(cursor=next_cursor)
        citing_downloaded = 0
        while next_cursor:
            cdata = get_data(CURL, params)
            next_cursor = cdata["meta"]["next_cursor"]
            params.update(cursor=next_cursor)
            if next_cursor is None:
                break

            count = cdata["meta"]["count"]

            # Handle max_citing limit
            if max_citing is not None:
                # -1 means no limit, download all
                if max_citing == -1:
                    pass  # Download all
                # Positive number: limit to that many
                elif max_citing > 0:
                    if citing_downloaded >= max_citing:
                        print(f"Reached limit of {max_citing} citing works.")
                        break
                    # Don't prompt if we're within the limit
                    pass
            # No max_citing specified, use existing trigger logic
            else:
                # TODO: should the max citations to trigger this be configurable in litdb.toml
                trigger = config["openalex"].get("citation_count_trigger", 100)
                if count > trigger:
                    # Option 1: --yes flag bypasses prompt
                    if yes:
                        # Download all
                        pass
                    # Option 2: Check if non-interactive mode (piped, scripted, etc.)
                    elif not sys.stdin.isatty():
                        # Non-interactive: default to NO (safer)
                        print(
                            f"Found {count} citations. Non-interactive mode, skipping."
                        )
                        break
                    # Option 3: Normal interactive prompt
                    else:
                        r = input(
                            f"Found {count} citations. Do you want to download them all? (n/y): "
                        )
                        if r.lower().startswith("n"):
                            break
                        else:
                            pass

            for work in tqdm(cdata["results"]):
                # Check if we've reached the limit
                if max_citing is not None and max_citing > 0:
                    if citing_downloaded >= max_citing:
                        break

                source = work.get("doi") or work["id"]
                text = get_text(work)
                work["citation"] = get_citation(work)
                work["bibtex"] = dump_bibtex(work)
                add_source(source, text, work)
                citing_downloaded += 1


def add_author(oaid):
    """Add all works from an author.
    "id": "https://openalex.org/A5003442464",
    "orcid": "https://orcid.org/0000-0003-2625-9232",
    """
    config = get_config()
    aurl = "https://api.openalex.org/authors/" + oaid

    params = {
        "mailto": config["openalex"]["email"],
        "per_page": 200,
    }

    if config["openalex"].get("api_key"):
        params.update(api_key=config["openalex"].get("api_key"))

    data = get_data(aurl, params)

    wurl = data["works_api_url"]
    next_cursor = "*"
    params.update(cursor=next_cursor)
    while next_cursor:
        wdata = get_data(wurl, params)
        next_cursor = wdata["meta"]["next_cursor"]
        params.update(cursor=next_cursor)
        for work in tqdm(wdata["results"]):
            add_work(work.get("doi") or work["id"])


def update_filter(f, last_updated=None, silent=False):
    """Update one filter (f). f should be a string that goes in the filter=
    param for openalex.

    last_updated should be a string %Y-%m-%d

    If last_updated is None, we only go back one year.
    That might still lead to a lot of hits.

    """
    config = get_config()
    model = SentenceTransformer(config["embedding"]["model"])
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config["embedding"]["chunk_size"],
        chunk_overlap=config["embedding"]["chunk_overlap"],
    )

    db = get_db()

    _filter = f  # make a copy because we modify it later.

    wurl = "https://api.openalex.org/works"

    # If last_updated is None, we limit to the past year
    if last_updated is None:
        now = datetime.date.today()
        last_updated = (now - datetime.timedelta(days=365)).strftime("%Y-%m-%d")

    _filter += f",from_created_date:{last_updated}"

    params = {
        "mailto": config["openalex"]["email"],
        "api_key": config["openalex"]["api_key"],
        "per_page": 200,
        "filter": _filter,
    }

    next_cursor = "*"
    params.update(cursor=next_cursor)

    results = []
    while next_cursor:
        data = get_data(wurl, params)
        next_cursor = data["meta"]["next_cursor"]
        params.update(cursor=next_cursor)

        for work in tqdm(data["results"], disable=silent):
            source = work.get("doi") or work.get("id")
            citation = get_citation(work)
            work["citation"] = citation

            bibtex = dump_bibtex(work)
            work["bibtex"] = bibtex

            text = get_text(work)

            chunks = splitter.split_text(text)
            embedding = model.encode(chunks).mean(axis=0).astype(np.float32).tobytes()

            results += [[source, text, work]]

            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c = db.execute(
                """insert or ignore into
            sources(source, text, extra, embedding, date_added)
            values(?, ?, ?, ?, ?)""",
                (source, text, json.dumps(work), embedding, now),
            )

            if c.rowcount > 0:
                db.execute(
                    """insert into fulltext(source, text) values (?, ?)""",
                    (source, text),
                )

    db.execute(
        """update queries set last_updated = ? where filter = ?""",
        (datetime.date.today().strftime("%Y-%m-%d"), f),
    )

    db.commit()
    return results


def add_bibtex(bibfile):
    """Add entries with a DOI from bibfile."""

    with open(bibfile, "r", encoding="utf-8", errors="replace") as bibfile:
        bib_database = bibtexparser.load(bibfile)

        for entry in tqdm(bib_database.entries):
            if "doi" in entry:
                doi = entry["doi"]
                if doi.startswith("http"):
                    add_work(doi)
                elif doi.startswith("10"):
                    add_work(f"https://doi.org/{doi}")
                else:
                    print(f'I do not know what to do with "{doi}"')
