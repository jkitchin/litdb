"""Setup and add things to the database."""

import functools
import json
import logging
import os
import sys
from pathlib import Path

import libsql

from .utils import get_config

# Suppress sentence_transformers INFO logs and progress bars
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["TQDM_DISABLE"] = "1"

import datetime

import bibtexparser
import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rich import print
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from litdb.bibtex import dump_bibtex
from litdb.openalex import get_data, get_text


def _check_embedding_config(db, config):
    """Check if embedding config has changed and warn the user.

    Stores the embedding model, chunk_size, and chunk_overlap in the metadata
    table. If any of these differ from what's in the config file, prints a
    warning telling the user to run 'litdb update-embeddings'.
    """
    emb_config = {
        "model": config["embedding"]["model"],
        "chunk_size": config["embedding"]["chunk_size"],
        "chunk_overlap": config["embedding"]["chunk_overlap"],
    }
    current = json.dumps(emb_config, sort_keys=True)

    row = db.execute(
        "select value from metadata where key = 'embedding_config'"
    ).fetchone()

    if row is None:
        # First time: store the config
        db.execute(
            "insert into metadata(key, value) values ('embedding_config', ?)",
            (current,),
        )
        db.commit()
    elif row[0] != current:
        stored = json.loads(row[0])
        changes = []
        for k, v in emb_config.items():
            if v != stored.get(k):
                changes.append(f"  {k}: {stored.get(k)} -> {v}")
        print(
            "[bold yellow]Warning:[/bold yellow] Embedding config has changed:\n"
            + "\n".join(changes)
            + "\nRun [bold]litdb update-embeddings[/bold] to rebuild embeddings."
        )


@functools.cache
def get_model(name):
    """Return the SentenceTransformer model NAME, loading it once per process.

    Loading a model takes seconds, and add_source runs once per work (hundreds
    of times for add_work with references or citing works).
    """
    return SentenceTransformer(name)


def _table_exists(db, name):
    """Return True if table NAME exists in DB."""
    row = db.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?", (name,)
    ).fetchone()
    return row is not None


def get_db():
    """Get or create the database."""
    config = get_config()

    root = Path(config["root"])

    DB = str(root / "litdb.libsql")

    db = libsql.connect(DB)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode=WAL")

    # Check for the schema rather than for the file: libsql.connect creates the
    # file, so a first run that failed partway (e.g. a model download error)
    # would otherwise leave an empty database that is never initialized.
    # images is checked too: older versions created it last, after loading the
    # CLIP model, so an interrupted first run could have sources but no images.
    if not (_table_exists(db, "sources") and _table_exists(db, "images")):
        _create_schema(db, config)

    # Databases created before the metadata table was added do not have it.
    db.execute("create table if not exists metadata(key text primary key, value text)")
    _check_embedding_config(db, config)

    return db


def _create_schema(db, config):
    """Create the litdb tables and indexes in DB."""
    # Load both models before creating anything, so a failure leaves no
    # partial schema behind.
    _, dim = get_model(config["embedding"]["model"]).encode(["test"]).shape
    _, image_dim = get_model("clip-ViT-B-32").encode(["test"]).shape

    statements = [
        f"""create table if not exists
        sources(rowid integer primary key,
        source text unique,
        text text,
        extra text,
        embedding F32_BLOB({dim}),
        date_added text)""",
        """create virtual table if not exists fulltext using fts5(source, text)""",
        """create table if not exists
        tags(rowid integer primary key,
        tag text unique)""",
        """create table if not exists
        source_tag(rowid integer primary key,
        source_id integer,
        tag_id integer,
        foreign key(source_id) references sources(rowid) on delete cascade,
        foreign key(tag_id) references tags(rowid) on delete cascade)""",
        """create table if not exists
        queries(rowid integer primary key,
        filter text unique,
        description text,
        last_updated text)""",
        """create table if not exists
        directories(rowid integer primary key,
        path text unique,
        last_updated text)""",
        """create index if not exists embedding_idx
        ON sources (libsql_vector_idx(embedding))""",
        """create table if not exists
        prompt_history(rowid integer primary key,
        prompt text)""",
        # For images
        f"""create table if not exists
        images(rowid integer primary key,
        source text unique,
        embedding F32_BLOB({image_dim}),
        date_added text)""",
        """create index if not exists image_idx
        ON images (libsql_vector_idx(embedding))""",
    ]
    for statement in statements:
        db.execute(statement)
    db.commit()


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
    model = get_model(config["embedding"]["model"])
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
        pl = openalex_data.get("primary_location") or {}
        src = pl.get("source") or {}
        venue = src.get("display_name")
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

    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        print(f"Error generating citation: {e}")
        return None


