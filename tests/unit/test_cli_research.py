"""Unit tests for CLI research commands.

These tests cover research functionality that will be moved to
commands/research_commands.py during refactoring.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from litdb.cli import cli


class TestFhresearchCommand:
    """Test the 'litdb fhresearch' command."""

    @pytest.mark.unit
    @patch("litdb.commands.research_commands.FutureHouseClient")
    @patch("litdb.commands.research_commands.os")
    def test_fhresearch_basic(self, mock_os, mock_client):
        """Test basic FutureHouse research."""
        mock_os.environ = {"FUTURE_HOUSE_API_KEY": "test-key"}

        mock_instance = MagicMock()
        mock_task_response = MagicMock()
        mock_task_response.formatted_answer = "Research result"
        mock_instance.run_tasks_until_done.return_value = [mock_task_response]
        mock_client.return_value = mock_instance

        runner = CliRunner()
        result = runner.invoke(cli, ["fhresearch", "machine learning"])

        assert result.exit_code == 0
        assert "Research result" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires FutureHouse API key and network")
    def test_fhresearch_integration(self):
        """Test FutureHouse research with actual API."""
        runner = CliRunner()
        result = runner.invoke(cli, ["fhresearch", "machine learning", "-t", "crow"])

        assert result.exit_code == 0


class TestResearchCommand:
    """Test the 'litdb research' command."""

    @pytest.mark.unit
    @patch("litdb.commands.research_commands.deep_research")
    @patch("litdb.commands.research_commands.Console")
    def test_research_basic(self, mock_console, mock_deep_research):
        """Test basic research command."""
        mock_deep_research.return_value = (
            "# Report\nResearch findings",
            "Result data",
            "Context data",
            10.5,
            [],
            [],
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["research", "machine learning"])

        assert result.exit_code == 0
        mock_deep_research.assert_called_once()

    @pytest.mark.unit
    @patch("litdb.commands.research_commands.deep_research")
    @patch("litdb.commands.research_commands.os")
    def test_research_with_output_file(self, mock_os, mock_deep_research):
        """Test research with output file."""
        mock_deep_research.return_value = (
            "# Report\nResearch findings",
            "Result",
            "Context",
            10.5,
            [],
            [],
        )
        mock_os.path.splitext.return_value = ("output", ".md")
        mock_os.path.exists.return_value = True
        mock_os.path.abspath.return_value = "/path/output.md"

        runner = CliRunner()
        with patch("builtins.open", create=True):
            with patch("litdb.commands.research_commands.webbrowser"):
                result = runner.invoke(cli, ["research", "AI", "-o", "output.md"])

        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires API keys and network")
    def test_research_integration(self):
        """Test research command with actual API."""
        runner = CliRunner()
        result = runner.invoke(cli, ["research", "machine learning"])

        assert result.exit_code == 0


class TestSuggestReviewersCommand:
    """Test the 'litdb suggest-reviewers' command."""

    @pytest.mark.unit
    @patch("litdb.commands.research_commands.get_data")
    @patch("litdb.commands.research_commands.get_config")
    @patch("litdb.commands.research_commands.get_ipython")
    @patch("litdb.commands.research_commands.click.Context")
    def test_suggest_reviewers_basic(
        self, mock_context, mock_ipython, mock_config, mock_get_data
    ):
        """Test suggesting reviewers."""
        mock_config.return_value = {"openalex": {"email": "test@example.com"}}
        mock_ipython.return_value = None  # Not in IPython

        # Mock vsearch results
        mock_ctx = MagicMock()
        mock_ctx.invoke.return_value = [
            (
                "source1",
                "citation1",
                '{"authorships": [{"author": {"id": "A1"}}]}',
                0.1,
            ),
        ]
        mock_context.return_value.__enter__.return_value = mock_ctx

        # Mock OpenAlex author data
        mock_get_data.return_value = {
            "results": [
                {
                    "id": "A1",
                    "display_name": "John Doe",
                    "summary_stats": {"h_index": 50},
                    "last_known_institutions": [{"display_name": "MIT"}],
                }
            ]
        }

        runner = CliRunner()
        result = runner.invoke(cli, ["suggest-reviewers", "machine learning"])

        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database and network")
    def test_suggest_reviewers_integration(self):
        """Test suggest reviewers with actual database."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["suggest-reviewers", "machine learning", "-n", "3"]
        )

        assert result.exit_code == 0
