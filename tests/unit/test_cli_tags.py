"""Unit tests for CLI tag management commands.

These tests cover tag functionality that will be moved to
commands/tags.py during refactoring.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from litdb.cli import cli


def run(*args):
    return CliRunner().invoke(cli, list(args))


def tags_of(db, source):
    return {
        tag
        for (tag,) in db.execute(
            """select tags.tag from tags
            join source_tag on source_tag.tag_id = tags.rowid
            join sources on source_tag.source_id = sources.rowid
            where sources.source = ?""",
            (source,),
        ).fetchall()
    }


@pytest.fixture
def db(real_db):
    from litdb.db import add_source

    add_source("test.pdf", "some text")
    add_source("other.pdf", "more text")
    return real_db


class TestAddTagCommand:
    """Test the 'litdb add-tag' command."""

    @pytest.mark.unit
    def test_add_tag_single_source_single_tag(self, db):
        result = run("add-tag", "test.pdf", "-t", "important")
        assert result.exit_code == 0
        assert "Tagged test.pdf with important" in result.output
        assert tags_of(db, "test.pdf") == {"important"}

    @pytest.mark.unit
    def test_add_multiple_tags_to_multiple_sources(self, db):
        result = run("add-tag", "test.pdf", "other.pdf", "-t", "a", "-t", "b")
        assert result.exit_code == 0
        assert tags_of(db, "test.pdf") == {"a", "b"}
        assert tags_of(db, "other.pdf") == {"a", "b"}

    @pytest.mark.unit
    def test_add_tag_twice_does_not_duplicate(self, db):
        run("add-tag", "test.pdf", "-t", "a")
        run("add-tag", "test.pdf", "-t", "a")
        (n,) = db.execute("select count(*) from source_tag").fetchone()
        assert n == 1

    @pytest.mark.unit
    def test_add_tag_unknown_source(self, db):
        result = run("add-tag", "missing.pdf", "-t", "a")
        assert result.exit_code == 0
        assert "missing.pdf is not in the database" in result.output
        (n,) = db.execute("select count(*) from tags").fetchone()
        assert n == 0


class TestRmTagCommand:
    """Test the 'litdb rm-tag' command."""

    @pytest.mark.unit
    def test_rm_tag(self, db):
        run("add-tag", "test.pdf", "-t", "a", "-t", "b")
        result = run("rm-tag", "test.pdf", "-t", "a")
        assert result.exit_code == 0
        assert "Deleted 1 rows (a from test.pdf)" in result.output
        assert tags_of(db, "test.pdf") == {"b"}

    @pytest.mark.unit
    def test_rm_unknown_tag_or_source(self, db):
        assert "Deleted 0 rows" in run("rm-tag", "test.pdf", "-t", "nope").output
        assert "Deleted 0 rows" in run("rm-tag", "missing.pdf", "-t", "a").output


class TestDeleteTagCommand:
    """Test the 'litdb delete-tag' command."""

    @pytest.mark.unit
    def test_delete_tag_removes_it_from_sources(self, db):
        run("add-tag", "test.pdf", "other.pdf", "-t", "a", "-t", "b")
        result = run("delete-tag", "a")
        assert result.exit_code == 0
        assert "Deleted 1 rows (a)" in result.output
        assert tags_of(db, "test.pdf") == {"b"}
        (n,) = db.execute("select count(*) from source_tag").fetchone()
        assert n == 2


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
