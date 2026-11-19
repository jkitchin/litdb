"""Tag management commands for litdb.

Commands:
- add_tag: Add tags to sources
- rm_tag: Remove tags from sources
- delete_tag: Delete tags completely
- show_tag: Show entries with tags
- list_tags: List all defined tags
"""

import json

import click
from rich import print as richprint

from ..db import get_db, tag_source
from ._render import rich_template

# Lazy database initialization
_db = None


def get_tags_db():
    """Get or create database connection for tag commands."""
    global _db
    if _db is None:
        _db = get_db()
    return _db


@click.command()
@click.argument("sources", nargs=-1)
@click.option("-t", "--tag", "tags", multiple=True)
def add_tag(sources, tags):
    """Add tags to sources.

    It is a little annoying to add multiple tags. It looks like this.
    litdb add-tag source -t tag1 -t tag2
    """
    db = get_tags_db()
    for source in sources:
        for tag in tags:
            if tag_source(db, source, tag):
                print(f"Tagged {source} with {tag}")
            else:
                print(f"{source} is not in the database.")
                break


@click.command()
@click.argument("sources", nargs=-1)
@click.option("-t", "--tag", "tags", multiple=True)
def rm_tag(sources, tags):
    """Remove tags from sources.

    It is a little annoying to remove multiple tags. It looks like this.
    litdb rm-tag source -t tag1 -t tag2
    """
    db = get_tags_db()
    for source in sources:
        for tag in tags:
            c = db.execute(
                """delete from source_tag
            where source_id = (select rowid from sources where source = ?)
            and tag_id = (select rowid from tags where tag = ?)""",
                (source, tag),
            )
            db.commit()
            print(f"Deleted {c.rowcount} rows ({tag} from {source})")


@click.command()
@click.argument("tags", nargs=-1)
def delete_tag(tags):
    """Delete each tag.

    This should also delete tags from sources by cascade.
    """
    for tag in tags:
        get_tags_db().execute(
            """delete from source_tag
            where tag_id = (select rowid from tags where tag = ?)""",
            (tag,),
        )
        c = get_tags_db().execute("delete from tags where tag = ?", (tag,))
        print(f"Deleted {c.rowcount} rows ({tag})")
    get_tags_db().commit()


@click.command()
@click.argument("tags", nargs=-1)
@click.option("-f", "--fmt", default='{{ source }}\n{{ extra["citation"] }}')
def show_tag(tags, fmt):
    """Show entries with tags.

    FMT is a jinja template for the output. You have variables of source, text
    and extra.

    I don't have good logic here, we just show all entries. I could probably get
    some basic and logic with sets, but mostly I assume for now you only want
    one tag, so this works. TODO: add something like boolean logic?

    """
    template = rich_template(fmt)
    for tag in tags:
        for row in (
            get_tags_db()
            .execute(
                """select
        sources.source, sources.text, sources.extra
        from sources
        inner join source_tag on source_tag.source_id = sources.rowid
        inner join tags on source_tag.tag_id = tags.rowid
        where tags.tag = ?""",
                (tag,),
            )
            .fetchall()
        ):
            source, text, extra = row
            extra = json.loads(extra)
            richprint(template.render(**locals()))


@click.command()
def list_tags():
    """Print defined tags."""
    print("The following tags are defined.")
    for (tag,) in get_tags_db().execute("select tag from tags").fetchall():
        print(tag)
