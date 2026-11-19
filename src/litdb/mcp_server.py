"""An MCP server for litdb.

Provides Claude-Desktop tools to interact with litdb. This is mostly a proof of
concept to retrieve information from litdb, and it does not currently support
modifying the litdb.

There is a cli, litdb_mcp, that runs the server. The cli is installed as a
script.

You can install the server in Claude Desktop using:

> litdb install mcp-server

and uninstall it with

> litdb install uninstall-mcp

For other agents (Claude Code, VS Code, Cursor, Codex, ...) use knowhow, which
reads mcp/litdb.json from the litdb repository:

> uvx knowhow add jkitchin/litdb --mcp litdb -a claude-code

The database is the `litdb` environment variable if it is set (Claude Desktop
install), otherwise litdb.libsql next to the litdb.toml found from the working
directory or LITDB_ROOT.

This should work on Windows, but is untested there.

The mcp server provides the following tools:

CORE TOOLS:
about_litdb: Describes the server and database location.

vsearch: Performs a vector search in your litdb database. Returns formatted
summaries with title, authors, year, DOI, similarity score, and full abstract.

openalex: Performs a keyword search in OpenAlex API. Returns formatted summaries
with title, authors, year, venue, DOI, citation count, and full abstract.

SEARCH TOOLS:
fulltext_search: Full-text search using SQLite FTS5 with BM25 ranking. Supports
FTS5 query syntax (AND, OR, NOT). Returns snippets and relevance scores.

find_similar: Find articles similar to a given source using vector similarity.
Great for "more like this" discovery.

METADATA & CITATION TOOLS:
get_source_details: Get complete details for a specific source including full
metadata, abstract, and citation information.

get_citation: Generate a formatted citation string for a source.

get_bibtex: Generate a BibTeX entry for a source (for LaTeX/bibliography managers).

ORGANIZATION TOOLS:
list_tags: List all defined tags in the database.

get_tagged_articles: Get all articles with a specific tag.

NSF GRANT TOOLS:
generate_nsf_coa: Generate NSF Collaborators and Other Affiliations (COA) Table 4.
Creates an Excel file with co-authors from publications in the last 4 years, formatted
for NSF grant applications.

All tools return formatted, readable text with complete information.

"""

import contextlib
import json
import os
import platform
import shutil
import sys

import libsql
import numpy as np
import requests
from mcp.server.fastmcp import FastMCP

from .bibtex import dump_bibtex
from .coa import get_coa
from .db import get_model

# Initialize FastMCP server
mcp = FastMCP("litdb")


def get_db_path():
    """Return the path to the litdb database.

    Uses the litdb environment variable if it is set, otherwise the
    litdb.libsql next to the litdb.toml found by get_config.
    """
    if os.environ.get("litdb"):
        return os.environ["litdb"]

    from .utils import get_config

    # stdout is the MCP stdio transport, so keep get_config messages off it
    try:
        with contextlib.redirect_stdout(sys.stderr):
            config = get_config()
    except SystemExit:
        raise RuntimeError(
            "No litdb.toml found. Set LITDB_ROOT to the directory containing"
            " litdb.toml, or set litdb to the path of litdb.libsql."
        )
    return os.path.join(config["root"], "litdb.libsql")


DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def embedding_model_name(db):
    """Return the name of the model that made the embeddings in DB.

    The db records it in its metadata table, which works even without a
    litdb.toml (the Claude Desktop install only sets the db path).
    """
    try:
        row = db.execute(
            "select value from metadata where key = 'embedding_config'"
        ).fetchone()
    except ValueError:  # an old db without a metadata table
        row = None
    if row:
        return json.loads(row[0])["model"]
    return DEFAULT_EMBEDDING_MODEL


def _fts_literal(query):
    """Quote each word of QUERY so FTS5 matches it literally."""
    return " ".join('"' + w.replace('"', '""') + '"' for w in query.split())


def _abstract(work):
    """Return the abstract of the OpenAlex WORK, or "" if it has none."""
    index = work.get("abstract_inverted_index") or {}
    words = sorted(
        (pos, word) for word, positions in index.items() for pos in positions
    )
    return " ".join(word for _pos, word in words)


