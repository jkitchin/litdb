import os
from pathlib import Path

import toml
import tomlkit

def find_root_directory(rootfile):
    """Search upwards for rootfile.
    Returns the root directory, or the current directory if one is not found."""
    wd = Path.cwd()
    while wd != Path("/"):
        if (wd / rootfile).exists():
            return wd
        wd = wd.parent

    return Path.cwd()


CONFIG = "litdb.toml"
root = find_root_directory(CONFIG)

# if you don't find a litdb.toml you might not be in a litdb root. We check for
# an env var next so that litdb works everywhere.
if not (root / CONFIG).exists():
    litdb_root = os.environ.get('LITDB_ROOT')
    if litdb_root:
        root = Path(litdb_root)


def init_litdb():
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
        "gpt": {'model': 'llama2'}
    }

    if api_key:
        d["openalex"]["api_key"] = api_key

    with open("litdb.toml", "w") as f:
        toml.dump(d, f)

    
# If you aren't in a litdb project, and there is no env var, we might have to
# make a new one. We ask for confirmation before doing this.
if not (root / CONFIG).exists():
    if input("No config found. Do you want to make one here? (y/n)") == "n":
        import sys
        sys.exit()
    else:
        init_litdb()
    
# This file should exist if you get here.
with open(root / CONFIG) as f:
    config = tomlkit.parse(f.read())
