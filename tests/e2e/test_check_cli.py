"""End-to-end tests for `cobo check` CLI surface (no network)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cobo.cli import app

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e

runner = CliRunner()

_EXIT_NO_LOCK = 2

_LOCK_UNKNOWN_SOURCE = """\
version = 1

[[fragment]]
path = ".gitignore"
source = "does-not-exist"
update = true

  [[fragment.files]]
  name = "Python"
  path = "Python.gitignore"
  commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  blob = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
"""


def test_check_missing_lock_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No lockfile -> usage error, exit code 2."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == _EXIT_NO_LOCK, result.output


def test_check_unknown_source_reports_and_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown-source fragment is reported but is not 'outdated' (exit 0)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cobo.lock").write_text(_LOCK_UNKNOWN_SOURCE, encoding="utf-8")
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "does-not-exist" in result.output


def test_check_json_emits_machine_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json prints parseable JSON with a fragments array."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cobo.lock").write_text(_LOCK_UNKNOWN_SOURCE, encoding="utf-8")
    result = runner.invoke(app, ["check", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["outdated_count"] == 0
    assert payload["fragments"][0]["path"] == ".gitignore"


_LOCK_HELD_BAKED = """\
version = 1

[[fragment]]
path = ".gitignore"
source = "gitignore"
update = false

  [[fragment.files]]
  name = "Python"
  path = "Python.gitignore"
  commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  blob = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
"""


def test_check_table_shows_held_fragment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A held fragment renders in the table as 'held' (no network)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cobo.lock").write_text(_LOCK_HELD_BAKED, encoding="utf-8")
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "held" in result.output


def test_sync_missing_lock_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cobo sync` with no lockfile exits 2."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == _EXIT_NO_LOCK, result.output


def test_sync_unknown_source_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cobo sync` over an unknown-source lock reports failure (exit 1)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cobo.lock").write_text(_LOCK_UNKNOWN_SOURCE, encoding="utf-8")
    result = runner.invoke(app, ["sync", "--dry-run"])
    assert result.exit_code == 1, result.output
