"""Helpers for rendering user templates in commands."""

from jinja2 import Template
from rich.markup import escape


def _escape(value):
    """Escape rich markup in a value substituted into a template."""
    return escape(str(value))


def rich_template(fmt):
    """Return a jinja Template for FMT whose output is safe to rich-print.

    Values substituted into the template are escaped, so text such as
    "[b]" or "[Pt]" in a title is printed as is instead of being treated as
    rich markup and dropped. Markup written in FMT itself still works.
    """
    return Template(fmt, finalize=_escape)


def elisp_string(value):
    """Return VALUE as the contents of an Emacs lisp string literal."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
