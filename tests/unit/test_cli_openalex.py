"""Unit tests for CLI OpenAlex commands.

These tests cover OpenAlex functionality that will be moved to
commands/openalex_commands.py during refactoring.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from litdb.cli import cli


class TestOpenAlexCommand:
    """Test the 'litdb openalex' command."""

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands.requests")
    @patch("litdb.commands.openalex_commands.get_config")
    def test_openalex_basic_search(self, mock_config, mock_requests):
        """Test basic OpenAlex search."""
        mock_config.return_value = {"openalex": {"email": "test@example.com"}}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test Paper",
                    "publication_year": 2025,
                    "id": "https://openalex.org/W123",
                }
            ]
        }
        mock_requests.get.return_value = mock_response

        runner = CliRunner()
        result = runner.invoke(cli, ["openalex", "circular polymer"])

        assert result.exit_code == 0
        assert "Test Paper" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires network and OpenAlex API")
    def test_openalex_integration(self):
        """Test OpenAlex command with actual API."""
        runner = CliRunner()
        result = runner.invoke(cli, ["openalex", "machine learning"])

        assert result.exit_code == 0


class TestAuthorSearchCommand:
    """Test the 'litdb author-search' command."""

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands.get_data")
    def test_author_search_basic(self, mock_get_data):
        """Test searching for an author."""
        mock_get_data.return_value = {
            "results": [
                {
                    "display_name": "John Kitchin",
                    "hint": "Carnegie Mellon University",
                    "external_id": "https://orcid.org/0000-0003-2625-9232",
                }
            ]
        }

        runner = CliRunner()
        result = runner.invoke(cli, ["author-search", "John", "Kitchin"])

        assert result.exit_code == 0
        assert "John Kitchin" in result.output
        assert "Carnegie Mellon" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires network and OpenAlex API")
    def test_author_search_integration(self):
        """Test author search with actual API."""
        runner = CliRunner()
        result = runner.invoke(cli, ["author-search", "John", "Kitchin"])

        assert result.exit_code == 0


class TestFollowCommand:
    """Test the 'litdb follow' command."""

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands.get_data")
    @patch("litdb.commands.openalex_commands.add_author")
    @patch("litdb.commands.openalex_commands._db")
    @patch("litdb.commands.openalex_commands.datetime")
    def test_follow_orcid(self, mock_datetime, mock_db, mock_add_author, mock_get_data):
        """Test following an ORCID."""
        mock_date = MagicMock()
        mock_date.today.return_value.strftime.return_value = "2025-01-01"
        mock_datetime.date = mock_date

        mock_get_data.return_value = {"display_name": "John Kitchin"}

        runner = CliRunner()
        result = runner.invoke(cli, ["follow", "0000-0003-2625-9232"])

        assert result.exit_code == 0
        mock_add_author.assert_called_once()
        mock_db.execute.assert_called()
        mock_db.commit.assert_called()

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands._db")
    def test_follow_remove(self, mock_db):
        """Test removing a followed ORCID."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["follow", "0000-0003-2625-9232", "--remove"])

        assert result.exit_code == 0
        assert "removed" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_follow_integration(self):
        """Test follow command with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["follow", "0000-0003-2625-9232"])

        assert result.exit_code == 0


class TestWatchCommand:
    """Test the 'litdb watch' command."""

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands.get_data")
    @patch("litdb.commands.openalex_commands._db")
    def test_watch_query(self, mock_db, mock_get_data):
        """Test creating a watch on a query."""
        mock_get_data.return_value = {"results": [{"id": "W123"}]}

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "author.id:A123"])

        assert result.exit_code == 0
        assert "Watching" in result.output or "Added" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands._db")
    def test_watch_remove(self, mock_db):
        """Test removing a watch."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "author.id:A123", "--remove"])

        assert result.exit_code == 0
        assert "removed" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database and network")
    def test_watch_integration(self):
        """Test watch command with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "author.id:A123"])

        assert result.exit_code == 0


class TestCitingCommand:
    """Test the 'litdb citing' command."""

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands.get_data")
    @patch("litdb.commands.openalex_commands._db")
    def test_citing_doi(self, mock_db, mock_get_data):
        """Test creating a citing watch for a DOI."""
        mock_get_data.return_value = {"results": [{"id": "https://openalex.org/W123"}]}

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["citing", "10.1234/test"])

        assert result.exit_code == 0
        assert "Added" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands.get_data")
    @patch("litdb.commands.openalex_commands._db")
    def test_citing_remove(self, mock_db, mock_get_data):
        """Test removing a citing watch."""
        mock_get_data.return_value = {"results": [{"id": "https://openalex.org/W123"}]}

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["citing", "10.1234/test", "--remove"])

        assert result.exit_code == 0
        assert "Deleted" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database and network")
    def test_citing_integration(self):
        """Test citing command with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["citing", "10.1234/test"])

        assert result.exit_code == 0


class TestRelatedCommand:
    """Test the 'litdb related' command."""

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands.get_data")
    @patch("litdb.commands.openalex_commands._db")
    def test_related_doi(self, mock_db, mock_get_data):
        """Test creating a related watch for a DOI."""
        mock_get_data.return_value = {"results": [{"id": "https://openalex.org/W123"}]}

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["related", "10.1234/test"])

        assert result.exit_code == 0
        assert "Added" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands.get_data")
    @patch("litdb.commands.openalex_commands._db")
    def test_related_remove(self, mock_db, mock_get_data):
        """Test removing a related watch."""
        mock_get_data.return_value = {"results": [{"id": "https://openalex.org/W123"}]}

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["related", "10.1234/test", "--remove"])

        assert result.exit_code == 0
        assert "Deleted" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database and network")
    def test_related_integration(self):
        """Test related command with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["related", "10.1234/test"])

        assert result.exit_code == 0


class TestUnpaywallCommand:
    """Test the 'litdb unpaywall' command."""

    @pytest.mark.unit
    @patch("litdb.commands.openalex_commands.requests")
    @patch("litdb.commands.openalex_commands.get_config")
    def test_unpaywall_basic(self, mock_config, mock_requests):
        """Test unpaywall command."""
        mock_config.return_value = {"openalex": {"email": "test@example.com"}}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "best_oa_location": {"url_for_pdf": "https://example.com/paper.pdf"}
        }
        mock_requests.get.return_value = mock_response

        runner = CliRunner()
        result = runner.invoke(cli, ["unpaywall", "10.1234/test"])

        assert result.exit_code == 0
        assert "example.com" in result.output or result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires network and Unpaywall API")
    def test_unpaywall_integration(self):
        """Test unpaywall command with actual API."""
        runner = CliRunner()
        result = runner.invoke(cli, ["unpaywall", "10.1038/nature12373"])

        assert result.exit_code == 0