def _apply_limit(items, limit):
    """Return the first LIMIT items; None or a negative LIMIT means all of them."""
    if limit is None or limit < 0:
        return items
    return items[:limit]


def _confirm_citing(count, trigger, yes):
    """Ask whether to download COUNT citing works when there are more than TRIGGER.

    --yes downloads them all. Without a terminal to ask on, the answer is no.
    Only an explicit "y" answer downloads them; the prompt defaults to no.
    """
    if count <= trigger or yes:
        return True
    if not sys.stdin.isatty():
        print(f"Found {count} citations. Non-interactive mode, skipping.")
        return False
    r = input(f"Found {count} citations. Do you want to download them all? (n/y): ")
    return r.strip().lower().startswith("y")


def _add_citing_works(data, params, config, yes, max_citing, verbose):
    """Add the works that cite DATA (an OpenAlex work).

    max_citing None asks first when there are more citing works than the
    citation_count_trigger config value (default 100); -1 (or any negative)
    downloads all of them; otherwise at most max_citing are downloaded.
    """
    # OpenAlex no longer includes cited_by_api_url, so build the URL.
    work_id = data["id"].split("/")[-1]
    url = f"https://api.openalex.org/works?filter=cites:{work_id}"
    params = {**params, "cursor": "*"}
    limit = None if max_citing is None or max_citing < 0 else max_citing

    downloaded = 0
    asked = max_citing is not None  # an explicit limit replaces the prompt
    while limit is None or downloaded < limit:
        cdata = get_data(url, params)
        results = cdata.get("results", [])
        if not results:
            break

        if not asked:
            trigger = config["openalex"].get("citation_count_trigger", 100)
            if not _confirm_citing(cdata["meta"]["count"], trigger, yes):
                break
            asked = True

        if limit is not None:
            results = results[: limit - downloaded]

        for work in tqdm(results):
            source = work.get("doi") or work["id"]
            if verbose:
                title = work.get("title") or "No title"
                year = work.get("publication_year") or "Unknown"
                print(
                    f"  [cit] {title[:70]}{'...' if len(title) > 70 else ''} ({year})"
                )
            text = get_text(work)
            work["citation"] = get_citation(work)
            work["bibtex"] = dump_bibtex(work)
            add_source(source, text, work)
            downloaded += 1

        next_cursor = cdata["meta"].get("next_cursor")
        if not next_cursor:
            break
        params["cursor"] = next_cursor

    if limit is not None and downloaded >= limit:
        print(f"Reached limit of {limit} citing works.")


