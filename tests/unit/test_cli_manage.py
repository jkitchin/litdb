"""Unit tests for CLI management commands (add, remove, index).

These tests cover the commands that will be moved to commands/manage.py
during refactoring.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock, mock_open

from litdb.cli import cli


class TestAddCommand:
    """Test the 'litdb add' command."""

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_work")
    def test_add_doi_basic(self, mock_add_work):
        """Test adding a work by DOI."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "10.1234/test"])

        assert result.exit_code == 0
        mock_add_work.assert_called_once_with(
            "https://doi.org/10.1234/test", False, False, False, False, None, None, None
        )

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_work")
    def test_add_doi_with_full_url(self, mock_add_work):
        """Test adding a work with full DOI URL."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "https://doi.org/10.1234/test"])

        assert result.exit_code == 0
        mock_add_work.assert_called_once_with(
            "https://doi.org/10.1234/test", False, False, False, False, None, None, None
        )

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_work")
    def test_add_doi_with_references(self, mock_add_work):
        """Test adding a work with --references flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "10.1234/test", "--references"])

        assert result.exit_code == 0
        mock_add_work.assert_called_once_with(
            "https://doi.org/10.1234/test", True, False, False, False, None, None, None
        )

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_work")
    def test_add_doi_with_citing(self, mock_add_work):
        """Test adding a work with --citing flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "10.1234/test", "--citing"])

        assert result.exit_code == 0
        mock_add_work.assert_called_once_with(
            "https://doi.org/10.1234/test", False, True, False, False, None, None, None
        )

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_work")
    def test_add_doi_with_related(self, mock_add_work):
        """Test adding a work with --related flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "10.1234/test", "--related"])

        assert result.exit_code == 0
        mock_add_work.assert_called_once_with(
            "https://doi.org/10.1234/test", False, False, True, False, None, None, None
        )

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_work")
    def test_add_doi_with_all_flag(self, mock_add_work):
        """Test adding a work with --all flag (references, citing, related)."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "10.1234/test", "--all"])

        assert result.exit_code == 0
        mock_add_work.assert_called_once_with(
            "https://doi.org/10.1234/test", True, True, True, False, None, None, None
        )

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_work")
    def test_add_multiple_dois(self, mock_add_work):
        """Test adding multiple DOIs at once."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", "10.1234/test1", "10.1234/test2", "10.1234/test3"]
        )

        assert result.exit_code == 0
        assert mock_add_work.call_count == 3

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_author")
    def test_add_orcid(self, mock_add_author):
        """Test adding works from an ORCID."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "https://orcid.org/0000-0001-2345-6789"])

        assert result.exit_code == 0
        mock_add_author.assert_called_once_with("https://orcid.org/0000-0001-2345-6789")

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_author")
    def test_add_openalex_author(self, mock_add_author):
        """Test adding works from an OpenAlex author ID."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "https://openalex.org/A1234567890"])

        assert result.exit_code == 0
        mock_add_author.assert_called_once_with("https://openalex.org/A1234567890")

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_bibtex")
    def test_add_bibtex_file(self, mock_add_bibtex):
        """Test adding from a bibtex file."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "references.bib"])

        assert result.exit_code == 0
        mock_add_bibtex.assert_called_once_with("references.bib")

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_pdf")
    @patch("os.path.abspath")
    def test_add_pdf_file(self, mock_abspath, mock_add_pdf):
        """Test adding a PDF file."""
        mock_abspath.return_value = "/absolute/path/paper.pdf"
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "paper.pdf"])

        assert result.exit_code == 0
        mock_add_pdf.assert_called_once_with("/absolute/path/paper.pdf")

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_source")
    @patch("litdb.commands.manage.Document")
    @patch("os.path.abspath")
    def test_add_docx_file(self, mock_abspath, mock_document, mock_add_source):
        """Test adding a DOCX file."""
        mock_abspath.return_value = "/absolute/path/document.docx"
        mock_doc = MagicMock()
        mock_para = MagicMock()
        mock_para.text = "Test paragraph"
        mock_doc.paragraphs = [mock_para]
        mock_document.return_value = mock_doc

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "document.docx"])

        assert result.exit_code == 0
        mock_add_source.assert_called_once_with(
            "/absolute/path/document.docx", "Test paragraph"
        )

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_source")
    @patch("litdb.commands.manage.get_youtube_doc")
    def test_add_youtube_url(self, mock_youtube, mock_add_source):
        """Test adding a YouTube video."""
        mock_youtube.return_value = ("Transcript text", "Video title")
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "https://youtube.com/watch?v=dQw4w9WgXcQ"])

        assert result.exit_code == 0
        mock_youtube.assert_called_once()
        mock_add_source.assert_called_once_with(
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "Transcript text",
            {"citation": "Video title"},
        )

    @pytest.mark.unit
    @patch("litdb.commands.manage.add_source")
    @patch("builtins.open", new_callable=mock_open, read_data="Plain text content")
    @patch("os.path.abspath")
    def test_add_text_file(self, mock_abspath, mock_file, mock_add_source):
        """Test adding a plain text file."""
        mock_abspath.return_value = "/absolute/path/notes.txt"
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "notes.txt"])

        assert result.exit_code == 0
        mock_add_source.assert_called_once_with(
            "/absolute/path/notes.txt", "Plain text content"
        )


class TestRemoveCommand:
    """Test the 'litdb remove' command."""

    @pytest.mark.unit
    def test_remove_requires_db(self):
        """Test that remove command needs database initialization."""
        runner = CliRunner()
        # If db is None, this will fail - this is expected behavior
        # We're just testing the command structure exists
        result = runner.invoke(cli, ["remove", "--help"])
        assert result.exit_code == 0
        assert "Remove sources from litdb" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database with data")
    def test_remove_single_source(self, test_db):
        """Test removing a single source."""
        # TODO: Set up test database with known entry
        # TODO: Remove it
        # TODO: Verify it's gone
        pass

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_remove_multiple_sources(self, test_db):
        """Test removing multiple sources at once."""
        # TODO: Test with multiple sources
        pass

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_remove_nonexistent_source(self, test_db):
        """Test removing a source that doesn't exist."""
        # Should complete without error even if source doesn't exist
        pass


