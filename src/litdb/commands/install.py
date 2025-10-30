"""Installation commands for litdb.

Commands:
- install claude-skill: Install litdb skill for Claude Code
- install mcp-server: Install litdb MCP server for Claude Desktop
"""

import json
import os
import platform
import shutil
from pathlib import Path

import click
from rich import print as richprint


@click.group()
def install():
    """Install litdb integrations for Claude tools."""
    pass


@install.command("claude-skill")
def install_claude_skill():
    """Install the litdb skill for Claude Code.

    Copies SKILL.md from the litdb repository to ~/.claude/skills/litdb/
    """
    # Find the SKILL.md file in the package
    try:
        import litdb

        litdb_dir = Path(litdb.__file__).parent.parent.parent
        skill_source = litdb_dir / "SKILL.md"

        if not skill_source.exists():
            richprint("[red]Error: SKILL.md not found in litdb repository[/red]")
            richprint(f"[yellow]Looked in: {skill_source}[/yellow]")
            raise click.Abort()

        # Create target directory
        skill_dir = Path.home() / ".claude" / "skills" / "litdb"
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Copy SKILL.md
        skill_target = skill_dir / "SKILL.md"
        shutil.copy2(skill_source, skill_target)

        richprint("[green]✓ Successfully installed Claude Code skill![/green]")
        richprint(f"[blue]Skill installed to: {skill_target}[/blue]")
        richprint("[yellow]Restart Claude Code to use the litdb skill[/yellow]")

    except Exception as e:
        richprint(f"[red]Error installing Claude Code skill: {e}[/red]")
        raise click.Abort()


@install.command("mcp-server")
@click.option(
    "--db",
    default=None,
    help="Path to litdb database. If not specified, uses the current database from config.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt and install immediately.",
)
def install_mcp_server(db, yes):
    """Install the litdb MCP server for Claude Desktop.

    This configures Claude Desktop to use litdb as an MCP server.
    """
    # Get the database path
    if db is None:
        from ..utils import get_config

        try:
            config = get_config()
            root = config.get("root")
            if root:
                db = os.path.join(root, "litdb.libsql")
            else:
                richprint(
                    "[red]Error: Could not determine database location from config[/red]"
                )
                richprint(
                    "[yellow]Run this command from a directory with litdb.toml or set LITDB_ROOT[/yellow]"
                )
                richprint(
                    "[yellow]Or use --db option to specify the database path explicitly[/yellow]"
                )
                raise click.Abort()
        except SystemExit:
            richprint("[red]Error: Could not load litdb config[/red]")
            richprint(
                "[yellow]Make sure you are in a directory with litdb.toml[/yellow]"
            )
            richprint(
                "[yellow]Or use --db option to specify the database path explicitly[/yellow]"
            )
            raise click.Abort()

    # Expand path
    db = os.path.expanduser(db)
    db = os.path.abspath(db)

    if not os.path.exists(db):
        richprint(f"[red]Error: Database not found at {db}[/red]")
        richprint(
            "[yellow]Make sure the database exists before installing the MCP server[/yellow]"
        )
        raise click.Abort()

    # Get database size for display
    db_size_mb = os.path.getsize(db) / (1024 * 1024)

    # Show details and ask for confirmation
    richprint("\n[bold]MCP Server Installation Details:[/bold]")
    richprint(f"[blue]Database path:[/blue] {db}")
    richprint(f"[blue]Database size:[/blue] {db_size_mb:.2f} MB")

    if not yes:
        richprint(
            "\n[yellow]This will configure Claude Desktop to use this litdb database.[/yellow]"
        )
        confirm = input("Continue with installation? (y/N): ")
        if not confirm.lower().startswith("y"):
            richprint("[yellow]Installation cancelled[/yellow]")
            raise click.Abort()

    # Get Claude Desktop config file path based on platform
    if platform.system() == "Darwin":
        cfgfile = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    elif platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            richprint("[red]Error: APPDATA environment variable not set[/red]")
            raise click.Abort()
        cfgfile = Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:
        richprint("[red]Error: Only macOS and Windows are supported[/red]")
        raise click.Abort()

    # Load existing config or create new one
    if cfgfile.exists():
        with open(cfgfile, "r") as f:
            cfg = json.load(f)
    else:
        cfg = {}
        cfgfile.parent.mkdir(parents=True, exist_ok=True)

    # Find litdb_mcp command
    litdb_mcp_path = shutil.which("litdb_mcp")
    if not litdb_mcp_path:
        richprint("[red]Error: litdb_mcp command not found[/red]")
        richprint(
            "[yellow]Make sure litdb is installed with MCP support: pip install litdb[mcp][/yellow]"
        )
        raise click.Abort()

    # Setup MCP server configuration
    setup = {
        "command": litdb_mcp_path,
        "env": {
            "litdb": db,
            "LITDB_ROOT": os.path.dirname(db),
        },
    }

    if "mcpServers" not in cfg:
        cfg["mcpServers"] = {}

    cfg["mcpServers"]["litdb"] = setup

    # Write config
    with open(cfgfile, "w") as f:
        json.dump(cfg, f, indent=4)

    richprint("[green]✓ Successfully installed litdb MCP server![/green]")
    richprint(f"[blue]Database: {db}[/blue]")
    richprint(f"[blue]Config file: {cfgfile}[/blue]")
    richprint("[yellow]Please restart Claude Desktop to use the MCP server[/yellow]")


@install.command("uninstall-mcp")
def uninstall_mcp_server():
    """Uninstall the litdb MCP server from Claude Desktop."""
    # Get Claude Desktop config file path based on platform
    if platform.system() == "Darwin":
        cfgfile = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    elif platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            richprint("[red]Error: APPDATA environment variable not set[/red]")
            raise click.Abort()
        cfgfile = Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:
        richprint("[red]Error: Only macOS and Windows are supported[/red]")
        raise click.Abort()

    # Load existing config
    if not cfgfile.exists():
        richprint(
            "[yellow]No Claude Desktop config found - nothing to uninstall[/yellow]"
        )
        return

    with open(cfgfile, "r") as f:
        cfg = json.load(f)

    # Remove litdb MCP server
    if "mcpServers" in cfg and "litdb" in cfg["mcpServers"]:
        del cfg["mcpServers"]["litdb"]

        # Write config
        with open(cfgfile, "w") as f:
            json.dump(cfg, f, indent=4)

        richprint("[green]✓ Successfully uninstalled litdb MCP server[/green]")
        richprint("[yellow]Please restart Claude Desktop[/yellow]")
    else:
        richprint("[yellow]litdb MCP server is not installed[/yellow]")
