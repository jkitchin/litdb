"""Unit tests for CLI search commands (vsearch, fulltext, hybrid-search).

These tests cover search functionality that will be moved to
commands/search.py during refactoring.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
import numpy as np

from litdb.cli import cli


class TestVsearchCommand:
    """Test the 'litdb vsearch' command (vector search)."""

    @pytest.mark.unit
    @patch("litdb.commands.search.get_config")
    @patch("litdb.commands.search.SentenceTransformer")
    @patch("litdb.commands.search.get_db")
    def test_vsearch_basic(self, mock_get_db, mock_model_cls, mock_config):
        """Test basic vector search."""
        mock_config.return_value = {"embedding": {"model": "test-model"}}
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
        mock_model_cls.return_value = mock_model

        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("source1.pdf", "test text 1", "{}", 0.95),
            ("source2.pdf", "test text 2", "{}", 0.85),
        ]
        mock_db.execute.return_value = mock_cursor
        mock_get_db.return_value = mock_db

        runner = CliRunner()
        result = runner.invoke(cli, ["vsearch", "machine learning", "-n", "2"])

        assert result.exit_code == 0
        mock_model.encode.assert_called_once()
        mock_db.execute.assert_called_once()

    @pytest.mark.unit
    @patch("litdb.commands.search.get_config")
    @patch("litdb.commands.search.SentenceTransformer")
    @patch("litdb.commands.search.get_db")
    def test_vsearch_with_emacs_format(self, mock_get_db, mock_model_cls, mock_config):
        """Test vsearch with emacs output format."""
        mock_config.return_value = {"embedding": {"model": "test-model"}}
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
        mock_model_cls.return_value = mock_model

        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("source1.pdf", "text 1", "{}", 0.95),
        ]
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["vsearch", "test query", "--emacs"])

        assert result.exit_code == 0
        assert "(" in result.output  # Emacs format uses lisp syntax

    @pytest.mark.unit
    @patch("litdb.commands.search.get_config")
    @patch("litdb.commands.search.SentenceTransformer")
    @patch("litdb.commands.search.get_db")
    @patch("sentence_transformers.cross_encoder.CrossEncoder")
    def test_vsearch_with_cross_encode(
        self, mock_cross_encoder_cls, mock_get_db, mock_model_cls, mock_config
    ):
        """Test vsearch with cross-encoder reranking."""
        mock_config.return_value = {
            "embedding": {"model": "test-model", "cross-encoder": "test-ce"}
        }
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
        mock_model_cls.return_value = mock_model

        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("source1.pdf", "text 1", "{}", 0.95),
            ("source2.pdf", "text 2", "{}", 0.85),
        ]
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value = mock_cursor

        mock_ce = MagicMock()
        mock_ce.predict.return_value = np.array([0.7, 0.9])
        mock_cross_encoder_cls.return_value = mock_ce

        runner = CliRunner()
        result = runner.invoke(cli, ["vsearch", "test", "--cross-encode"])

        assert result.exit_code == 0
        mock_ce.predict.assert_called_once()

    @pytest.mark.unit
    def test_vsearch_command_exists(self):
        """Test that vsearch command is properly registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["vsearch", "--help"])

        assert result.exit_code == 0
        assert "vector search" in result.output.lower()


class TestFulltextCommand:
    """Test the 'litdb fulltext' command."""

    @pytest.mark.unit
    @patch("litdb.commands.search.get_db")
    def test_fulltext_basic(self, mock_get_db):
        """Test basic full-text search."""
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("source1.pdf", "full text 1", "snippet 1", "{}", -2.5),
            ("source2.pdf", "full text 2", "snippet 2", "{}", -3.1),
        ]
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["fulltext", "machine learning"])

        assert result.exit_code == 0
        mock_db.execute.assert_called_once()

    @pytest.mark.unit
    @patch("litdb.commands.search.get_db")
    def test_fulltext_with_limit(self, mock_get_db):
        """Test fulltext with result limit."""
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_get_db.return_value = mock_db
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["fulltext", "test query", "-n", "5"])

        assert result.exit_code == 0
        # Check that the limit was passed to the query
        call_args = mock_db.execute.call_args[0]
        assert 5 in call_args[1]  # The limit should be in the parameters

    @pytest.mark.unit
    def test_fulltext_command_exists(self):
        """Test that fulltext command is properly registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fulltext", "--help"])

        assert result.exit_code == 0
        assert "fulltext" in result.output.lower()


class TestHybridSearchCommand:
    """Test the 'litdb hybrid-search' command."""

    @pytest.mark.unit
    @patch("litdb.commands.search.get_config")
    @patch("litdb.commands.search.SentenceTransformer")
    @patch("litdb.commands.search.get_db")
    def test_hybrid_search_basic(self, mock_get_db, mock_model_cls, mock_config):
        """Test basic hybrid search."""
        mock_config.return_value = {"embedding": {"model": "test-model"}}
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)
        mock_model_cls.return_value = mock_model

        mock_db = MagicMock()
        mock_cursor_vsearch = MagicMock()
        mock_cursor_fulltext = MagicMock()
        mock_cursor_final = MagicMock()

        # First call for vsearch, second for fulltext, third for final results
        mock_cursor_vsearch.fetchall.return_value = [
            ("source1.pdf", "text 1", "{}", 0.95),
            ("source2.pdf", "text 2", "{}", 0.85),
        ]
        mock_cursor_fulltext.fetchall.return_value = [
            ("source1.pdf", "text 1", "snippet 1", "{}", -2.5),
            ("source3.pdf", "text 3", "snippet 3", "{}", -3.5),
        ]
        mock_cursor_final.fetchone.return_value = ("source1.pdf", "text 1", "{}")

        mock_get_db.return_value = mock_db
        mock_db.execute.side_effect = [
            mock_cursor_vsearch,
            mock_cursor_fulltext,
            mock_cursor_final,
            mock_cursor_final,
            mock_cursor_final,
        ]

        runner = CliRunner()
        result = runner.invoke(
            cli, ["hybrid-search", "vector query", "text query", "-n", "3"]
        )

        assert result.exit_code == 0
        # Should call execute at least twice (vsearch + fulltext)
        assert mock_db.execute.call_count >= 2

    @pytest.mark.unit
    def test_hybrid_search_command_exists(self):
        """Test that hybrid-search command is properly registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["hybrid-search", "--help"])

        assert result.exit_code == 0
        assert "hybrid" in result.output.lower()


