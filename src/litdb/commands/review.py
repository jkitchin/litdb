"""Review and summary commands for litdb.

Commands:
- review: Review new entries added since a date
- summary: Generate newsletter-style summary of articles
"""

import json

import click
import dateparser
from jinja2 import Template

from ..db import get_db
from ..summary import generate_summary


# Lazy database initialization
db = None


def get_review_db():
    """Get or create database connection for review commands."""
    global db
    if db is None:
        db = get_db()
    return db


# Initialize db for module
db = get_review_db()


@click.command()
@click.option("-s", "--since", default="1 week ago")
@click.option("-f", "--fmt", default=None)
def review(since, fmt):
    """Review new entries added SINCE.

    SINCE should be something dateparser can handle.
    FMT is a jinja template for the output. Defaults to an org-mode template.
    """

    since = dateparser.parse(since).strftime("%Y-%m-%d")
    c = db.execute(
        """select source, text, extra from sources
    where date(date_added) > ?""",
        (since,),
    ).fetchall()

    template = Template(
        fmt
        or """* {{ extra['display_name'] | replace("\n", " ") }}
:PROPERTIES:
:SOURCE: {{ source }}
:OPENALEX: {{ extra.get('id') }}
:YEAR: {{ extra.get('publication_year') }}
:REFERENCE_COUNT: {{ extra.get('referenced_works_count', 0) }}
:CITED_BY_COUNT: {{ extra.get('cited_by_count', 0) }}
:END:

{{ text }} litdb:{{ source }}
        """
    )

    for source, text, extra in c:
        extra = json.loads(extra) or {}
        print(template.render(**locals()))


@click.command()
@click.option("-s", "--since", default="1 week")
@click.option("-o", "--output", default=None, help="Output file path (optional)")
@click.option("--model", default=None, help="LLM model to use (optional)")
def summary(since, output, model):
    """Generate a newsletter-style summary of articles added SINCE.

    SINCE: Time period to look back (e.g., "1 week", "2 weeks", "1 month").
    Uses dateparser, so flexible date formats are supported.

    OUTPUT: Optional file path to save the summary. If not provided, outputs to stdout.

    MODEL: LLM model to use for analysis (uses config default if not specified).

    This command:
    1. Fetches articles added since the specified date
    2. Extracts topics from each article using an LLM
    3. Aggregates topics into 5-10 main themes with subtopics
    4. Classifies each article into topics/subtopics
    5. Generates narrative summaries for each subtopic
    6. Outputs an org-mode formatted newsletter

    Example:
        litdb summary -s "2 weeks" -o newsletter.org
    """
    generate_summary(since=since, output_file=output, model=model)
