"""OpenAlex-related commands for litdb.

Commands:
- openalex: Run OpenAlex queries
- author_search: Search for authors
- follow: Follow an ORCID
- watch: Watch a query
- citing: Watch citing articles
- related: Watch related articles
- unpaywall: Find PDFs using Unpaywall
"""

import datetime

import click
import requests
from rich import print as richprint

from ..utils import get_config
from ..db import get_db, add_author
from ..openalex import get_data


# Lazy database initialization
_db = None


def get_openalex_db():
    """Get or create database connection for OpenAlex commands."""
    global _db
    if _db is None:
        _db = get_db()
    return _db


@click.command()
@click.argument("query", nargs=-1)
@click.option("-f", "--filter", "_filter", is_flag=True, default=False)
@click.option("-e", "--endpoint", default="works")
@click.option("--sample", default=-1)
@click.option("--per-page", default=5)
def openalex(query, _filter, endpoint, sample, per_page):
    """Run an openalex query on FILTER.

    ENDPOINT should be one of works, authors, or another entity.
    SAMPLE: int, return this many random samples
    PER_PAGE: limits the number of results retrieved

    This does not add anything to your database. It is to help you find starting
    points.

    To search text:
    litdb openalex "circular polymer"

    To find a journal id with a specific filter
    litdb openalex -e sources -f "display_name.search:Digital Discovery"

    """
    config = get_config()
    url = f"https://api.openalex.org/{endpoint}"

    if isinstance(query, tuple):
        query = " ".join(query)
    if not _filter:
        query = f"default.search:{query}"

    params = {
        "mailto": config["openalex"]["email"],
        "filter": query,
        "per_page": per_page,
    }

    if api_key := config["openalex"].get("api_key"):
        params.update(api_key=api_key)

    if sample > 0:
        params.update(sample=sample, per_page=sample)

    resp = requests.get(url, params)
    if resp.status_code != 200:
        print(resp.url)
        print(resp.text)
        return

    data = resp.json()
    for result in data["results"]:
        s = f"{result['title']}, ({result['publication_year']}) {result['id']}\n"
        # Note sometimes there is an exception from bad markup in strings
        richprint(s)


@click.command()
@click.argument("name", nargs=-1)
def author_search(name):
    """Search OpenAlex for name.

    Uses the autocomplete endpoint to find an author's orcid.
    """
    auname = " ".join(name)

    url = "https://api.openalex.org/autocomplete/authors"

    data = get_data(url, params={"q": auname})

    for result in data["results"]:
        richprint(
            f"- {result['display_name']}\n  {result['hint']} "
            f"{result['external_id']}\n\n"
        )


@click.command()
@click.argument("orcids", nargs=-1)
@click.option("-r", "--remove", is_flag=True, help="remove")
def follow(orcids, remove=False):
    """Add a filter to follow orcid."""
    for orcid in orcids:
        if not orcid.startswith("http"):
            orcid = f"https://orcid.org/{orcid}"

        # Seems like we should get their articles first.
        add_author(orcid)

        f = f"author.orcid:{orcid}"

        if remove:
            c = get_openalex_db().execute(
                """delete from queries where  filter = ?""", (f,)
            )
            get_openalex_db().commit()
            richprint(f"{c.rowcount} rows removed")
            return

        url = f"https://api.openalex.org/authors/{orcid}"
        data = get_data(url)
        name = data["display_name"]

        today = datetime.date.today().strftime("%Y-%m-%d")
        get_openalex_db().execute(
            """insert or ignore into
        queries(filter, description, last_updated)
        values (?, ?, ?)""",
            (f, name, today),
        )

        richprint(f"Following {name}: {orcid}")
        get_openalex_db().commit()


@click.command()
@click.argument("query", nargs=-1)
@click.option("-r", "--remove", is_flag=True, help="remove")
def watch(query, remove=False):
    """Create a watch on query.

    QUERY: string, a filter for openalex.
    REMOVE: a flag to remove the query.
    """
    # First, we should make sure the filter is valid
    query = " ".join(query)

    if remove:
        c = get_openalex_db().execute(
            """delete from queries where filter = ?""", (query,)
        )
        get_openalex_db().commit()
        richprint(f"{c.rowcount} rows removed")
        return

    url = "https://api.openalex.org/works"

    data = get_data(url, params={"filter": query})
    if len(data["results"]) == 0:
        richprint(f"Sorry, {query} does not seem valid.")

    if remove:
        c = get_openalex_db().execute(
            """delete from queries where filter = ?""", (query,)
        )
        richprint(f"Deleted {c.rowcount} rows")
        get_openalex_db().commit()
    else:
        c = get_openalex_db().execute(
            """insert or ignore into queries(filter, description)
        values (?, ?)""",
            (query,),
        )
        richprint(f"Added {c.rowcount} rows")
        get_openalex_db().commit()
        richprint(f"Watching {query}")


@click.command()
@click.argument("doi")
@click.option("-r", "--remove", is_flag=True, help="remove")
def citing(doi, remove=False):
    """Create a watch for articles that cite doi.

    REMOVE is a flag to remove the doi.
    """
    url = "https://api.openalex.org/works"

    # We need an OpenAlex id
    f = f"doi:{doi}"

    data = get_data(url, params={"filter": f})
    if len(data["results"]) == 0:
        richprint(f"Sorry, {doi} does not seem valid.")

    wid = data["results"][0]["id"]

    if remove:
        c = get_openalex_db().execute(
            """delete from queries where filter = ?""", (f"cites:{wid}",)
        )
        get_openalex_db().commit()
        richprint(f"Deleted {c.rowcount} rows")
    else:
        c = get_openalex_db().execute(
            """insert or ignore into queries(filter, description)
        values (?, ?)""",
            (f"cites:{wid}", f"Citing papers for {doi}"),
        )

        get_openalex_db().commit()
        richprint(f"Added {c.rowcount} rows")


@click.command()
@click.argument("doi")
@click.option("-r", "--remove", is_flag=True, help="remove")
def related(doi, remove=False):
    """Create a watch for articles that are related to doi.

    REMOVE is a flag to remove the doi from queries.
    """
    url = "https://api.openalex.org/works"

    # We need an OpenAlex id
    f = f"doi:{doi}"

    data = get_data(url, params={"filter": f})
    if len(data["results"]) == 0:
        richprint(f"Sorry, {doi} does not seem valid.")

    wid = data["results"][0]["id"]

    if remove:
        c = get_openalex_db().execute(
            """delete from queries where filter = ?""", (f"related_to:{wid}",)
        )
        get_openalex_db().commit()
        richprint(f"Deleted {c.rowcount} rows")
    else:
        c = get_openalex_db().execute(
            """insert or ignore into queries(filter, description)
        values (?, ?)""",
            (f"related_to:{wid}", f"Related papers for {doi}"),
        )

        get_openalex_db().commit()
        richprint(f"Added {c.rowcount} rows")


@click.command()
@click.argument("doi")
def unpaywall(doi):
    """Use unpaywall to find PDFs for doi."""
    config = get_config()
    url = f"https://api.unpaywall.org/v2/{doi}"
    params = {"mailto": config["openalex"]["email"]}

    resp = requests.get(url, params)
    if resp.status_code == 200:
        data = resp.json()
        richprint(f"{data['title']}, {data.get('journal_name') or ''}")
        richprint(f"Is open access: {data.get('is_oa', False)}")

        for loc in data.get("oa_locations", []):
            richprint(loc.get("url_for_pdf") or loc.get("url_for_landing_page"))
    else:
        richprint(f"{doi} not found in unpaywall")
