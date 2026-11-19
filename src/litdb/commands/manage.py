"""Core database management commands.

Commands:
- init: Initialize litdb project
- add: Add sources to database
- remove: Remove sources
- index: Index file directories
- reindex: Reindex saved directories
- update_embeddings: Update embeddings for sources
"""

import datetime
import os
import pathlib
import re

import bs4
import click
import nbformat
import requests
from docx import Document
from nbconvert import MarkdownExporter
from pptx import Presentation
from rich import print as richprint
from tqdm import tqdm

from ..audio import get_audio_text, is_audio_url
from ..db import (
    add_author,
    add_bibtex,
    add_source,
    add_work,
    embed_text,
    get_db,
    get_model,
    remove_source,
    tag_source,
)
from ..images import add_image, image_extensions
from ..pdf import add_pdf
from ..utils import get_config, init_litdb
from ..youtube import get_youtube_doc


@click.command()
def init():
    """Initialize a litdb directory in the current working directory."""
    if os.path.exists("litdb.toml"):
        raise click.ClickException(
            "litdb.toml already exists here; remove it first to re-initialize."
        )
    init_litdb()
    db = get_db()

    # Import about command to show statistics after init
    from . import export

    with click.Context(export.about) as ctx:
        ctx.invoke(export.about)

    return db


@click.command()
@click.argument("sources", nargs=-1)
@click.option("--references", is_flag=True, help="Add references too.")
@click.option("--related", is_flag=True, help="Add related too.")
@click.option("--citing", is_flag=True, help="Add citing too.")
@click.option("--all", is_flag=True, help="Add references, related and citing.")
@click.option(
    "-y", "--yes", is_flag=True, help="Auto-confirm prompts (bypass interactive mode)."
)
@click.option(
    "--max-citing",
    type=int,
    default=None,
    help="Max citing works to download (None=prompt, -1=no limit).",
)
@click.option(
    "--max-references",
    type=int,
    default=None,
    help="Max references to download (None=all, -1=no limit).",
)
@click.option(
    "--max-related",
    type=int,
    default=None,
    help="Max related works to download (None=all, -1=no limit).",
)
@click.option("-t", "--tag", "tags", multiple=True)
@click.option(
    "-v", "--verbose", is_flag=True, help="Show details of works being added."
)
def add(
    sources,
    references=False,
    citing=False,
    related=False,
    all=False,
    yes=False,
    max_citing=None,
    max_references=None,
    max_related=None,
    verbose=False,
    tags=None,
):
    """Add WIDS to the db.

    REFERENCES, RELATED, CITING are flags to also add those for DOI sources. ALL
    is shorthand for all of those.

    SOURCES can be one or more of a doi or orcid, a pdf path, a url, bibtex
    file, or other kind of file assumed to be text.

    TAGS is a list of tags to add to the source.

    These are one time additions.

    """

    if all:
        references, citing, related = True, True, True

    db = get_db() if tags else None

    for source in tqdm(sources):
        added = _add_one(
            source,
            references,
            citing,
            related,
            yes,
            max_citing,
            max_references,
            max_related,
            verbose,
        )

        for tag in tags or ():
            if added and tag_source(db, added, tag):
                print(f"Tagged {added} with {tag}")
            else:
                print(f"Could not tag {source} with {tag}: it was not added.")


OPENALEX_WORK = re.compile(
    r"^(https?://(api\.)?openalex\.org/(works/)?)?W\d+$", re.IGNORECASE
)
OPENALEX_AUTHOR = re.compile(
    r"^(https?://(api\.)?openalex\.org/(authors/)?)?A\d+$", re.IGNORECASE
)
ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$", re.IGNORECASE)


DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".pptx", ".html", ".htm", ".ipynb"}


def _is_doi(source):
    s = source.strip().lower()
    return s.startswith(("10.", "doi:")) or "doi.org/10." in s


def _add_one(
    source,
    references,
    citing,
    related,
    yes,
    max_citing,
    max_references,
    max_related,
    verbose,
):
    """Add one SOURCE to the db.

    Returns the key the source is stored under, or None if nothing was added.
    Authors and bibtex files add many works, so they return None too.
    """
    is_url = source.startswith(("http://", "https://"))
    ext = os.path.splitext(source.split("?")[0])[1].lower()

    # a work, by DOI or OpenAlex id
    if _is_doi(source) or OPENALEX_WORK.match(source):
        if source.startswith("10."):
            source = f"https://doi.org/{source}"
        return add_work(
            source,
            references,
            citing,
            related,
            yes,
            max_citing,
            max_references,
            max_related,
            verbose,
        )

    # works from an author
    if "orcid.org/" in source.lower() or ORCID.match(source):
        if not is_url:
            source = f"https://orcid.org/{source}"
        add_author(source)
        return None

    if OPENALEX_AUTHOR.match(source):
        add_author(source)
        return None

    # YouTube
    if is_url and "youtube" in source:
        text, citation = get_youtube_doc(source)
        add_source(source, text, {"citation": citation})
        return source

    # audio sources
    if (is_url and is_audio_url(source)) or ext == ".mp3":
        add_source(source, get_audio_text(source))
        return source

    # any other url
    if is_url:
        resp = requests.get(source, timeout=30)
        resp.raise_for_status()
        if "pdf" in resp.headers.get("content-type", "") or ext == ".pdf":
            import pymupdf
            import pymupdf4llm

            with pymupdf.open(stream=resp.content, filetype="pdf") as doc:
                add_source(source, pymupdf4llm.to_markdown(doc))
            return source
        soup = bs4.BeautifulSoup(resp.text, features="html.parser")
        add_source(source, soup.get_text())
        return source

    # From here on, source is a local file.
    if ext == ".bib":
        add_bibtex(source)
        return None

    if ext not in DOCUMENT_EXTENSIONS and ext in image_extensions:
        # Checked after the document types: PIL registers .pdf as an image.
        add_image(source)
        return None

    source = os.path.abspath(source)

    if ext == ".pdf":
        add_pdf(source)

    elif ext == ".docx":
        doc = Document(source)
        add_source(source, "\n".join([para.text for para in doc.paragraphs]))

    elif ext == ".pptx":
        prs = Presentation(source)
        text = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text.append(shape.text)
        add_source(source, "\n".join(text))

    elif ext in (".html", ".htm"):
        with open(source) as f:
            soup = bs4.BeautifulSoup(f.read(), features="html.parser")
        add_source(source, soup.get_text())

    elif ext == ".ipynb":
        with open(source) as f:
            notebook = nbformat.read(f, as_version=4)
        (body, _resources) = MarkdownExporter().from_notebook_node(notebook)
        add_source(source, body)

    # assume it is text
    else:
        with open(source) as f:
            add_source(source, f.read())

    return source


