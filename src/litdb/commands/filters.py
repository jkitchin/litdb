"""Filter management commands for litdb.

Commands:
- add_filter: Add OpenAlex filters
- rm_filter: Remove filters
- update_filters: Update database using filters
- list_filters: List all defined filters
"""

import os

import click
from jinja2 import Template
from rich import print as richprint
from tqdm import tqdm

from ..db import get_db, update_filter


# Lazy database initialization
_db = None


def get_filters_db():
    """Get or create database connection for filter commands."""
    global _db
    if _db is None:
        _db = get_db()
    return _db


@click.command()
@click.argument("_filter")
@click.option("-d", "--description")
def add_filter(_filter, description=None):
    """Add an OpenAlex FILTER.

    This does not run the filter right away. You need
    to manually update the filters later.
    """
    get_filters_db().execute(
        "insert into queries(filter, description) values (?, ?)", (_filter, description)
    )
    get_filters_db().commit()


@click.command()
@click.argument("_filter")
def rm_filter(_filter):
    """Remove an OpenAlex FILTER."""
    get_filters_db().execute("delete from queries where filter = ?", (_filter,))
    get_filters_db().commit()


update_filter_fmt = """** {{ extra['display_name'] | replace("\n", "") | replace("\r", "") }}
:PROPERTIES:
:SOURCE: {{ source }}
:REFERENCE_COUNT: {{ extra.get('referenced_works_count', 0) }}
:CITED_BY_COUNT: {{ extra.get('cited_by_count', 0) }}
:END:

litdb:{{ source }}

{{ text }}

"""


@click.command()
@click.option("-f", "--fmt", default=update_filter_fmt)
@click.option("-s", "--silent", is_flag=True, default=False)
def update_filters(fmt, silent):
    """Update litdb using a filter with works from a created date."""

    os.environ["TRANSFORMERS_OFFLINE"] = "1"  # Prevent checking HF on each filter
    filters = get_filters_db().execute(
        """select filter, description, last_updated from queries"""
    )
    for f, description, last_updated in tqdm(filters.fetchall(), disable=silent):
        try:
            results = update_filter(f, last_updated, silent)
            if results:
                richprint(f"* {description or f}")
            for result in results:
                source, text, extra = result
                richprint(Template(fmt).render(**locals()))
        except:  # noqa: E722
            continue


list_filter_fmt = (
    '{{ "{:3d}".format(rowid) }}.'
    ' {{ "{:30s}".format(description'
    ' or "None") }} {{ f }}'
    " ({{ last_updated }})"
)


@click.command()
@click.option("-f", "--fmt", default=list_filter_fmt)
def list_filters(fmt):
    """List the filters.

    FMT is a jinja template with access to the variables rowid, f, description
    and last_updated. f is the filter string.

    You can dump the filters to stdout like this.

    > litdb list-filters -f 'litdb add-filter {{ f }}'

    You could use that to send a list of your filters to someone, or to recreate
    a db somewhere else.
    """
    filters = get_filters_db().execute(
        """select rowid, filter, description, last_updated
    from queries"""
    )
    for rowid, f, description, last_updated in filters.fetchall():
        richprint(Template(fmt).render(**locals()))
