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

The mcp server provides three tools:

about_litdb: Describes the server and database location.

vsearch: Performs a vector search in your litdb database. Returns formatted
summaries with title, authors, year, DOI, similarity score, and full abstract.

openalex: Performs a keyword search in OpenAlex API. Returns formatted summaries
with title, authors, year, venue, DOI, citation count, and full abstract.

All tools return formatted, readable text with complete abstracts.

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
