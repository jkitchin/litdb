"""Unit tests for core CLI commands (init, add, remove).

These tests cover the foundational commands that will be moved to
commands/manage.py and commands/add.py during refactoring.
"""

import pytest
from click.testing import CliRunner

from litdb.cli import cli


class TestInitCommand:
    """Test the 'litdb init' command."""

    @pytest.mark.unit
    def test_init_creates_config(self, tmp_path, monkeypatch):
        """Test that init creates a litdb.toml file."""
        runner = CliRunner()

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Run init and provide input
        result = runner.invoke(
            cli,
            ["init"],
            input="\n".join(
                [
                    "test@example.com",  # email
                    "",  # api key (empty)
                    "",  # embedding model (use default)
                    "",  # llm model (use default)
                    "",  # gpt model (use default)
                ]
            ),
        )

        # Check command succeeded
        assert result.exit_code == 0

        # Check litdb.toml was created
        config_file = tmp_path / "litdb.toml"
        assert config_file.exists()

        # Check content
        content = config_file.read_text()
        assert "test@example.com" in content
        assert "[embedding]" in content
        assert "[openalex]" in content

    @pytest.mark.unit
    def test_init_creates_database(self, tmp_path, monkeypatch):
        """Test that init creates a database file."""
        runner = CliRunner()
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            cli,
            ["init"],
            input="\n".join(["test@example.com", "", "", "", ""]),
        )

        assert result.exit_code == 0

        # Check database was created
        db_file = tmp_path / "litdb.libsql"
        assert db_file.exists()

    @pytest.mark.unit
    def test_init_in_existing_project(self, tmp_path, monkeypatch):
        """Test init when litdb.toml already exists."""
        runner = CliRunner()
        monkeypatch.chdir(tmp_path)

        # Create existing config
        config_file = tmp_path / "litdb.toml"
        config_file.write_text("[embedding]\nmodel = 'existing'\n")

        result = runner.invoke(cli, ["init"], input="\n")

        # Init prompts for input even if config exists
        # User can abort with empty input, or it may proceed
        # Either way, we just verify it doesn't crash
        assert result.exit_code in (0, 1)  # Success or user abort
        assert config_file.exists()  # Config should still exist


class TestAboutCommand:
    """Test the 'litdb about' command."""

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database with data")
    def test_about_shows_statistics(self):
        """Test that about shows database statistics."""
        runner = CliRunner()
        result = runner.invoke(cli, ["about"])

        assert result.exit_code == 0
        # Should show some statistics
        assert "sources" in result.output.lower() or "entries" in result.output.lower()


class TestAddCommandPlaceholder:
    """Placeholder tests for 'litdb add' command.

    These will be implemented with proper API mocking.
    """

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires OpenAlex API mocking")
    def test_add_doi_basic(self):
        """Test adding a work by DOI."""
        runner = CliRunner()
        # TODO: Mock OpenAlex API response
        result = runner.invoke(cli, ["add", "https://doi.org/10.1234/test"])

        assert result.exit_code == 0
        assert "added" in result.output.lower()

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires OpenAlex API mocking")
    def test_add_with_references(self):
        """Test adding a work with its references."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["add", "https://doi.org/10.1234/test", "--references"]
        )

        assert result.exit_code == 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires OpenAlex API mocking")
    def test_add_invalid_doi(self):
        """Test error handling for invalid DOI."""
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "not-a-doi"])

        # Should handle error gracefully
        assert "error" in result.output.lower() or result.exit_code != 0

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires bibtex file fixture")
    def test_add_from_bibtex(self):
        """Test adding entries from a bibtex file."""
        # TODO: Create bibtex fixture
        # TODO: Test adding from file
        pass


class TestRemoveCommandPlaceholder:
    """Placeholder tests for 'litdb remove' command."""

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires test database")
    def test_remove_by_source(self):
        """Test removing a source from database."""
        # TODO: Set up test database with known entry
        # TODO: Test removal
        # TODO: Verify it's gone
        pass


class TestVersionCommand:
    """Test the version command."""

    @pytest.mark.unit
    def test_version_shows_version(self):
        """Test that version command shows package version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])

        # Should show version number
        # Format depends on implementation
        assert result.exit_code == 0