def add_work(
    workid,
    references=False,
    citing=False,
    related=False,
    yes=False,
    max_citing=None,
    max_references=None,
    max_related=None,
    verbose=False,
):
    """Add a single work to litdb.

    workid is the doi (full url), or it could be an OpenAlex workid. DOI is
    preferrable.

    if references is truthy, also add them.
    if citing is truthy, also add them.
    if related is truthy, also add them.
    if yes is truthy, bypass interactive prompts and proceed automatically.
    max_citing limits the number of citing works to download (None = ask when
    there are many, negative = no limit, 0 = none).
    max_references limits the number of references (None or negative = all).
    max_related limits the number of related works (None or negative = all).
    verbose prints details about each work being added.

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

    if verbose:
        # OpenAlex returns null for some of these, so .get defaults are not enough
        title = data.get("title") or "No title"
        doi = data.get("doi") or "No DOI"
        year = data.get("publication_year") or "Unknown year"
        print(f"Adding: {title[:80]}{'...' if len(title) > 80 else ''}")
        print(f"  DOI: {doi} | Year: {year}")

    add_source(workid, get_text(data), data)

    if references:
        ref_works = _apply_limit(data.get("referenced_works", []), max_references)

        for wid in tqdm(ref_works):
            # Extract work ID from full URL (e.g., https://openalex.org/W3103133276 -> W3103133276)
            work_id = wid.split("/")[-1] if "/" in wid else wid
            api_url = "https://api.openalex.org/works/" + work_id
            rdata = get_data(api_url, params)
            source = rdata.get("doi") or rdata.get("id")
            if source is None:
                print(f"Referenced work not found (may be removed/merged): {work_id}")
                print(f"  API URL: {api_url}")
                continue
            if verbose:
                title = rdata.get("title", "No title") or "No title"
                year = rdata.get("publication_year", "Unknown")
                print(
                    f"  [ref] {title[:70]}{'...' if len(title) > 70 else ''} ({year})"
                )
            text = get_text(rdata)
            rdata["citation"] = get_citation(rdata)
            rdata["bibtex"] = dump_bibtex(rdata)
            add_source(source, text, rdata)

    if related:
        rel_works = _apply_limit(data.get("related_works", []), max_related)

        for wid in tqdm(rel_works):
            # Extract work ID from full URL (e.g., https://openalex.org/W3103133276 -> W3103133276)
            work_id = wid.split("/")[-1] if "/" in wid else wid
            api_url = "https://api.openalex.org/works/" + work_id
            rdata = get_data(api_url, params)
            source = rdata.get("doi") or rdata.get("id")
            if source is None:
                print(f"Related work not found (may be removed/merged): {work_id}")
                print(f"  API URL: {api_url}")
                continue
            if verbose:
                title = rdata.get("title", "No title") or "No title"
                year = rdata.get("publication_year", "Unknown")
                print(
                    f"  [rel] {title[:70]}{'...' if len(title) > 70 else ''} ({year})"
                )
            text = get_text(rdata)
            rdata["citation"] = get_citation(rdata)
            rdata["bibtex"] = dump_bibtex(rdata)
            add_source(source, text, rdata)

    if citing:
        _add_citing_works(data, params, config, yes, max_citing, verbose)


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

    wurl = data.get("works_api_url")
    if wurl is None:
        # get_data returns an empty result for a bad id (e.g. a 404).
        print(f"No author found for {oaid}.")
        return

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
    model = get_model(config["embedding"]["model"])
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
        "per_page": 200,
        "filter": _filter,
    }
    # api_key is optional: litdb init leaves it out when you do not have one.
    if config["openalex"].get("api_key"):
        params["api_key"] = config["openalex"]["api_key"]

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


def _normalize_doi(doi):
    """Return DOI as a https://doi.org/ URL, or None if it is not a DOI.

    Accepts a bare DOI ("10.1/x"), a "doi:" prefix, or a doi.org URL, with
    surrounding whitespace, as found in the doi field of bibtex entries.
    """
    doi = doi.strip()
    if doi.lower().startswith("doi:"):
        doi = doi[4:].strip()
    if doi.startswith("http"):
        return doi
    if doi.startswith("10."):
        return f"https://doi.org/{doi}"
    return None


def add_bibtex(bibfile):
    """Add entries with a DOI from bibfile."""

    with open(bibfile, encoding="utf-8", errors="replace") as f:
        bib_database = bibtexparser.load(f)

        for entry in tqdm(bib_database.entries):
            if "doi" in entry:
                doi = _normalize_doi(entry["doi"])
                if doi is None:
                    print(f'I do not know what to do with "{entry["doi"]}"')
                else:
                    add_work(doi)
