"""Jupyter Lab interface for litdb."""

import shlex
from IPython.core.magic import Magics, magics_class, line_cell_magic
from IPython import get_ipython
from .cli import cli


@magics_class
class LitdbMagics(Magics):
    @line_cell_magic
    def litdb(self, line, cell=None):
        """Main litdb magic command using Click."""
        args = shlex.split(line)
        cli.main(args=args, standalone_mode=False)


# Register the magic command
ip = get_ipython()
ip.register_magics(LitdbMagics)
