"""Export and display commands for litdb.

Commands:
- bibtex: Generate bibtex entries
- citation: Generate citation strings
- show: Display source details
- visit (open): Open source in browser
- about: Database statistics
- sql: Run SQL queries
"""

import json
import os
import sys
import webbrowser

import click
from jinja2 import Template
from rich import print as richprint

from ..utils import get_config
from ..db import get_db
from ..bibtex import dump_bibtex


# Lazy database initialization
_db = None


def get_export_db():
    """Get or create database connection for export commands."""
    global _db
    if _db is None:
        _db = get_db()
    return _db


@click.command()
@click.argument("sources", nargs=-1)
def bibtex(sources):
    """Generate bibtex entries for sources."""
    if not sources:
        sources = sys.stdin.read().strip().split()

    for source in sources:
        work = (
            get_export_db()
            .execute("""select extra from sources where source = ?""", (source,))
            .fetchone()
        )
        if work:
            print(f"WORK: {work}")
            richprint(dump_bibtex(json.loads(work[0])))
        else:
            print(f"No entry found for {source}")


@click.command()
@click.argument("sources", nargs=-1)
def citation(sources):
    """Generate citation strings for sources."""
    if not sources:
        sources = sys.stdin.read().strip().split()

    for i, source in enumerate(sources):
        (_citation,) = (
            get_export_db()
            .execute(
                """select json_extract(extra, '$.citation')
        from sources where source = ?""",
                (source,),
            )
            .fetchone()
        )
        richprint(f"{i + 1:2d}. {_citation}")


@click.command()
def about():
    """Summary statistics of your db."""
    config = get_config()
    dbf = os.path.join(config["root"], "litdb.libsql")
    cf = os.path.join(config["root"], "litdb.toml")

    richprint(f"Your database is located at {dbf}")
    richprint(f"The configuration is at {cf}")
    kb = 1024
    mb = 1024 * kb
    gb = 1024 * mb
    richprint(f"Database size: {os.path.getsize(dbf) / gb:1.2f} GB")
    (nsources,) = (
        get_export_db().execute("select count(source) from sources").fetchone()
    )
    richprint(f"You have {nsources} sources")


@click.command()
@click.argument("sql")
def sql(sql):
    """Run the SQL command on the db."""
    for row in get_export_db().execute(sql).fetchall():
        richprint(row)


@click.command()
@click.argument("sources", nargs=-1)
@click.option("-f", "--fmt", default="{{ source }}\n{{ text }}")
def show(sources, fmt):
    """Show the source.

    FMT is a jinja template with access to source, text, extra for each arg.
    """
    for src in sources:
        result = (
            get_export_db()
            .execute(
                """select source, text, extra from
        sources where source = ?""",
                (src,),
            )
            .fetchone()
        )

        if result:
            source, text, extra = result
            extra = json.loads(extra)
            richprint(Template(fmt).render(**locals()))
        else:
            print(f"Nothing found for {src}")


@click.command(name="open")
@click.argument("source")
def visit(source):
    """Open source."""
    if source.startswith("http"):
        webbrowser.open(source, new=2)
    elif source.endswith(".pdf"):
        webbrowser.open(f"file://{source}")
    else:
        webbrowser.open(f"file://{source}")