class TestIndexCommand:
    """Test the 'litdb index' command."""

    @pytest.mark.unit
    def test_index_command_exists(self):
        """Test that index command exists and has proper structure."""
        runner = CliRunner()
        result = runner.invoke(cli, ["index", "--help"])

        assert result.exit_code == 0
        assert "Index the directories" in result.output
        assert "SOURCES" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database and file fixtures")
    def test_index_directory_basic(self, tmp_path, test_db):
        """Test indexing a directory with supported files."""
        # TODO: Create test directory with PDF, DOCX, etc.
        # TODO: Run index command
        # TODO: Verify files were added to database
        # TODO: Verify directories table was updated
        pass

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_index_skips_existing_files(self, tmp_path, test_db):
        """Test that index skips files already in database."""
        # TODO: Add a file to db first
        # TODO: Run index on directory containing that file
        # TODO: Verify it wasn't added twice
        pass

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_index_updates_directory_timestamp(self, tmp_path, test_db):
        """Test that index updates the last_updated timestamp."""
        # TODO: Index a directory
        # TODO: Check directories table has correct timestamp
        # TODO: Index again
        # TODO: Verify timestamp was updated
        pass

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_index_recursive(self, tmp_path, test_db):
        """Test that index recursively processes subdirectories."""
        # TODO: Create nested directory structure
        # TODO: Run index on parent
        # TODO: Verify files from subdirectories were added
        pass


class TestReindexCommand:
    """Test the 'litdb reindex' command."""

    @pytest.mark.unit
    def test_reindex_command_exists(self):
        """Test that reindex command exists."""
        runner = CliRunner()
        result = runner.invoke(cli, ["reindex", "--help"])

        assert result.exit_code == 0
        assert "Reindex saved directories" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_reindex_all_directories(self, test_db):
        """Test reindexing all saved directories."""
        # TODO: Add directories to directories table
        # TODO: Run reindex
        # TODO: Verify all were reindexed
        pass


class TestUpdateEmbeddingsCommand:
    """Test the 'litdb update-embeddings' command."""

    @pytest.mark.unit
    def test_update_embeddings_command_exists(self):
        """Test that update-embeddings command exists."""
        runner = CliRunner()
        result = runner.invoke(cli, ["update-embeddings", "--help"])

        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database and embedding model")
    def test_update_embeddings_basic(self, test_db):
        """Test updating embeddings for sources."""
        # TODO: Add sources without embeddings
        # TODO: Run update-embeddings
        # TODO: Verify embeddings were generated
        pass