def _authors(work, limit=3):
    """Return up to LIMIT author names of the OpenAlex WORK."""
    authorships = work.get("authorships") or []
    names = [
        (a.get("author") or {}).get("display_name") or "Unknown"
        for a in authorships[:limit]
    ]
    if len(authorships) > len(names):
        names.append("et al.")
    return names


def _venue(work):
    """Return the venue name of the OpenAlex WORK, or ""."""
    source = (work.get("primary_location") or {}).get("source") or {}
    return source.get("display_name") or ""


def _title(work):
    """Return the title of the OpenAlex WORK."""
    return work.get("title") or work.get("display_name") or "No title"


def _preview(text, n):
    """Return the first N characters of TEXT."""
    text = text or ""
    return text[:n] + "..." if len(text) > n else text


# Note I added _litdb here because Claude Desktop had trouble with other
# functions named about...
@mcp.tool()
def about_litdb():
    """Describe litdb."""
    return f"""Litdb is a database of scientific literature.

    The MCP server has tools to search it (vsearch, fulltext_search,
    find_similar), to get details, citations and bibtex for a source, to list
    tags and tagged articles, to search OpenAlex, and to make an NSF COA table.

    Using the db at {get_db_path()}.
    """


@mcp.tool()
def vsearch(query: str, n: int = 3) -> str:
    """Do a vector search in your litdb.

    QUERY: string, natural language query.
    N: int, number of results to return.
    """
    db = libsql.connect(get_db_path())

    # The query must be embedded with the model that made the stored
    # embeddings, or the distances are meaningless.
    model = get_model(embedding_model_name(db))
    emb = model.encode([query]).astype(np.float32).tobytes()

    c = db.execute(
        """select sources.source, sources.text,
        sources.extra, vector_distance_cos(?, embedding) as d
        from vector_top_k('embedding_idx', ?, ?)
        join sources on sources.rowid = id
        order by d""",
        (emb, emb, n),
    )

    results = c.fetchall()

    # Format results concisely to avoid hitting token limits
    formatted_results = []
    for i, (source, text, extra, distance) in enumerate(results, 1):
        try:
            extra_data = json.loads(extra) if extra else {}
            title = _title(extra_data)
            authors = _authors(extra_data)
            year = extra_data.get("publication_year", "")

            # Use first 500 chars of full text if there is no abstract
            abstract = _abstract(extra_data) or _preview(text, 500)

            result_text = f"{i}. {title}"
            if authors:
                result_text += f"\n   Authors: {', '.join(authors)}"
            if year:
                result_text += f"\n   Year: {year}"
            result_text += f"\n   Source: {source}"
            result_text += f"\n   Similarity: {1 - distance:.3f}"
            if abstract:
                result_text += f"\n   Abstract: {abstract}"

            formatted_results.append(result_text)
        except Exception as e:
            formatted_results.append(f"{i}. {source}\n   Error: {e!s}")

    return "\n\n".join(formatted_results)


