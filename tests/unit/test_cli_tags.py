"""Unit tests for CLI tag management commands.

These tests cover tag functionality that will be moved to
commands/tags.py during refactoring.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from litdb.cli import cli


class TestAddTagCommand:
    """Test the 'litdb add-tag' command."""

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_add_tag_single_source_single_tag(self, mock_db):
        """Test adding a single tag to a single source."""
        # Mock source lookup
        mock_cursor_source = MagicMock()
        mock_cursor_source.fetchone.return_value = (1,)

        # Mock tag lookup (tag doesn't exist)
        mock_cursor_tag = MagicMock()
        mock_cursor_tag.fetchone.return_value = None
        mock_cursor_tag.lastrowid = 10

        # Setup execute to return different cursors
        mock_db.execute.side_effect = [
            mock_cursor_source,  # source lookup
            mock_cursor_tag,  # tag lookup
            mock_cursor_tag,  # insert tag
            MagicMock(),  # insert source_tag
        ]

        runner = CliRunner()
        result = runner.invoke(cli, ["add-tag", "test.pdf", "-t", "important"])

        assert result.exit_code == 0
        assert "Tagged test.pdf with important" in result.output
        assert mock_db.commit.call_count >= 2

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_add_tag_existing_tag(self, mock_db):
        """Test adding an existing tag to a source."""
        mock_cursor_source = MagicMock()
        mock_cursor_source.fetchone.return_value = (1,)

        mock_cursor_tag = MagicMock()
        mock_cursor_tag.fetchone.return_value = (10,)  # Tag exists

        mock_db.execute.side_effect = [
            mock_cursor_source,  # source lookup
            mock_cursor_tag,  # tag lookup
            MagicMock(),  # insert source_tag
        ]

        runner = CliRunner()
        result = runner.invoke(cli, ["add-tag", "test.pdf", "-t", "existing"])

        assert result.exit_code == 0
        assert "Tagged test.pdf with existing" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_add_multiple_tags(self, mock_db):
        """Test adding multiple tags to a source."""
        mock_cursor_source = MagicMock()
        mock_cursor_source.fetchone.return_value = (1,)

        mock_cursor_tag = MagicMock()
        mock_cursor_tag.fetchone.return_value = None
        mock_cursor_tag.lastrowid = 10

        # Need more execute calls for multiple tags
        mock_db.execute.side_effect = [
            mock_cursor_source,  # source lookup
            mock_cursor_tag,  # tag1 lookup
            mock_cursor_tag,  # insert tag1
            MagicMock(),  # insert source_tag1
            mock_cursor_tag,  # tag2 lookup
            mock_cursor_tag,  # insert tag2
            MagicMock(),  # insert source_tag2
        ]

        runner = CliRunner()
        result = runner.invoke(cli, ["add-tag", "test.pdf", "-t", "tag1", "-t", "tag2"])

        assert result.exit_code == 0
        assert "Tagged test.pdf with tag1" in result.output
        assert "Tagged test.pdf with tag2" in result.output


class TestRmTagCommand:
    """Test the 'litdb rm-tag' command."""

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_rm_tag_single_tag(self, mock_db):
        """Test removing a single tag from a source."""
        mock_cursor_source = MagicMock()
        mock_cursor_source.fetchone.return_value = (1,)

        mock_cursor_tag = MagicMock()
        mock_cursor_tag.fetchone.return_value = (10,)

        mock_cursor_delete = MagicMock()
        mock_cursor_delete.rowcount = 1

        mock_db.execute.side_effect = [
            mock_cursor_source,  # source lookup
            mock_cursor_tag,  # tag lookup
            mock_cursor_delete,  # delete from source_tag
        ]

        runner = CliRunner()
        result = runner.invoke(cli, ["rm-tag", "test.pdf", "-t", "old-tag"])

        assert result.exit_code == 0
        assert "Deleted 1 rows (old-tag from test.pdf)" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_rm_multiple_tags(self, mock_db):
        """Test removing multiple tags from a source."""
        mock_cursor_source = MagicMock()
        mock_cursor_source.fetchone.return_value = (1,)

        mock_cursor_tag = MagicMock()
        mock_cursor_tag.fetchone.return_value = (10,)

        mock_cursor_delete = MagicMock()
        mock_cursor_delete.rowcount = 1

        mock_db.execute.side_effect = [
            mock_cursor_source,  # source lookup
            mock_cursor_tag,  # tag1 lookup
            mock_cursor_delete,  # delete tag1
            mock_cursor_tag,  # tag2 lookup
            mock_cursor_delete,  # delete tag2
        ]

        runner = CliRunner()
        result = runner.invoke(cli, ["rm-tag", "test.pdf", "-t", "tag1", "-t", "tag2"])

        assert result.exit_code == 0
        assert "Deleted 1 rows (tag1 from test.pdf)" in result.output
        assert "Deleted 1 rows (tag2 from test.pdf)" in result.output


class TestDeleteTagCommand:
    """Test the 'litdb delete-tag' command."""

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_delete_tag_single(self, mock_db):
        """Test deleting a single tag."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["delete-tag", "obsolete"])

        assert result.exit_code == 0
        assert "Deleted 1 rows (obsolete)" in result.output
        mock_db.execute.assert_called_once_with(
            "delete from tags where tag = ?", ("obsolete",)
        )
        mock_db.commit.assert_called_once()

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_delete_multiple_tags(self, mock_db):
        """Test deleting multiple tags."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["delete-tag", "tag1", "tag2"])

        assert result.exit_code == 0
        assert "Deleted 1 rows (tag1)" in result.output
        assert "Deleted 1 rows (tag2)" in result.output
        assert mock_db.execute.call_count == 2


class TestShowTagCommand:
    """Test the 'litdb show-tag' command."""

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_show_tag_basic(self, mock_db):
        """Test showing entries with a tag."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("test.pdf", "Test content", '{"citation": "Test citation"}'),
        ]
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["show-tag", "important"])

        assert result.exit_code == 0
        assert "test.pdf" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_show_tag_with_format(self, mock_db):
        """Test showing entries with custom format."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("test.pdf", "Test content", '{"citation": "Test citation"}'),
        ]
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["show-tag", "important", "-f", "{{ source }}"])

        assert result.exit_code == 0
        assert "test.pdf" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_show_tag_no_results(self, mock_db):
        """Test showing a tag with no entries."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["show-tag", "nonexistent"])

        assert result.exit_code == 0
        # No entries should be shown


class TestListTagsCommand:
    """Test the 'litdb list-tags' command."""

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_list_tags_with_tags(self, mock_db):
        """Test listing all tags."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("tag1",), ("tag2",), ("tag3",)]
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["list-tags"])

        assert result.exit_code == 0
        assert "The following tags are defined" in result.output
        assert "tag1" in result.output
        assert "tag2" in result.output
        assert "tag3" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.tags._db")
    def test_list_tags_empty(self, mock_db):
        """Test listing tags when none exist."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["list-tags"])

        assert result.exit_code == 0
        assert "The following tags are defined" in result.output
