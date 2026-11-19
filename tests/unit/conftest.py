"""Shared fixtures for unit tests."""

from unittest.mock import patch

import numpy as np
import pytest

DIM = 4


class FakeModel:
    """Stand-in for SentenceTransformer that returns fixed-size embeddings."""

    def encode(self, texts):
        if isinstance(texts, str):
            return np.ones(DIM, dtype=np.float32)
        return np.ones((len(texts), DIM), dtype=np.float32)


@pytest.fixture
def real_db(tmp_path, monkeypatch):
    """A real litdb database in a temporary root, with a fake embedding model.

    Commands that cache their db connection in a module global get it reset,
    so they use this database.
    """
    from litdb import db as litdb_db

    cfg = {
        "root": str(tmp_path),
        "embedding": {"model": "fake", "chunk_size": 1000, "chunk_overlap": 200},
        "openalex": {"email": "test@example.com"},
    }
    for mod in ("tags", "export", "filters", "openalex_commands", "review"):
        monkeypatch.setattr(f"litdb.commands.{mod}._db", None)
    with (
        patch("litdb.db.get_config", return_value=cfg),
        patch("litdb.commands.manage.get_config", return_value=cfg),
        patch("litdb.db.get_model", return_value=FakeModel()),
        patch("litdb.commands.manage.get_model", return_value=FakeModel()),
    ):
        yield litdb_db.get_db()
