"""Utility functions used in litdb."""

import os
from pathlib import Path
import sys
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
        "gpt": {"model": "ollama/llama2"},
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
    if not (root / CONFIG).exists():
        print('No config found. You need to run "litdb init"')
        sys.exit()

    with open(root / CONFIG) as f:
        config = tomlkit.parse(f.read())

    config["root"] = str(root)

    return config