@click.command()
@click.argument("sources", nargs=-1)
def remove(sources):
    """Remove sources from litdb."""
    db = get_db()
    for source in sources:
        if remove_source(db, source):
            print(f"Removed {source}")
        else:
            print(f"{source} is not in the database.")


@click.command()
@click.argument("sources", nargs=-1)
def index(sources):
    """Index the directories in SOURCES.

    SOURCES is a list of directories. Files already in litdb are skipped. A
    bibtex file is read again only if it changed since the directory was last
    indexed, since its entries are stored under their DOIs, not its path.
    """
    db = get_db()
    for directory in sources:
        _index_directory(db, directory)


def _files_to_index(db, directory):
    """Return the files under DIRECTORY that are not in DB yet.

    Bibtex files are not sources themselves (their entries are), so they are
    returned if they changed since DIRECTORY was last indexed.
    """
    directory = pathlib.Path(directory).resolve()
    row = db.execute(
        "select last_updated from directories where path = ?", (str(directory),)
    ).fetchone()
    last_indexed = (
        datetime.datetime.strptime(row[0], "%Y-%m-%d").timestamp()
        if row and row[0]
        else None
    )

    files = []
    for fname in sorted(directory.rglob("*")):
        if not fname.is_file() or fname.suffix.lower() not in INDEX_EXTENSIONS:
            continue

        if fname.suffix.lower() == ".bib":
            if last_indexed is not None and fname.stat().st_mtime < last_indexed:
                continue
        elif db.execute(
            "select source from sources where source = ?", (str(fname),)
        ).fetchone():
            continue
        files.append(fname)
    return files


def _record_indexed(db, directory):
    """Record in DB that DIRECTORY was indexed today."""
    db.execute(
        """insert into directories(path, last_updated) values (?, ?)
        on conflict(path) do update set last_updated = excluded.last_updated""",
        (
            str(pathlib.Path(directory).resolve()),
            datetime.date.today().strftime("%Y-%m-%d"),
        ),
    )
    db.commit()


def _index_directory(db, directory):
    """Add the new files under DIRECTORY to DB and record when it was indexed."""
    for fname in _files_to_index(db, directory):
        try:
            _add_one(str(fname), False, False, False, False, None, None, None, False)
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the rest
            richprint(f"[yellow]Skipping {fname}: {e}[/yellow]")
            continue
        print(f"Added {fname}")

    _record_indexed(db, directory)


INDEX_EXTENSIONS = {".pdf", ".docx", ".pptx", ".org", ".md", ".html", ".bib", ".ipynb"}


@click.command()
def reindex():
    """Reindex saved directories."""
    db = get_db()
    for (directory,) in db.execute("""select path from directories""").fetchall():
        print(f"Reindexing {directory}")
        _index_directory(db, directory)


@click.command(name="update-embeddings")
def update_embeddings():
    """Update all the embeddings in your db.

    The only reason you would do this is if you change the embedding model, or
    the way the chunks are sized in your config.

    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    config = get_config()
    db = get_db()

    model = get_model(config["embedding"]["model"])
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config["embedding"]["chunk_size"],
        chunk_overlap=config["embedding"]["chunk_overlap"],
    )

    _, dim = model.encode(["test"]).shape

    # The point of this is to avoid deleting the database.
    db.execute("drop index if exists embedding_idx")
    db.execute("alter table sources drop embedding")
    db.execute(f"alter table sources add column embedding F32_BLOB({dim})")
    db.commit()

    rows = db.execute("select rowid, text from sources").fetchall()
    for rowid, text in tqdm(rows):
        db.execute(
            "update sources set embedding = ? where rowid = ?",
            (embed_text(model, splitter, text), rowid),
        )

    # I don't know why this has to be here. I had it above, and no updates were
    # happening.
    db.execute(
        """create index if not exists embedding_idx ON sources (libsql_vector_idx(embedding))"""
    )

    # Update stored embedding config so the warning doesn't persist
    import json

    emb_config = json.dumps(
        {
            "model": config["embedding"]["model"],
            "chunk_size": config["embedding"]["chunk_size"],
            "chunk_overlap": config["embedding"]["chunk_overlap"],
        },
        sort_keys=True,
    )
    db.execute(
        """insert or replace into metadata(key, value)
        values ('embedding_config', ?)""",
        (emb_config,),
    )
    db.commit()
