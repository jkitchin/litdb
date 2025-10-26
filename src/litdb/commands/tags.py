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
from jinja2 import Template
from rich import print as richprint

from ..db import get_db


# Lazy database initialization
db = None


def get_tags_db():
    """Get or create database connection for tag commands."""
    global db
    if db is None:
        db = get_db()
    return db


# Initialize db for module
db = get_tags_db()


@click.command()
@click.argument("sources", nargs=-1)
@click.option("-t", "--tag", "tags", multiple=True)
def add_tag(sources, tags):
    """Add tags to sources.

    It is a little annoying to add multiple tags. It looks like this.
    litdb add-tag source -t tag1 -t tag2
    """
    for source in sources:
        # Get source id
        (source_id,) = db.execute(
            "select rowid from sources where source = ?", (source,)
        ).fetchone()

        for tag in tags:
            # get tag id
            tag_id = db.execute(
                "select rowid from tags where tag = ?", (tag,)
            ).fetchone()

            if not tag_id:
                c = db.execute("insert into tags(tag) values (?)", (tag,))
                tag_id = c.lastrowid
                db.commit()
            else:
                # we get a tuple in the first query
                (tag_id,) = tag_id

            # Now add a tag
            db.execute(
                "insert into source_tag(source_id, tag_id) values (?, ?)",
                (source_id, tag_id),
            )
            db.commit()

            print(f"Tagged {source} with {tag}")


@click.command()
@click.argument("sources", nargs=-1)
@click.option("-t", "--tag", "tags", multiple=True)
def rm_tag(sources, tags):
    """Remove tags from sources.

    It is a little annoying to remove multiple tags. It looks like this.
    litdb rm-tag source -t tag1 -t tag2
    """
    for source in sources:
        # Get source id
        (source_id,) = db.execute(
            "select rowid from sources where source = ?", (source,)
        ).fetchone()

        for tag in tags:
            # get tag id. Assume it exists?
            (tag_id,) = db.execute(
                "select rowid from tags where tag = ?", (tag,)
            ).fetchone()

            c = db.execute(
                """delete from source_tag
            where source_id = ? and tag_id = ?""",
                (source_id, tag_id),
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
        c = db.execute("delete from tags where tag = ?", (tag,))
        print(f"Deleted {c.rowcount} rows ({tag})")
    db.commit()


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
    template = Template(fmt)
    for tag in tags:
        for row in db.execute(
            """select
        sources.source, sources.text, sources.extra
        from sources
        inner join source_tag on source_tag.source_id = sources.rowid
        inner join tags on source_tag.tag_id = tags.rowid
        where tags.tag = ?""",
            (tag,),
        ).fetchall():
            source, text, extra = row
            extra = json.loads(extra)
            richprint(template.render(**locals()))


@click.command()
def list_tags():
    """Print defined tags."""
    print("The following tags are defined.")
    for (tag,) in db.execute("select tag from tags").fetchall():
        print(tag)
