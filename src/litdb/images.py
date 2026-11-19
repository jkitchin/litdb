"""Add-on to index and search images by text.

This uses the clip transformer to get embedding vectors of images. Then you can
search the images either by textual descriptions, or by using similar images.

"""

import datetime
import functools
import os

import numpy as np
from PIL import Image

from .db import get_db

# Register HEIF support if available (optional dependency)
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

image_extensions = Image.registered_extensions().keys()


@functools.cache
def get_model():
    """Return the CLIP model, loading it on first use.

    Loading is deferred so that importing this module (which every litdb CLI
    command does) does not load or download the model.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("clip-ViT-B-32")


def add_image(path):
    """Embed and add the image in path to db."""
    db = get_db()
    model = get_model()
    emb = model.encode(Image.open(path))

    q = """insert or ignore into
    images(source, embedding, date_added)
    values (?, ?, ?)"""
    db.execute(
        q,
        (
            os.path.abspath(path),
            emb.astype(np.float32).tobytes(),
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    db.commit()


def image_query(query=None, clipboard=False, n=1):
    """Query the image database.

    If query is not None, it is either a text description or path to image.
    If clipboard is True, use an image or text from the clipboard.

    Raises ValueError if there is nothing to search with.
    """
    if query:
        # A path to an existing file is searched as an image; anything else,
        # including a directory name, is searched as text.
        source = Image.open(query) if os.path.isfile(query) else query
    elif clipboard:
        from PIL import ImageGrab

        clip = ImageGrab.grabclipboard()
        if isinstance(clip, Image.Image):
            source = clip
        else:
            try:
                import pyperclip
            except ImportError as e:
                raise ValueError(
                    "Searching with text from the clipboard needs pyperclip: "
                    'pip install "litdb[image]"'
                ) from e
            source = pyperclip.paste()
            if not source:
                raise ValueError("The clipboard has no image or text to search with.")
            print(source)
    else:
        raise ValueError(
            "Provide a query (text or an image path) or use the clipboard."
        )

    db = get_db()
    emb = get_model().encode(source)
    emb = emb.astype(np.float32).tobytes()

    q = """select source from vector_top_k('image_idx', ?, ?)
    join images on images.rowid = id"""
    results = db.execute(q, (emb, n)).fetchall()

    for (row,) in results:
        print(row)
        Image.open(row).show()

    return results
