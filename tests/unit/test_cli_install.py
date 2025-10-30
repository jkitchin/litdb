"""Unit tests for install CLI commands.

Tests for claude-skill and mcp-server installation commands.
"""

import json
import pytest
from click.testing import CliRunner
from unittest.mock import patch

from litdb.cli import cli


class TestInstallClaudeSkillCommand:
    """Test the 'litdb install claude-skill' command."""

    @pytest.mark.unit
    def test_install_claude_skill_help(self):
        """Test that claude-skill command has help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "claude-skill", "--help"])

        assert result.exit_code == 0
        assert "Install the litdb skill for Claude Code" in result.output

    @pytest.mark.unit
    def test_install_claude_skill_creates_directory(self, tmp_path, monkeypatch):
        """Test that claude-skill creates directory and copies file."""
        runner = CliRunner()

        # Mock home directory
        mock_home = tmp_path / "home"
        mock_home.mkdir()

        # Mock Path.home() to return our test directory
        with patch("pathlib.Path.home", return_value=mock_home):
            # Mock litdb module location to find SKILL.md
            import litdb

            with patch.object(
                litdb, "__file__", str(tmp_path / "src" / "litdb" / "__init__.py")
            ):
                # Create a fake SKILL.md in the right location
                skill_dir = tmp_path / "SKILL.md"
                skill_dir.write_text("# Test Skill")

                result = runner.invoke(cli, ["install", "claude-skill"])

                # Check command succeeded
                assert result.exit_code == 0
                assert "Successfully installed Claude Code skill" in result.output

                # Check directory was created
                target_dir = mock_home / ".claude" / "skills" / "litdb"
                assert target_dir.exists()

                # Check SKILL.md was copied
                target_file = target_dir / "SKILL.md"
                assert target_file.exists()
                assert target_file.read_text() == "# Test Skill"


class TestInstallMcpServerCommand:
    """Test the 'litdb install mcp-server' command."""

    @pytest.mark.unit
    def test_install_mcp_server_help(self):
        """Test that mcp-server command has help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "mcp-server", "--help"])

        assert result.exit_code == 0
        assert "Install the litdb MCP server for Claude Desktop" in result.output

    @pytest.mark.unit
    @patch("shutil.which")
    def test_install_mcp_server_basic(self, mock_which, tmp_path):
        """Test basic MCP server installation."""
        runner = CliRunner()

        # Setup mocks
        mock_which.return_value = "/usr/local/bin/litdb_mcp"

        # Create a fake database
        db_path = tmp_path / "test.libsql"
        db_path.write_text("fake db")

        # Mock platform to be Mac
        import platform

        with patch.object(platform, "system", return_value="Darwin"):
            # Mock Path.home() to use our test directory
            with patch("pathlib.Path.home", return_value=tmp_path):
                # Create the config directory structure
                lib_dir = tmp_path / "Library" / "Application Support" / "Claude"
                lib_dir.mkdir(parents=True)

                result = runner.invoke(
                    cli, ["install", "mcp-server", "--db", str(db_path), "-y"]
                )

                # Check command succeeded
                assert result.exit_code == 0
                assert "Successfully installed litdb MCP server" in result.output

                # Check config file was created
                config_path = lib_dir / "claude_desktop_config.json"
                assert config_path.exists()

                # Check config content
                with open(config_path) as f:
                    config = json.load(f)

                assert "mcpServers" in config
                assert "litdb" in config["mcpServers"]
                assert (
                    config["mcpServers"]["litdb"]["command"]
                    == "/usr/local/bin/litdb_mcp"
                )

    @pytest.mark.unit
    @patch("shutil.which")
    def test_install_mcp_server_with_confirmation(self, mock_which, tmp_path):
        """Test MCP server installation with user confirmation."""
        runner = CliRunner()

        # Setup mocks
        mock_which.return_value = "/usr/local/bin/litdb_mcp"

        # Create a fake database
        db_path = tmp_path / "test.libsql"
        db_path.write_text("fake db")

        # Mock platform to be Mac
        import platform

        with patch.object(platform, "system", return_value="Darwin"):
            # Mock Path.home() to use our test directory
            with patch("pathlib.Path.home", return_value=tmp_path):
                # Create the config directory structure
                lib_dir = tmp_path / "Library" / "Application Support" / "Claude"
                lib_dir.mkdir(parents=True)

                # Test with 'y' input
                result = runner.invoke(
                    cli, ["install", "mcp-server", "--db", str(db_path)], input="y\n"
                )

                # Check command succeeded
                assert result.exit_code == 0
                assert "MCP Server Installation Details:" in result.output
                assert "Continue with installation?" in result.output
                assert "Successfully installed litdb MCP server" in result.output

    @pytest.mark.unit
    @patch("shutil.which")
    def test_install_mcp_server_cancelled(self, mock_which, tmp_path):
        """Test MCP server installation cancelled by user."""
        runner = CliRunner()

        # Setup mocks
        mock_which.return_value = "/usr/local/bin/litdb_mcp"

        # Create a fake database
        db_path = tmp_path / "test.libsql"
        db_path.write_text("fake db")

        # Mock platform to be Mac
        import platform

        with patch.object(platform, "system", return_value="Darwin"):
            # Mock Path.home() to use our test directory
            with patch("pathlib.Path.home", return_value=tmp_path):
                # Test with 'n' input (cancel)
                result = runner.invoke(
                    cli, ["install", "mcp-server", "--db", str(db_path)], input="n\n"
                )

                # Check command was cancelled
                assert result.exit_code == 1
                assert "Installation cancelled" in result.output


class TestUninstallMcpCommand:
    """Test the 'litdb install uninstall-mcp' command."""

    @pytest.mark.unit
    def test_uninstall_mcp_help(self):
        """Test that uninstall-mcp command has help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "uninstall-mcp", "--help"])

        assert result.exit_code == 0
        assert "Uninstall the litdb MCP server from Claude Desktop" in result.output

    @pytest.mark.unit
    def test_uninstall_mcp_removes_config(self, tmp_path):
        """Test that uninstall-mcp removes MCP server from config."""
        runner = CliRunner()

        # Mock platform to be Mac
        import platform

        with patch.object(platform, "system", return_value="Darwin"):
            # Mock Path.home() to use our test directory
            with patch("pathlib.Path.home", return_value=tmp_path):
                # Create the config directory structure
                lib_dir = tmp_path / "Library" / "Application Support" / "Claude"
                lib_dir.mkdir(parents=True)

                # Create existing config with litdb
                config_path = lib_dir / "claude_desktop_config.json"
                config = {
                    "mcpServers": {
                        "litdb": {
                            "command": "/usr/local/bin/litdb_mcp",
                            "env": {"litdb": "/path/to/db"},
                        },
                        "other": {"command": "/other/command"},
                    }
                }
                with open(config_path, "w") as f:
                    json.dump(config, f)

                # Run uninstall
                result = runner.invoke(cli, ["install", "uninstall-mcp"])

                # Check command succeeded
                assert result.exit_code == 0
                assert "Successfully uninstalled litdb MCP server" in result.output

                # Check config was updated
                with open(config_path) as f:
                    updated_config = json.load(f)

                assert "litdb" not in updated_config["mcpServers"]
                assert (
                    "other" in updated_config["mcpServers"]
                )  # Other servers preserved