class TestLsearchCommand:
    """Test the 'litdb lsearch' command."""

    @pytest.mark.unit
    @patch("litdb.commands.search.llm_oa_search")
    def test_lsearch_basic(self, mock_llm_search):
        """Test basic LLM-enhanced search."""
        mock_llm_search.return_value = [
            (
                (0.95, "result1"),
                {"title": "Paper 1", "publication_year": 2023, "id": "W123"},
            ),
            (
                (0.85, "result2"),
                {"title": "Paper 2", "publication_year": 2022, "id": "W456"},
            ),
        ]

        runner = CliRunner()
        result = runner.invoke(cli, ["lsearch", "machine learning"])

        assert result.exit_code == 0
        mock_llm_search.assert_called_once()

    @pytest.mark.unit
    def test_lsearch_command_exists(self):
        """Test that lsearch command is properly registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["lsearch", "--help"])

        assert result.exit_code == 0
        assert "LLM" in result.output or "llm" in result.output.lower()


class TestSimilarCommand:
    """Test the 'litdb similar' command."""

    @pytest.mark.unit
    @patch("litdb.commands.search.get_db")
    def test_similar_basic(self, mock_get_db):
        """Test finding similar sources."""
        mock_db = MagicMock()
        mock_cursor1 = MagicMock()
        mock_cursor1.fetchone.return_value = (b"\x00\x01\x02\x03",)

        mock_cursor2 = MagicMock()
        mock_cursor2.fetchall.return_value = [
            ("source1.pdf", "text 1", "{}"),
            ("source2.pdf", "text 2", "{}"),
        ]

        mock_get_db.return_value = mock_db
        mock_db.execute.side_effect = [mock_cursor1, mock_cursor2]

        runner = CliRunner()
        result = runner.invoke(cli, ["similar", "source1.pdf", "-n", "3"])

        assert result.exit_code == 0
        assert mock_db.execute.call_count == 2

    @pytest.mark.unit
    @patch("litdb.commands.search.get_db")
    def test_similar_with_emacs_format(self, mock_get_db):
        """Test similar with emacs output format."""
        mock_db = MagicMock()
        mock_cursor1 = MagicMock()
        mock_cursor1.fetchone.return_value = (b"\x00\x01\x02\x03",)

        mock_cursor2 = MagicMock()
        mock_cursor2.fetchall.return_value = [
            ("source1.pdf", "text 1", "{}"),
        ]

        mock_get_db.return_value = mock_db
        mock_db.execute.side_effect = [mock_cursor1, mock_cursor2]

        runner = CliRunner()
        result = runner.invoke(cli, ["similar", "source1.pdf", "--emacs"])

        assert result.exit_code == 0
        assert "(" in result.output  # Emacs format uses lisp syntax

    @pytest.mark.unit
    def test_similar_command_exists(self):
        """Test that similar command is properly registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["similar", "--help"])

        assert result.exit_code == 0
        assert "similar" in result.output.lower()


class TestImageSearchCommand:
    """Test the 'litdb image-search' command."""

    @pytest.mark.unit
    @patch("litdb.commands.search.image_query")
    def test_image_search_basic(self, mock_image_query):
        """Test basic image search."""
        runner = CliRunner()
        result = runner.invoke(cli, ["image-search", "test query"])

        assert result.exit_code == 0
        mock_image_query.assert_called_once_with("test query", False, 1)

    @pytest.mark.unit
    @patch("litdb.commands.search.image_query")
    def test_image_search_with_clipboard(self, mock_image_query):
        """Test image search with clipboard flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["image-search", "test", "--clipboard"])

        assert result.exit_code == 0
        mock_image_query.assert_called_once_with("test", True, 1)

    @pytest.mark.unit
    def test_image_search_command_exists(self):
        """Test that image-search command is properly registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["image-search", "--help"])

        assert result.exit_code == 0


class TestScreenshotCommand:
    """Test the 'litdb screenshot' command."""

    @pytest.mark.unit
    def test_screenshot_command_exists(self):
        """Test that screenshot command is properly registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["screenshot", "--help"])

        assert result.exit_code == 0
        assert "screenshot" in result.output.lower()

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires clipboard and OCR dependencies")
    def test_screenshot_with_clipboard_image(self):
        """Test screenshot search with actual clipboard image."""
        # TODO: Mock ImageGrab and pytesseract
        pass
