"""Utility functions used in litdb."""

import json
import os
import sys
from pathlib import Path

import toml
import tomlkit


def find_root_directory(rootfile="litdb.toml"):
    """Search upwards for rootfile.

    Returns the root directory, or the current directory if one is not found.
    """
    wd = Path.cwd()
    while wd != Path("/"):
        if (wd / rootfile).exists():
            return wd
        wd = wd.parent

    return Path.cwd()


def init_litdb():
    """Initialize litdb in the current directory.

    This just creates the config.
    """
    email = input("Email address: ")
    api_key = input("OpenAlex API key (Enter if None): ")

    d = {
        "embedding": {
            "model": "all-MiniLM-L6-v2",
            "cross-encoder": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "chunk_size": 1000,
            "chunk_overlap": 200,
        },
        "openalex": {"email": email},
        "llm": {"model": "ollama/llama2"},
    }

    if api_key:
        d["openalex"]["api_key"] = api_key

    with open("litdb.toml", "w") as f:
        toml.dump(d, f)


def get_config():
    """Return the config dictionary.

    Priority:
    1. There is a root / litdb.toml
    2. There is a LITDB_ROOT/litdb.toml
    """
    CONFIG = "litdb.toml"
    root = find_root_directory()
    if (root / CONFIG).exists():
        pass
    else:
        root = os.environ.get("LITDB_ROOT")
        if root:
            root = Path(root)
            if (root / CONFIG).exists():
                pass

    # if you don't find a litdb.toml you might not be in a litdb root. We check
    # for an env var next so that litdb works everywhere.
    if root is None or not (root / CONFIG).exists():
        # Exit with a failure status (and the message on stderr) so scripts and
        # the MCP server can tell that nothing ran.
        sys.exit('No config found. You need to run "litdb init"')

    with open(root / CONFIG) as f:
        config = tomlkit.parse(f.read())

    config["root"] = str(root)

    return config


def extract_json(text: str) -> str:
    """
    Extract the first JSON object or array from `text`.
    Finds the first '{' or '[', then scans forward matching braces/brackets,
    ignoring ones inside string literals. Returns the JSON substring.
    Raises ValueError if no valid JSON is found.
    """
    # 1) Locate first opening brace/bracket
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        raise ValueError("No JSON object or array found in text")

    # 2) Scan forward to find the matching closing brace/bracket
    stack = []
    mapping = {"]": "[", "}": "{"}
    in_string = False
    escape = False

    for i, ch in enumerate(text[start:], start):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if not stack or stack[-1] != mapping[ch]:
                    raise ValueError(f"Mismatched closing {ch!r} at position {i}")
                stack.pop()
                if not stack:
                    # Found the matching closing bracket
                    candidate = text[start : i + 1]
                    # Optional: validate it's real JSON
                    try:
                        json.loads(candidate)
                    except json.JSONDecodeError as e:
                        raise ValueError(
                            f"Extracted text is not valid JSON: {e}"
                        ) from e
                    return candidate

    raise ValueError("No matching closing bracket found for JSON start")


def fts_literal(query):
    """Quote each word of QUERY so FTS5 matches it literally."""
    return " ".join('"' + w.replace('"', '""') + '"' for w in query.split())


def fts_query(db, sql, query, *params):
    """Run SQL, whose first parameter is an FTS5 MATCH, for QUERY.

    QUERY is tried as FTS5 syntax, and if that is invalid (e.g.
    "density-functional" or "Pt(111)"), as literal words. Raises ValueError if
    neither works.
    """
    try:
        return db.execute(sql, (query, *params)).fetchall()
    except ValueError:
        return db.execute(sql, (fts_literal(query), *params)).fetchall()
