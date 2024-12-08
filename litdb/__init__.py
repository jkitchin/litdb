import toml
import tomlkit

from pathlib import Path


def find_root_directory(rootfile):
    """Search upwards for rootfile.
    Returns the root directory, or the current directory if one is not found."""
    wd = Path.cwd()
    while wd != Path("/"):
        if (wd / rootfile).exists():
            return wd
        wd = wd.parent

    return Path.cwd()


# I am not 100% sure this does what I expect. I guess we will see.

CONFIG = "litdb.toml"
root = find_root_directory(CONFIG)

if not (root / CONFIG).exists():
    if input("No config found. Do you want to make one here? (y/n)") == "n":
        import sys

        sys.exit()

    email = input("Email address: ")
    api_key = input("OpenAlex API key (Enter if None): ")

    d = {
        "database": {"db": "litdb.libsql"},
        "embedding": {
            "model": "all-MiniLM-L6-v2",
            "cross-encoder": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "chunk_size": 1000,
            "chunk_overlap": 200,
        },
        "openalex": {"email": email},
    }

    if api_key:
        d["openalex"]["api_key"] = api_key

    with open("litdb.toml", "w") as f:
        toml.dump(d, f)


with open(root / CONFIG) as f:
    config = tomlkit.parse(f.read())
