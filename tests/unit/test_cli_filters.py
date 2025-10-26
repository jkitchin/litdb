"""Unit tests for CLI filter management commands.

These tests cover filter functionality that will be moved to
commands/filters.py during refactoring.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from litdb.cli import cli


class TestAddFilterCommand:
    """Test the 'litdb add-filter' command."""

    @pytest.mark.unit
    @patch("litdb.commands.filters._db")
    def test_add_filter_basic(self, mock_db):
        """Test adding a filter without description."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add-filter", "author.id:A12345"])

        assert result.exit_code == 0
        mock_db.execute.assert_called_once_with(
            "insert into queries(filter, description) values (?, ?)",
            ("author.id:A12345", None),
        )
        mock_db.commit.assert_called_once()

    @pytest.mark.unit
    @patch("litdb.commands.filters._db")
    def test_add_filter_with_description(self, mock_db):
        """Test adding a filter with description."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add-filter", "author.id:A12345", "-d", "My favorite author"],
        )

        assert result.exit_code == 0
        mock_db.execute.assert_called_once_with(
            "insert into queries(filter, description) values (?, ?)",
            ("author.id:A12345", "My favorite author"),
        )
        mock_db.commit.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_add_filter_integration(self):
        """Test adding a filter with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add-filter", "test-filter", "-d", "Test"])

        assert result.exit_code == 0


class TestRmFilterCommand:
    """Test the 'litdb rm-filter' command."""

    @pytest.mark.unit
    @patch("litdb.commands.filters._db")
    def test_rm_filter_basic(self, mock_db):
        """Test removing a filter."""
        runner = CliRunner()
        result = runner.invoke(cli, ["rm-filter", "author.id:A12345"])

        assert result.exit_code == 0
        mock_db.execute.assert_called_once_with(
            "delete from queries where filter = ?", ("author.id:A12345",)
        )
        mock_db.commit.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_rm_filter_integration(self):
        """Test removing a filter with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["rm-filter", "test-filter"])

        assert result.exit_code == 0


class TestUpdateFiltersCommand:
    """Test the 'litdb update-filters' command."""

    @pytest.mark.unit
    @patch("litdb.commands.filters.update_filter")
    @patch("litdb.commands.filters._db")
    @patch("litdb.commands.filters.os")
    def test_update_filters_basic(self, mock_os, mock_db, mock_update_filter):
        """Test updating filters."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("filter1", "Description 1", "2025-01-01"),
        ]
        mock_db.execute.return_value = mock_cursor
        mock_update_filter.return_value = []  # No new results

        runner = CliRunner()
        result = runner.invoke(cli, ["update-filters", "--silent"])

        assert result.exit_code == 0
        mock_db.execute.assert_called_once_with(
            "select filter, description, last_updated from queries"
        )
        mock_update_filter.assert_called_once_with("filter1", "2025-01-01", True)

    @pytest.mark.unit
    @patch("litdb.commands.filters.update_filter")
    @patch("litdb.commands.filters._db")
    @patch("litdb.commands.filters.os")
    def test_update_filters_with_results(self, mock_os, mock_db, mock_update_filter):
        """Test updating filters with new results."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("filter1", "Description 1", "2025-01-01"),
        ]
        mock_db.execute.return_value = mock_cursor
        mock_update_filter.return_value = [
            ("source1", "text1", '{"display_name": "Paper 1"}'),
        ]

        runner = CliRunner()
        result = runner.invoke(cli, ["update-filters", "--silent"])

        assert result.exit_code == 0
        assert "Description 1" in result.output or result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database and network")
    def test_update_filters_integration(self):
        """Test updating filters with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["update-filters", "--silent"])

        assert result.exit_code == 0


class TestListFiltersCommand:
    """Test the 'litdb list-filters' command."""

    @pytest.mark.unit
    @patch("litdb.commands.filters._db")
    def test_list_filters_empty(self, mock_db):
        """Test listing filters when none exist."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["list-filters"])

        assert result.exit_code == 0
        mock_db.execute.assert_called_once()

    @pytest.mark.unit
    @patch("litdb.commands.filters._db")
    def test_list_filters_with_data(self, mock_db):
        """Test listing filters with data."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (1, "author.id:A12345", "My favorite author", "2025-01-01"),
            (2, "institution.id:I67890", "My institution", "2025-01-02"),
        ]
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["list-filters"])

        assert result.exit_code == 0
        mock_db.execute.assert_called_once_with(
            """select rowid, filter, description, last_updated
    from queries"""
        )

    @pytest.mark.unit
    @patch("litdb.commands.filters._db")
    def test_list_filters_custom_format(self, mock_db):
        """Test listing filters with custom format."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (1, "filter1", "Description 1", "2025-01-01"),
        ]
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["list-filters", "-f", "{{ f }}"])

        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_list_filters_integration(self):
        """Test listing filters with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["list-filters"])

        assert result.exit_code == 0
