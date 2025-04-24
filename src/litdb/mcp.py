"""An MCP server for litdb.

Provides Claude-Desktop tools to interact with litdb. This is mostly a proof of
concept to retrieve information from litdb, and it does not currently support
modifying the litdb.

There is a cli, litdb_mcp, that runs the server. The cli is installed as a
script.

You can install the server using:

> litdb_mcp install /path/to/litdb.libsql

and uninstall it with

> litdb_mcp uninstall

This should work on Windows, but is untested there.

The mcp server provides three tools:

about: Just describes the server.

vsearch: Performs a vector search from a query. The query is determined by
Claude.

openalex: Performs a keyword search from a query. the query is determined by
Claude.

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
import libsql_experimental as libsql


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

    Using the db at {os.environ['litdb']}.
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

    return str(results)


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
    return data


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
