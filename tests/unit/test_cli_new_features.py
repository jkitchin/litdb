"""Unit tests for new CLI features (summary, fromtext, extract, schema).

These commands were recently added in v2.1.8 and need comprehensive testing
before refactoring to commands/review.py and commands/extract.py.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch

from litdb.cli import cli


class TestSummaryCommand:
    """Test the 'litdb summary' command."""

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires database and LLM mocking")
    def test_summary_default_timeframe(self):
        """Test summary with default '1 week' timeframe."""
        runner = CliRunner()

        with patch("litdb.summary.generate_summary") as mock_gen:
            result = runner.invoke(cli, ["summary"])

            assert result.exit_code == 0
            # Verify generate_summary was called
            mock_gen.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires mocking")
    def test_summary_custom_timeframe(self):
        """Test summary with custom time period."""
        runner = CliRunner()

        with patch("litdb.summary.generate_summary") as mock_gen:
            result = runner.invoke(cli, ["summary", "-s", "2 weeks"])

            assert result.exit_code == 0
            # Check that '2 weeks' was passed
            call_kwargs = mock_gen.call_args[1]
            assert call_kwargs.get("since") == "2 weeks"

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires mocking")
    def test_summary_with_output_file(self, tmp_path):
        """Test summary with output file."""
        runner = CliRunner()
        output_file = tmp_path / "summary.org"

        with patch("litdb.summary.generate_summary") as mock_gen:
            result = runner.invoke(cli, ["summary", "-o", str(output_file)])

            assert result.exit_code == 0
            call_kwargs = mock_gen.call_args[1]
            assert call_kwargs.get("output_file") == str(output_file)

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires mocking")
    def test_summary_custom_model(self):
        """Test summary with custom LLM model."""
        runner = CliRunner()

        with patch("litdb.summary.generate_summary") as mock_gen:
            result = runner.invoke(cli, ["summary", "--model", "gpt-4o"])

            assert result.exit_code == 0
            call_kwargs = mock_gen.call_args[1]
            assert call_kwargs.get("model") == "gpt-4o"


class TestFromtextCommand:
    """Test the 'litdb fromtext' command."""

    @pytest.mark.unit
    def test_fromtext_basic_structure(self):
        """Test fromtext command exists and has proper structure."""
        runner = CliRunner()

        # Test with --help to verify command exists
        result = runner.invoke(cli, ["fromtext", "--help"])

        assert result.exit_code == 0
        assert "TEXT" in result.output
        assert "references" in result.output.lower()

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires LLM and API mocking")
    def test_fromtext_with_doi(self):
        """Test fromtext with text containing a DOI."""
        runner = CliRunner()
        text = "Kitchin, ACS Catal. 2015, DOI: 10.1021/acscatal.5b00538"

        # TODO: Mock LLM response
        # TODO: Mock CrossRef API
        # TODO: Mock add_work function

        result = runner.invoke(cli, ["fromtext", text])

        # Should parse and add the reference
        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires mocking")
    def test_fromtext_with_references_flag(self):
        """Test fromtext with --references flag."""
        runner = CliRunner()
        text = "Some paper, 2024"

        result = runner.invoke(cli, ["fromtext", text, "--references"])

        # Should also add references of matched papers
        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires mocking")
    def test_fromtext_custom_model(self):
        """Test fromtext with custom LLM model."""
        runner = CliRunner()
        text = "Paper citation"

        result = runner.invoke(cli, ["fromtext", text, "--model", "gpt-4o"])

        assert result.exit_code == 0


class TestExtractCommand:
    """Test the 'litdb extract' command."""

    @pytest.mark.unit
    def test_extract_command_exists(self):
        """Test that extract command exists."""
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "--help"])

        assert result.exit_code == 0
        assert "PDF" in result.output
        assert "tables" in result.output.lower()

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires PDF fixture")
    def test_extract_all_tables(self, tmp_path):
        """Test extracting all tables from PDF."""
        # TODO: Create PDF fixture with tables
        # TODO: Test extraction
        pass

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires PDF fixture")
    def test_extract_specific_tables(self):
        """Test extracting specific tables with -t flag."""
        # TODO: Test with -t 1 -t 3
        pass

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires PDF fixture")
    def test_extract_output_format(self):
        """Test extract with different output formats."""
        # TODO: Test with -f option
        pass


class TestSchemaCommand:
    """Test the 'litdb schema' command."""

    @pytest.mark.unit
    def test_schema_command_exists(self):
        """Test that schema command exists."""
        runner = CliRunner()
        result = runner.invoke(cli, ["schema", "--help"])

        assert result.exit_code == 0
        assert "SOURCE" in result.output
        assert "SCHEMA" in result.output

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires source file and LLM mocking")
    def test_schema_with_dsl(self):
        """Test schema extraction with DSL syntax."""
        runner = CliRunner()
        schema = "title:str, year:int, authors:list"

        # TODO: Mock document conversion
        # TODO: Mock LLM extraction
        # TODO: Provide source file fixture

        result = runner.invoke(cli, ["schema", "test.pdf", schema])

        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires mocking")
    def test_schema_with_json(self):
        """Test schema extraction with JSON schema."""
        runner = CliRunner()
        schema_json = '{"title": ["str", null], "year": ["int", 2024]}'

        result = runner.invoke(cli, ["schema", "test.pdf", schema_json])

        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires mocking")
    def test_schema_complex_types(self):
        """Test schema with various field types."""
        runner = CliRunner()
        schema = "name:str, age:int, score:float, active:bool, tags:list"

        result = runner.invoke(cli, ["schema", "test.pdf", schema])

        assert result.exit_code == 0


class TestReviewCommand:
    """Test the 'litdb review' command."""

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_review_default_timeframe(self):
        """Test review with default time period."""
        runner = CliRunner()
        result = runner.invoke(cli, ["review"])

        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_review_custom_timeframe(self):
        """Test review with custom time period."""
        runner = CliRunner()
        result = runner.invoke(cli, ["review", "-s", "2 weeks"])

        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_review_output_format(self):
        """Test review with custom output format."""
        runner = CliRunner()
        fmt = "{{ source }}: {{ title }}"
        result = runner.invoke(cli, ["review", "--fmt", fmt])

        assert result.exit_code == 0
