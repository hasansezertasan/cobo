"""End-to-end tests for the assembled cobo CLI."""

import pytest
from typer.testing import CliRunner

from cobo.cli import app

pytestmark = pytest.mark.e2e

runner = CliRunner()


def test_top_level_help_lists_baked_sources() -> None:
    """Both baked sources appear as subcommands in `cobo --help`."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "gitignore" in result.output
    assert "mise" in result.output


def test_baked_source_help_shows_per_source_commands() -> None:
    """`cobo gitignore --help` lists the standard six per-source commands."""
    result = runner.invoke(app, ["gitignore", "--help"])
    assert result.exit_code == 0
    for cmd in ("update", "list", "search", "dump", "root", "remote"):
        assert cmd in result.output


def test_version_command_exits_zero() -> None:
    """The global `version` command runs."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output


def test_list_sources_includes_both_defaults() -> None:
    """`cobo list-sources` shows both baked defaults."""
    result = runner.invoke(app, ["list-sources"])
    assert result.exit_code == 0
    assert "gitignore" in result.output
    assert "mise" in result.output
