"""An MCP server for litdb.

Provides Claude-Desktop tools to interact with litdb. This is mostly a proof of
concept to retrieve information from litdb, and it does not currently support
modifying the litdb.

There is a cli, litdb_mcp, that runs the server. The cli is installed as a
script.

You can install the server using:

> litdb install mcp-server

and uninstall it with

> litdb install uninstall-mcp

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

from mcp.server.fastmcp import FastMCP
import requests
import json
import platform
import os
import shutil
import sys

from sentence_transformers import SentenceTransformer
import numpy as np
import libsql

from .bibtex import dump_bibtex
from .coa import get_coa


# Initialize FastMCP server
mcp = FastMCP("litdb")


# Note I added _litdb here because Claude Desktop had trouble with other
# functions named about...
@mcp.tool()
def about_litdb():
    """Describe litdb."""
    return f"""Litdb is a database of scientific literature.

    The MCP server has three tools, this one, a vector search tool, and an
    OpenAlex search integration.

    Using the db at {os.environ["litdb"]}.
    """


@mcp.tool()
def vsearch(query: str, n: int = 3) -> str:
    """Do a vector search in your litdb.

    QUERY: string, natural language query.
    N: int, number of results to return.
    """
    db = libsql.connect(os.environ["litdb"])

    model = SentenceTransformer("all-MiniLM-L6-v2")
    emb = model.encode([query]).astype(np.float32).tobytes()

    c = db.execute(
        """select sources.source, sources.text,
        sources.extra, vector_distance_cos(?, embedding)
        from vector_top_k('embedding_idx', ?, ?)
        join sources on sources.rowid = id""",
        (emb, emb, n),
    )

    results = c.fetchall()

    # Format results concisely to avoid hitting token limits
    formatted_results = []
    for i, (source, text, extra, distance) in enumerate(results, 1):
        try:
            extra_data = json.loads(extra) if extra else {}
            title = extra_data.get("title") or extra_data.get(
                "display_name", "No title"
            )

            # Get authors (limit to first 3)
            authors = []
            if extra_data.get("authorships"):
                authors = [
                    a.get("author", {}).get("display_name", "Unknown")
                    for a in extra_data["authorships"][:3]
                ]
                if len(extra_data["authorships"]) > 3:
                    authors.append("et al.")

            # Get publication year
            year = extra_data.get("publication_year", "")

            # Get abstract (full text)
            abstract = extra_data.get("abstract", "")
            if not abstract and text:
                # Use first 500 chars of full text if no abstract
                abstract = text[:500] + "..." if len(text) > 500 else text

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
            formatted_results.append(f"{i}. {source}\n   Error: {str(e)}")

    return "\n\n".join(formatted_results)


@mcp.tool()
def openalex(query: str, n: int = 5):
    """Run a simple keyword query in OpenAlex.

    Args:
      query: string, natural language query.
      n: int, number of results to return.
    """
    params = {"filter": f"default.search:{query}", "per_page": n}

    resp = requests.get("https://api.openalex.org/works", params)
    data = resp.json()

    # Format results concisely to avoid hitting token limits
    results = data.get("results", [])
    formatted_results = []

    for i, work in enumerate(results, 1):
        title = work.get("title") or work.get("display_name", "No title")

        # Get authors (limit to first 3)
        authors = []
        if work.get("authorships"):
            authors = [
                a.get("author", {}).get("display_name", "Unknown")
                for a in work["authorships"][:3]
            ]
            if len(work["authorships"]) > 3:
                authors.append("et al.")

        # Get publication year
        year = work.get("publication_year", "")

        # Get abstract (full text)
        abstract_inv = work.get("abstract_inverted_index", {})
        if abstract_inv:
            # Reconstruct abstract from inverted index
            word_positions = []
            for word, positions in abstract_inv.items():
                for pos in positions:
                    word_positions.append((pos, word))
            # Sort by position and join
            word_positions.sort()
            abstract = " ".join(word for pos, word in word_positions)
        else:
            abstract = ""

        # Get DOI or OpenAlex ID
        doi = work.get("doi") or work.get("id", "")

        # Get journal/venue
        venue = ""
        if work.get("host_venue"):
            venue = work["host_venue"].get("display_name", "")
        elif work.get("primary_location", {}).get("source"):
            venue = work["primary_location"]["source"].get("display_name", "")

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
    db = libsql.connect(os.environ["litdb"])

    results = db.execute(
        """select
    sources.source, sources.text, snippet(fulltext, 1, '', '', '', 16),
    sources.extra, bm25(fulltext)
    from fulltext
    inner join sources on fulltext.source = sources.source
    where fulltext.text match ? order by rank limit ?""",
        (query, n),
    ).fetchall()

    if not results:
        return f"No results found for query: {query}"

    formatted_results = []
    for i, (source, text, snippet, extra, score) in enumerate(results, 1):
        try:
            extra_data = json.loads(extra) if extra else {}
            title = extra_data.get("title") or extra_data.get(
                "display_name", "No title"
            )

            # Get authors (limit to first 3)
            authors = []
            if extra_data.get("authorships"):
                authors = [
                    a.get("author", {}).get("display_name", "Unknown")
                    for a in extra_data["authorships"][:3]
                ]
                if len(extra_data["authorships"]) > 3:
                    authors.append("et al.")

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
                f"{i}. {source}\n   Snippet: {snippet}\n   Error: {str(e)}"
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
    db = libsql.connect(os.environ["litdb"])

    # Get the embedding for the source
    try:
        result = db.execute(
            """select embedding from sources where source = ?""", (source,)
        ).fetchone()

        if not result:
            return f"Source not found: {source}"

        (emb,) = result
    except Exception as e:
        return f"Error retrieving source embedding: {str(e)}"

    # Find similar sources (we get n+1 because the first is always the source itself)
    allrows = db.execute(
        """select sources.source, sources.text, sources.extra
    from vector_top_k('embedding_idx', ?, ?)
    join sources on sources.rowid = id""",
        (emb, n + 1),
    ).fetchall()

    # Skip the first result (the source itself)
    rows = allrows[1:]

    if not rows:
        return f"No similar articles found for: {source}"

    formatted_results = []
    for i, (sim_source, text, extra) in enumerate(rows, 1):
        try:
            extra_data = json.loads(extra) if extra else {}
            title = extra_data.get("title") or extra_data.get(
                "display_name", "No title"
            )

            # Get authors (limit to first 3)
            authors = []
            if extra_data.get("authorships"):
                authors = [
                    a.get("author", {}).get("display_name", "Unknown")
                    for a in extra_data["authorships"][:3]
                ]
                if len(extra_data["authorships"]) > 3:
                    authors.append("et al.")

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
            formatted_results.append(f"{i}. {sim_source}\n   Error: {str(e)}")

    return f"Articles similar to {source}:\n\n" + "\n\n".join(formatted_results)


@mcp.tool()
def get_source_details(source: str) -> str:
    """Get complete details for a specific source.

    Args:
        source: The source identifier (DOI, URL, or path).

    Returns:
        Complete source information including full text and metadata.
    """
    db = libsql.connect(os.environ["litdb"])

    result = db.execute(
        """select source, text, extra from sources where source = ?""",
        (source,),
    ).fetchone()

    if not result:
        return f"Source not found: {source}"

    source_id, text, extra = result

    try:
        extra_data = json.loads(extra) if extra else {}

        title = extra_data.get("title") or extra_data.get("display_name", "No title")

        # Get full author list
        authors = []
        if extra_data.get("authorships"):
            authors = [
                a.get("author", {}).get("display_name", "Unknown")
                for a in extra_data["authorships"]
            ]

        year = extra_data.get("publication_year", "")
        doi = extra_data.get("doi", "")
        citation = extra_data.get("citation", "")
        abstract = extra_data.get("abstract", "")
        venue = ""
        if extra_data.get("host_venue"):
            venue = extra_data["host_venue"].get("display_name", "")
        elif extra_data.get("primary_location", {}).get("source"):
            venue = extra_data["primary_location"]["source"].get("display_name", "")

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
            text_preview = text[:1000] + "..." if len(text) > 1000 else text
            output += f"\nText Preview:\n{text_preview}\n"

        return output
    except Exception as e:
        return f"Error formatting source details: {str(e)}"


@mcp.tool()
def get_citation(source: str) -> str:
    """Generate a formatted citation string for a source.

    Args:
        source: The source identifier (DOI, URL, or path).

    Returns:
        Formatted citation string.
    """
    db = libsql.connect(os.environ["litdb"])

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
    db = libsql.connect(os.environ["litdb"])

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
        return f"Error generating BibTeX: {str(e)}"


@mcp.tool()
def list_tags() -> str:
    """List all defined tags in the database.

    Returns:
        List of all tags.
    """
    db = libsql.connect(os.environ["litdb"])

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
    db = libsql.connect(os.environ["litdb"])

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
            title = extra_data.get("title") or extra_data.get(
                "display_name", "No title"
            )

            # Get authors (limit to first 3)
            authors = []
            if extra_data.get("authorships"):
                authors = [
                    a.get("author", {}).get("display_name", "Unknown")
                    for a in extra_data["authorships"][:3]
                ]
                if len(extra_data["authorships"]) > 3:
                    authors.append("et al.")

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
            formatted_results.append(f"{i}. {source}\n   Error: {str(e)}")

    return f"Articles tagged with '{tag}' ({len(results)} found):\n\n" + "\n\n".join(
        formatted_results
    )


@mcp.tool()
def generate_nsf_coa(orcid: str, email: str = None) -> str:
    """Generate NSF Collaborators and Other Affiliations (COA) Table 4.

    Creates an Excel file with co-authors from publications in the last 4 years.

    Args:
        orcid: The ORCID identifier (with or without https://orcid.org/ prefix).
        email: Optional email for OpenAlex API polite pool (recommended for better rate limits).

    Returns:
        Status message with the filename of the generated Excel file.
    """
    try:
        get_coa(orcid, email)
        # The get_coa function prints the filename, so we extract it from the pattern
        import datetime

        orcid_clean = orcid.replace("https://orcid.org/", "")
        today = datetime.date.today().strftime("%Y-%m-%d.xlsx")
        filename = f"{orcid_clean}-{today}"

        return f"Successfully generated NSF COA file: {filename}\n\nThe file contains:\n- Table 4: Unique co-authors with their affiliations and last active dates\n- All authors sheet: Complete list of all co-authors from each publication\n\nThis includes all co-authors from publications in the last 4 years."
    except Exception as e:
        return f"Error generating NSF COA file: {str(e)}"


def main():
    """Install, uninstall, or run the server.

    This is the cli. If you call it with install or uninstall as an argument, it
    will do that in the Claude Desktop. With no arguments it just runs the
    server.
    """
    if platform.system() == "Darwin":
        cfgfile = "~/Library/Application Support/Claude/claude_desktop_config.json"
    elif platform.system() == "Windows":
        cfgfile = r"%APPDATA%\Claude\claude_desktop_config.json"
    else:
        raise Exception(
            "Only Mac and Windows are supported for the claude-light mcp server"
        )

    cfgfile = os.path.expandvars(cfgfile)
    cfgfile = os.path.expanduser(cfgfile)

    if os.path.exists(cfgfile):
        with open(cfgfile, "r") as f:
            cfg = json.loads(f.read())
    else:
        cfg = {}

    # Called with no arguments
    if len(sys.argv) == 1:
        mcp.run(transport="stdio")

    elif sys.argv[1] == "install":
        db = sys.argv[2]

        setup = {
            "command": shutil.which("litdb_mcp"),
            "env": {"litdb": db, "LITDB_ROOT": os.path.dirname(os.path.abspath(db))},
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
