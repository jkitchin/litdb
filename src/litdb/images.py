"""Add-on to index and search images by text.

This uses the clip transformer to get embedding vectors of images. Then you can
search the images either by textual descriptions, or by using similar images.

"""

from .db import get_db
from sentence_transformers import SentenceTransformer
from PIL import Image, ImageGrab
from pillow_heif import register_heif_opener
import numpy as np
import datetime
import os
import pyperclip

register_heif_opener()

image_extensions = Image.registered_extensions().keys()

model = SentenceTransformer("clip-ViT-B-32")
db = get_db()


def add_image(path):
    """Embed and add the image in path to db."""
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
    If clipboard is True, use an image or text from the clipboard
    """
    if query and os.path.exists(query):
        emb = model.encode(Image.open(query))
    elif query and not os.path.exists(query):
        emb = model.encode(query)
    elif clipboard:
        clip = ImageGrab.grabclipboard()
        if isinstance(clip, Image.Image):
            emb = model.encode(clip)
        else:
            clip = pyperclip.paste()
            print(clip)
            emb = model.encode(clip)

    emb = emb.astype(np.float32).tobytes()

    q = """select source from vector_top_k('image_idx', ?, ?)
    join images on images.rowid = id"""
    results = db.execute(q, (emb, n)).fetchall()

    for (row,) in results:
        print(row)
        Image.open(row).show()

    return results
