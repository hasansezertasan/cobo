"""Smoke tests: minimum boot checks for the cobo package and CLI."""

import importlib

import pytest
from typer.testing import CliRunner

from cobo.cli import app
from cobo.config.defaults import BAKED_SOURCES

pytestmark = pytest.mark.smoke

runner = CliRunner()


def test_package_imports() -> None:
    """The top-level cobo package imports without error."""
    module = importlib.import_module("cobo")
    assert module is not None


def test_cli_app_loads() -> None:
    """The Typer app object is importable from cobo.cli."""
    assert app is not None


def test_cli_help_exits_zero() -> None:
    """Invoking `cobo --help` returns exit code 0."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_baked_sources_non_empty() -> None:
    """BAKED_SOURCES contains at least one entry."""
    assert len(BAKED_SOURCES) >= 1
