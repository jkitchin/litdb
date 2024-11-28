import tomlkit

from pathlib import Path

def find_root_directory(rootfile):
    """Search upwards for rootfile.
    Returns the root directory, or the current directory if one is not found."""
    wd = Path.cwd()
    while wd != Path('/'):
        if (wd / rootfile).exists():
            return wd
        wd = wd.parent

    return Path.cwd()

# I am not 100% sure this does what I expect. I guess we will see.

CONFIG = 'litdb.toml'
root = find_root_directory(CONFIG)

with open(root / CONFIG) as f:
    config = tomlkit.parse(f.read())