@mcp.tool()
def openalex(
    query: str, n: int = 5, email: str | None = None, api_key: str | None = None
):
    """Run a simple keyword query in OpenAlex.

    Args:
      query: string, natural language query.
      n: int, number of results to return.
      email: optional email for OpenAlex polite pool.
      api_key: optional OpenAlex API key.
    """
    # The search parameter, unlike a filter, allows commas in the query.
    params = {"search": query, "per_page": n}
    if email:
        params["mailto"] = email
    if api_key:
        params["api_key"] = api_key

    try:
        resp = requests.get("https://api.openalex.org/works", params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        return f"OpenAlex request failed: {e}"

    # Format results concisely to avoid hitting token limits
    results = data.get("results", [])
    formatted_results = []

    for i, work in enumerate(results, 1):
        title = _title(work)
        authors = _authors(work)
        year = work.get("publication_year", "")
        abstract = _abstract(work)

        # Get DOI or OpenAlex ID
        doi = work.get("doi") or work.get("id", "")
        venue = _venue(work)

        result_text = f"{i}. {title}"
        if authors:
            result_text += f"\n   Authors: {', '.join(authors)}"
        if year:
            result_text += f"\n   Year: {year}"
        if venue:
            result_text += f"\n   Venue: {venue}"
        if doi:
            result_text += f"\n   DOI/ID: {doi}"
        result_text += f"\n   Citations: {work.get('cited_by_count', 0)}"
        if abstract:
            result_text += f"\n   Abstract: {abstract}"

        formatted_results.append(result_text)

    if not formatted_results:
        return "No results found for this query."

    header = f"Found {data.get('meta', {}).get('count', len(results))} total results (showing {len(results)}):\n\n"
    return header + "\n\n".join(formatted_results)


@mcp.tool()
def fulltext_search(query: str, n: int = 3) -> str:
    """Perform a full-text search using SQLite FTS5 with BM25 ranking.

    Args:
        query: Search query string (can use FTS5 syntax like AND, OR, NOT).
        n: Number of results to return (default 3).

    Returns:
        Formatted results with source, BM25 score, and text snippet.
    """
    db = libsql.connect(get_db_path())

    sql = """select
    sources.source, sources.text, snippet(fulltext, 1, '', '', '', 16),
    sources.extra, bm25(fulltext)
    from fulltext
    inner join sources on fulltext.source = sources.source
    where fulltext.text match ? order by rank limit ?"""
    try:
        results = db.execute(sql, (query, n)).fetchall()
    except ValueError:
        # Not valid FTS5 syntax (e.g. "density-functional" or "Pt(111)"), so
        # search for the words literally.
        try:
            results = db.execute(sql, (_fts_literal(query), n)).fetchall()
        except ValueError as e:
            return f"Invalid full-text query {query!r}: {e}"

    if not results:
        return f"No results found for query: {query}"

    formatted_results = []
    for i, (source, text, snippet, extra, score) in enumerate(results, 1):
        try:
            extra_data = json.loads(extra) if extra else {}
            title = _title(extra_data)
            authors = _authors(extra_data)

            year = extra_data.get("publication_year", "")

            result_text = f"{i}. {title}"
            if authors:
                result_text += f"\n   Authors: {', '.join(authors)}"
            if year:
                result_text += f"\n   Year: {year}"
            result_text += f"\n   Source: {source}"
            result_text += f"\n   BM25 Score: {abs(score):.3f}"
            result_text += f"\n   Snippet: {snippet}"

            formatted_results.append(result_text)
        except Exception as e:
            formatted_results.append(
                f"{i}. {source}\n   Snippet: {snippet}\n   Error: {e!s}"
            )

    return "\n\n".join(formatted_results)


@mcp.tool()
def find_similar(source: str, n: int = 3) -> str:
    """Find articles similar to a given source using vector similarity.

    Args:
        source: The source identifier (DOI, URL, or path) to find similar articles for.
        n: Number of similar articles to return (default 3).

    Returns:
        Formatted list of similar articles with metadata.
    """
    db = libsql.connect(get_db_path())

    # Get the embedding for the source
    try:
        result = db.execute(
            """select embedding from sources where source = ?""", (source,)
        ).fetchone()

        if not result:
            return f"Source not found: {source}"

        (emb,) = result
    except Exception as e:
        return f"Error retrieving source embedding: {e!s}"

    if emb is None:
        return f"{source} has no embedding, so similar articles cannot be found."

    # Get n+1 because the source itself is one of the results, though not
    # always the first when other sources have the same embedding.
    allrows = db.execute(
        """select sources.source, sources.text, sources.extra,
    vector_distance_cos(?, embedding) as d
    from vector_top_k('embedding_idx', ?, ?)
    join sources on sources.rowid = id
    order by d""",
        (emb, emb, n + 1),
    ).fetchall()

    rows = [row[:3] for row in allrows if row[0] != source][:n]

    if not rows:
        return f"No similar articles found for: {source}"

    formatted_results = []
    for i, (sim_source, text, extra) in enumerate(rows, 1):
        try:
            extra_data = json.loads(extra) if extra else {}
            title = _title(extra_data)
            authors = _authors(extra_data)

            year = extra_data.get("publication_year", "")
            citation = extra_data.get("citation", "")

            result_text = f"{i}. {title}"
            if authors:
                result_text += f"\n   Authors: {', '.join(authors)}"
            if year:
                result_text += f"\n   Year: {year}"
            result_text += f"\n   Source: {sim_source}"
            if citation:
                result_text += f"\n   Citation: {citation}"

            formatted_results.append(result_text)
        except Exception as e:
            formatted_results.append(f"{i}. {sim_source}\n   Error: {e!s}")

    return f"Articles similar to {source}:\n\n" + "\n\n".join(formatted_results)


@mcp.tool()
def get_source_details(source: str) -> str:
    """Get complete details for a specific source.

    Args:
        source: The source identifier (DOI, URL, or path).

    Returns:
        Complete source information including full text and metadata.
    """
    db = libsql.connect(get_db_path())

    result = db.execute(
        """select source, text, extra from sources where source = ?""",
        (source,),
    ).fetchone()

    if not result:
        return f"Source not found: {source}"

    source_id, text, extra = result

    try:
        extra_data = json.loads(extra) if extra else {}

        title = _title(extra_data)
        authors = _authors(extra_data, limit=None)
        year = extra_data.get("publication_year", "")
        doi = extra_data.get("doi", "")
        citation = extra_data.get("citation", "")
        abstract = _abstract(extra_data)
        venue = _venue(extra_data)

        cited_by_count = extra_data.get("cited_by_count", 0)
        referenced_works_count = extra_data.get("referenced_works_count", 0)

        output = f"Title: {title}\n"
        if authors:
            output += f"Authors: {', '.join(authors)}\n"
        if year:
            output += f"Year: {year}\n"
        if venue:
            output += f"Venue: {venue}\n"
        if doi:
            output += f"DOI: {doi}\n"
        output += f"Source: {source_id}\n"
        output += f"Citations: {cited_by_count}\n"
        output += f"References: {referenced_works_count}\n"
        if citation:
            output += f"\nFormatted Citation:\n{citation}\n"
        if abstract:
            output += f"\nAbstract:\n{abstract}\n"
        else:
            # Use first 1000 chars of text if no abstract
            output += f"\nText Preview:\n{_preview(text, 1000)}\n"

        return output
    except Exception as e:
        return f"Error formatting source details: {e!s}"


@mcp.tool()
def get_citation(source: str) -> str:
    """Generate a formatted citation string for a source.

    Args:
        source: The source identifier (DOI, URL, or path).

    Returns:
        Formatted citation string.
    """
    db = libsql.connect(get_db_path())

    result = db.execute(
        """select json_extract(extra, '$.citation') from sources where source = ?""",
        (source,),
    ).fetchone()

    if not result:
        return f"Source not found: {source}"

    (citation,) = result

    if not citation:
        return f"No citation available for: {source}"

    return citation


@mcp.tool()
def get_bibtex(source: str) -> str:
    """Generate a BibTeX entry for a source.

    Args:
        source: The source identifier (DOI, URL, or path).

    Returns:
        BibTeX formatted entry.
    """
    db = libsql.connect(get_db_path())

    result = db.execute(
        """select extra from sources where source = ?""", (source,)
    ).fetchone()

    if not result:
        return f"Source not found: {source}"

    (extra,) = result

    if not extra:
        return f"No metadata available for BibTeX generation: {source}"

    try:
        extra_data = json.loads(extra)
        bibtex = dump_bibtex(extra_data)
        return bibtex
    except Exception as e:
        return f"Error generating BibTeX: {e!s}"


@mcp.tool()
def list_tags() -> str:
    """List all defined tags in the database.

    Returns:
        List of all tags.
    """
    db = libsql.connect(get_db_path())

    results = db.execute("select tag from tags").fetchall()

    if not results:
        return "No tags defined in the database."

    tags = [tag for (tag,) in results]
    return "Defined tags:\n" + "\n".join(f"- {tag}" for tag in tags)


@mcp.tool()
def get_tagged_articles(tag: str) -> str:
    """Get all articles with a specific tag.

    Args:
        tag: The tag name to search for.

    Returns:
        Formatted list of articles with the specified tag.
    """
    db = libsql.connect(get_db_path())

    results = db.execute(
        """select
        sources.source, sources.text, sources.extra
        from sources
        inner join source_tag on source_tag.source_id = sources.rowid
        inner join tags on source_tag.tag_id = tags.rowid
        where tags.tag = ?""",
        (tag,),
    ).fetchall()

    if not results:
        return f"No articles found with tag: {tag}"

    formatted_results = []
    for i, (source, text, extra) in enumerate(results, 1):
        try:
            extra_data = json.loads(extra) if extra else {}
            title = _title(extra_data)
            authors = _authors(extra_data)

            year = extra_data.get("publication_year", "")
            citation = extra_data.get("citation", "")

            result_text = f"{i}. {title}"
            if authors:
                result_text += f"\n   Authors: {', '.join(authors)}"
            if year:
                result_text += f"\n   Year: {year}"
            result_text += f"\n   Source: {source}"
            if citation:
                result_text += f"\n   Citation: {citation}"

            formatted_results.append(result_text)
        except Exception as e:
            formatted_results.append(f"{i}. {source}\n   Error: {e!s}")

    return f"Articles tagged with '{tag}' ({len(results)} found):\n\n" + "\n\n".join(
        formatted_results
    )


@mcp.tool()
def generate_nsf_coa(orcid: str, email: str | None = None) -> str:
    """Generate NSF Collaborators and Other Affiliations (COA) Table 4.

    Creates an Excel file with co-authors from publications in the last 4 years.
    The file will be saved directly to your Downloads folder.

    Args:
        orcid: The ORCID identifier (with or without https://orcid.org/ prefix).
        email: Optional email for OpenAlex API polite pool (recommended for better rate limits).

    Returns:
        Success message with file location.
    """
    try:
        file_path = get_coa(orcid, email)
        if file_path is None:
            # Running in Jupyter - get_coa handles display itself
            return "COA generated and displayed in Jupyter"

        return f"""✅ NSF COA Excel file successfully generated!

📁 File saved to: {file_path}

The Excel file contains:
• Table 4: Unique co-authors with their affiliations and last active dates
• All authors sheet: Complete list of all co-authors from each publication

This includes all co-authors from publications in the last 4 years.

You can open the file from your Downloads folder or use the path above to locate it."""
    except Exception as e:
        return f"❌ Failed to generate NSF COA file: {e!s}\n\nMake sure you have write access to your Downloads folder."


def main():
    """Install, uninstall, or run the server.

    This is the cli. If you call it with install or uninstall as an argument, it
    will do that in the Claude Desktop. With no arguments it just runs the
    server.
    """
    # Called with no arguments
    if len(sys.argv) == 1:
        mcp.run(transport="stdio")
        return

    if platform.system() == "Darwin":
        cfgfile = "~/Library/Application Support/Claude/claude_desktop_config.json"
    elif platform.system() == "Windows":
        cfgfile = r"%APPDATA%\Claude\claude_desktop_config.json"
    else:
        raise RuntimeError(
            "Claude Desktop install is only supported on Mac and Windows"
        )

    cfgfile = os.path.expandvars(cfgfile)
    cfgfile = os.path.expanduser(cfgfile)

    if os.path.exists(cfgfile):
        with open(cfgfile, "r") as f:
            cfg = json.loads(f.read())
    else:
        cfg = {}

    if sys.argv[1] == "install":
        if len(sys.argv) < 3:
            sys.exit("Usage: litdb_mcp install path/to/litdb.libsql")
        # Claude Desktop does not start the server in this directory.
        db = os.path.abspath(os.path.expanduser(sys.argv[2]))
        if not os.path.exists(db):
            sys.exit(f"{db} does not exist.")
        command = shutil.which("litdb_mcp")
        if command is None:
            sys.exit("litdb_mcp is not on your PATH.")

        setup = {
            "command": command,
            "env": {"litdb": db, "LITDB_ROOT": os.path.dirname(db)},
        }

        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}

        cfg["mcpServers"]["litdb"] = setup
        with open(cfgfile, "w") as f:
            f.write(json.dumps(cfg, indent=4))

        print(
            f"\n\nInstalled litdb. Here is your current {cfgfile}."
            " Please restart Claude Desktop."
        )
        print(json.dumps(cfg, indent=4))

    elif sys.argv[1] == "uninstall":
        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}

        if "litdb" in cfg["mcpServers"]:
            del cfg["mcpServers"]["litdb"]
            with open(cfgfile, "w") as f:
                f.write(json.dumps(cfg, indent=4))

        print(f"Uninstalled litdb. Here is your current {cfgfile}.")
        print(json.dumps(cfg, indent=4))

    else:
        print(
            "I am not sure what you are trying to do. Please use install or uninstall."
        )
