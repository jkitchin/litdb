"""CLI for litdb.

The main command is litdb. There are subcommands for the actions.
"""

import warnings

import click

from .db import get_db

# Import command modules
from .commands import (
    manage,
    search,
    export,
    tags,
    review,
    filters,
    openalex_commands,
    research_commands,
    data_processing,
    utilities,
)

import logging
from transformers.utils import logging as tulogging

# Disable all Transformers logging
tulogging.set_verbosity_error()

logging.getLogger("pydantic").setLevel(logging.CRITICAL)

warnings.filterwarnings("ignore")
warnings.filterwarnings("ignore", category=UserWarning)

# Lazy database initialization - only load if not in test/import-only mode
# During testing, fixtures will set up the database before commands run
db = None
try:
    db = get_db()
except SystemExit:
    # get_db() calls sys.exit() if no config found
    # This is expected during test imports
    pass


@click.group()
def cli():
    """Group command for litdb."""
    pass


# Register commands from manage module
cli.add_command(manage.init)
cli.add_command(manage.add)
cli.add_command(manage.remove)
cli.add_command(manage.index)
cli.add_command(manage.reindex)
cli.add_command(manage.update_embeddings)

# Register commands from search module
cli.add_command(search.screenshot)
cli.add_command(search.vsearch)
cli.add_command(search.fulltext)
cli.add_command(search.lsearch)
cli.add_command(search.image_search)
cli.add_command(search.similar)
cli.add_command(search.hybrid_search)

# Register commands from export module
cli.add_command(export.bibtex)
cli.add_command(export.citation)
cli.add_command(export.show)
cli.add_command(export.visit)
cli.add_command(export.about)
cli.add_command(export.sql)

# Register commands from tags module
cli.add_command(tags.add_tag)
cli.add_command(tags.rm_tag)
cli.add_command(tags.delete_tag)
cli.add_command(tags.show_tag)
cli.add_command(tags.list_tags)

# Register commands from review module
cli.add_command(review.review)
cli.add_command(review.summary)

# Register commands from filters module
cli.add_command(filters.add_filter)
cli.add_command(filters.rm_filter)
cli.add_command(filters.update_filters)
cli.add_command(filters.list_filters)

# Register commands from openalex_commands module
cli.add_command(openalex_commands.openalex)
cli.add_command(openalex_commands.author_search)
cli.add_command(openalex_commands.follow)
cli.add_command(openalex_commands.watch)
cli.add_command(openalex_commands.citing)
cli.add_command(openalex_commands.related)
cli.add_command(openalex_commands.unpaywall)

# Register commands from research_commands module
cli.add_command(research_commands.fhresearch)
cli.add_command(research_commands.research)
cli.add_command(research_commands.suggest_reviewers)

# Register commands from data_processing module
cli.add_command(data_processing.crossref)
cli.add_command(data_processing.fromtext)
cli.add_command(data_processing.extract)
cli.add_command(data_processing.schema)
cli.add_command(data_processing.crawl)

# Register commands from utilities module
cli.add_command(utilities.web)
cli.add_command(utilities.audio)
cli.add_command(utilities.chat_command, name="chat")
cli.add_command(utilities.app)
cli.add_command(utilities.version)
cli.add_command(utilities.coa)


if __name__ == "__main__":
    cli()
