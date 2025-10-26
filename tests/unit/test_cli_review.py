"""Unit tests for CLI review commands.

These tests cover review functionality that will be moved to
commands/review.py during refactoring.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from litdb.cli import cli


class TestReviewCommand:
    """Test the 'litdb review' command."""

    @pytest.mark.unit
    @patch("litdb.commands.review._db")
    @patch("litdb.commands.review.dateparser")
    def test_review_default_timeframe(self, mock_dateparser, mock_db):
        """Test review with default timeframe."""
        mock_date = MagicMock()
        mock_date.strftime.return_value = "2025-10-19"
        mock_dateparser.parse.return_value = mock_date

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (
                "test.pdf",
                "Test content",
                '{"display_name": "Test Paper", "id": "test-id"}',
            ),
        ]
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["review"])

        assert result.exit_code == 0
        mock_dateparser.parse.assert_called_once_with("1 week ago")
        assert "Test Paper" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.review._db")
    @patch("litdb.commands.review.dateparser")
    def test_review_custom_timeframe(self, mock_dateparser, mock_db):
        """Test review with custom timeframe."""
        mock_date = MagicMock()
        mock_date.strftime.return_value = "2025-10-01"
        mock_dateparser.parse.return_value = mock_date

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["review", "-s", "1 month ago"])

        assert result.exit_code == 0
        mock_dateparser.parse.assert_called_once_with("1 month ago")

    @pytest.mark.unit
    @patch("litdb.commands.review._db")
    @patch("litdb.commands.review.dateparser")
    def test_review_with_custom_format(self, mock_dateparser, mock_db):
        """Test review with custom jinja template."""
        mock_date = MagicMock()
        mock_date.strftime.return_value = "2025-10-19"
        mock_dateparser.parse.return_value = mock_date

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("test.pdf", "Test content", '{"display_name": "Test Paper"}'),
        ]
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(
            cli, ["review", "-f", "{{ source }}: {{ extra['display_name'] }}"]
        )

        assert result.exit_code == 0
        assert "test.pdf: Test Paper" in result.output

    @pytest.mark.unit
    @patch("litdb.commands.review._db")
    @patch("litdb.commands.review.dateparser")
    def test_review_no_results(self, mock_dateparser, mock_db):
        """Test review when no entries found."""
        mock_date = MagicMock()
        mock_date.strftime.return_value = "2025-10-19"
        mock_dateparser.parse.return_value = mock_date

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.execute.return_value = mock_cursor

        runner = CliRunner()
        result = runner.invoke(cli, ["review"])

        assert result.exit_code == 0
        # No output expected when no results

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_review_integration(self):
        """Test review command with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["review", "-s", "1 year ago"])

        assert result.exit_code == 0


class TestSummaryCommand:
    """Test the 'litdb summary' command."""

    @pytest.mark.unit
    @patch("litdb.commands.review.generate_summary")
    def test_summary_default_timeframe(self, mock_generate):
        """Test summary with default timeframe."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary"])

        assert result.exit_code == 0
        mock_generate.assert_called_once_with(
            since="1 week", output_file=None, model=None
        )

    @pytest.mark.unit
    @patch("litdb.commands.review.generate_summary")
    def test_summary_custom_timeframe(self, mock_generate):
        """Test summary with custom timeframe."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "-s", "2 weeks"])

        assert result.exit_code == 0
        mock_generate.assert_called_once_with(
            since="2 weeks", output_file=None, model=None
        )

    @pytest.mark.unit
    @patch("litdb.commands.review.generate_summary")
    def test_summary_with_output_file(self, mock_generate):
        """Test summary with output file."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "-o", "newsletter.org"])

        assert result.exit_code == 0
        mock_generate.assert_called_once_with(
            since="1 week", output_file="newsletter.org", model=None
        )

    @pytest.mark.unit
    @patch("litdb.commands.review.generate_summary")
    def test_summary_with_custom_model(self, mock_generate):
        """Test summary with custom model."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "--model", "gpt-4"])

        assert result.exit_code == 0
        mock_generate.assert_called_once_with(
            since="1 week", output_file=None, model="gpt-4"
        )

    @pytest.mark.unit
    @patch("litdb.commands.review.generate_summary")
    def test_summary_all_options(self, mock_generate):
        """Test summary with all options."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["summary", "-s", "1 month", "-o", "monthly.org", "--model", "claude-3"],
        )

        assert result.exit_code == 0
        mock_generate.assert_called_once_with(
            since="1 month", output_file="monthly.org", model="claude-3"
        )

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database and LLM")
    def test_summary_integration(self):
        """Test summary command with actual database."""
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "-s", "1 year ago"])

        assert result.exit_code == 0
