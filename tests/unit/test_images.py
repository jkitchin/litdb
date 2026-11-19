"""Unit tests for litdb.images (CLIP image search)."""

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from litdb import images
from litdb.cli import cli


@pytest.fixture
def fake_model():
    """Patch get_model with a fake CLIP model."""
    model = MagicMock()
    model.encode.return_value = np.array([0.1, 0.2], dtype=np.float32)
    with patch("litdb.images.get_model", return_value=model):
        yield model


@pytest.fixture
def fake_db():
    """Patch get_db with a database that returns no hits."""
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    with patch("litdb.images.get_db", return_value=db):
        yield db


@pytest.mark.unit
def test_import_does_not_load_model():
    """Importing litdb.images must not load the CLIP model."""
    assert images.get_model.cache_info().currsize == 0


@pytest.mark.unit
def test_image_query_without_input_raises(fake_model, fake_db):
    """No query and no clipboard is an error, not an UnboundLocalError."""
    with pytest.raises(ValueError, match="Provide a query"):
        images.image_query(None, clipboard=False)
    fake_model.encode.assert_not_called()


@pytest.mark.unit
def test_image_query_empty_clipboard_raises(fake_model, fake_db):
    """An empty clipboard is an error instead of searching for ''."""
    pyperclip = MagicMock()
    pyperclip.paste.return_value = ""
    with (
        patch("PIL.ImageGrab.grabclipboard", return_value=None),
        patch.dict(sys.modules, {"pyperclip": pyperclip}),
        pytest.raises(ValueError, match="clipboard has no image or text"),
    ):
        images.image_query(None, clipboard=True)
    fake_model.encode.assert_not_called()


@pytest.mark.unit
def test_image_query_clipboard_text_without_pyperclip(fake_model, fake_db):
    """Clipboard text without the image extra explains what to install."""
    with (
        patch("PIL.ImageGrab.grabclipboard", return_value=None),
        patch.dict(sys.modules, {"pyperclip": None}),
        pytest.raises(ValueError, match=r"litdb\[image\]"),
    ):
        images.image_query(None, clipboard=True)


@pytest.mark.unit
def test_image_query_clipboard_image(fake_model, fake_db):
    """An image on the clipboard is used without needing pyperclip."""
    img = Image.new("RGB", (4, 4))
    with (
        patch("PIL.ImageGrab.grabclipboard", return_value=img),
        patch.dict(sys.modules, {"pyperclip": None}),
    ):
        images.image_query(None, clipboard=True)
    fake_model.encode.assert_called_once_with(img)


@pytest.mark.unit
def test_image_query_text(fake_model, fake_db):
    """A query that is not a file is encoded as text."""
    images.image_query("a red bicycle")
    fake_model.encode.assert_called_once_with("a red bicycle")


@pytest.mark.unit
def test_image_query_directory_is_text(fake_model, fake_db, tmp_path):
    """A directory name is searched as text, not opened as an image."""
    images.image_query(str(tmp_path))
    fake_model.encode.assert_called_once_with(str(tmp_path))


@pytest.mark.unit
def test_image_query_image_file(fake_model, fake_db, tmp_path):
    """A path to an image file is encoded as an image."""
    path = tmp_path / "x.png"
    Image.new("RGB", (4, 4)).save(path)
    images.image_query(str(path))
    (arg,), _ = fake_model.encode.call_args
    assert isinstance(arg, Image.Image)


@pytest.mark.unit
def test_image_search_cli_without_query():
    """`litdb image-search` with no query gives a usage error."""
    result = CliRunner().invoke(cli, ["image-search"])
    assert result.exit_code == 2
    assert "Provide a query" in result.output
