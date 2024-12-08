"""plugin to add a PDF to litdb."""

import litdb.db

import pymupdf4llm


def add_pdf(sources):
    """Add SOURCES to litdb.

    sources: a list of paths to a pdf file.
    """
    if not isinstance(sources, list):
        sources = [sources]

    for source in sources:
        text = pymupdf4llm.to_markdown(source)
        litdb.db.add_source(source, text)
        print(f"Added {source}")
