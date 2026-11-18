"""Jupyter Lab interface for litdb."""

import shlex

from IPython import get_ipython
from IPython.core.magic import Magics, line_cell_magic, magics_class


@magics_class
class LitdbMagics(Magics):
    @line_cell_magic
    def litdb(self, line, cell=None):
        """Main litdb magic command using Click."""
        from .cli import cli

        args = shlex.split(line)
        if cell is not None:
            args += [cell]
        cli.main(args=args, standalone_mode=False)


# Register the magic command
ip = get_ipython()
if ip:
    ip.register_magics(LitdbMagics)
