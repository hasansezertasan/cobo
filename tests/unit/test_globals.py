"""Tests for the global commands."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from cobo import globals as cobo_globals
from cobo.commands.check import CheckResult, FragmentReport
from cobo.commands.sync import FailedFragment, SyncResult
from cobo.config.schema import CoboConfig, Source
from cobo.errors import GitError
from cobo.globals import attach_globals
from cobo.lock.diff import FileDrift
from cobo.paths import source_clone_root

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

runner = CliRunner()


def make_config() -> CoboConfig:
    """Build a minimal CoboConfig for tests.

    Returns:
        A CoboConfig with a single demo source.
    """
    return CoboConfig(
        default_branch="main",
        sources={
            "demo": Source(name="demo", url="https://example.com", extension=".x"),
        },
    )


def app_with_globals(tmp_path: Path) -> typer.Typer:
    """Create a Typer app with global commands attached.

    Returns:
        A Typer app ready for CliRunner invocation.
    """
    parent = typer.Typer()
    attach_globals(
        parent,
        config=make_config(),
        cache_root=tmp_path,
        user_config_file=tmp_path / "config.toml",
    )
    return parent


def test_version_prints_package_version(tmp_path: Path) -> None:
    """`cobo version` prints a version string."""
    result = runner.invoke(app_with_globals(tmp_path), ["version"])
    assert result.exit_code == 0, result.output
    assert result.output.strip()


def test_root_prints_cache_root(tmp_path: Path) -> None:
    """`cobo root` prints the cache root path."""
    result = runner.invoke(app_with_globals(tmp_path), ["root"])
    assert result.exit_code == 0
    assert str(tmp_path) in result.output


def test_config_path_prints_user_config_path(tmp_path: Path) -> None:
    """`cobo config-path` prints the user config file path."""
    result = runner.invoke(app_with_globals(tmp_path), ["config-path"])
    assert result.exit_code == 0
    assert "config.toml" in result.output


def test_list_sources_includes_configured_name(tmp_path: Path) -> None:
    """`cobo list-sources` includes the configured source name."""
    result = runner.invoke(app_with_globals(tmp_path), ["list-sources"])
    assert result.exit_code == 0
    assert "demo" in result.output


def test_info_mentions_python_version(tmp_path: Path) -> None:
    """`cobo info` includes Python version information."""
    result = runner.invoke(app_with_globals(tmp_path), ["info"])
    assert result.exit_code == 0
    assert "Python" in result.output


def test_config_prints_all_source_fields(tmp_path: Path) -> None:
    """`cobo config` emits a TOML-ish block with every source field."""
    result = runner.invoke(app_with_globals(tmp_path), ["config"])
    assert result.exit_code == 0, result.output
    assert "[sources.demo]" in result.output
    assert 'url = "https://example.com"' in result.output
    assert 'branch = "main"' in result.output
    assert 'extension = ".x"' in result.output
    assert "multi_dump = false" in result.output
    assert "inject_header = " in result.output
    assert "comment_prefix = " in result.output
    assert "subpath = " in result.output


def test_update_reports_ok_per_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cobo update` prints `<name>: ok` for each successful source."""
    monkeypatch.setattr(cobo_globals, "clone_or_pull", lambda *_a, **_k: None)
    result = runner.invoke(app_with_globals(tmp_path), ["update"])
    assert result.exit_code == 0, result.output
    assert "demo: ok" in result.output


def test_update_exits_with_failure_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cobo update` exits with non-zero code equal to number of failed sources."""

    def boom(*_a: object, **_k: object) -> None:
        msg = "remote unreachable"
        raise GitError(msg)

    monkeypatch.setattr(cobo_globals, "clone_or_pull", boom)
    result = runner.invoke(app_with_globals(tmp_path), ["update"])
    assert result.exit_code == 1
    assert "demo: failed" in result.output
    assert "remote unreachable" in result.output


_LOCK_CONTENT = """\
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


def _make_sync_result(
    changed: tuple[str, ...] = (),
    failed: tuple[FailedFragment, ...] = (),
) -> SyncResult:
    check = CheckResult(reports=())
    return SyncResult(changed=changed, failed=failed, check=check)


def test_sync_reports_changed_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cobo sync` prints updated paths and exits 0 when there are only changes."""
    (tmp_path / "cobo.lock").write_text(_LOCK_CONTENT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cobo_globals,
        "run_sync",
        MagicMock(return_value=_make_sync_result(changed=(".gitignore",))),
    )
    result = runner.invoke(app_with_globals(tmp_path), ["sync"])
    assert result.exit_code == 0, result.output
    assert "updated: .gitignore" in result.output


def test_sync_reports_failed_paths_and_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cobo sync` prints failed paths with their reason and exits 1."""
    (tmp_path / "cobo.lock").write_text(_LOCK_CONTENT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cobo_globals,
        "run_sync",
        MagicMock(
            return_value=_make_sync_result(
                failed=(FailedFragment(path=".gitignore", reason="gone upstream"),),
            ),
        ),
    )
    result = runner.invoke(app_with_globals(tmp_path), ["sync"])
    assert result.exit_code == 1, result.output
    assert "failed: .gitignore: gone upstream" in result.output


def test_check_outdated_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cobo check` exits 1 when a fragment is outdated (drift detected)."""
    (tmp_path / "cobo.lock").write_text(_LOCK_CONTENT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    outdated = FragmentReport(
        path=".gitignore",
        source="demo",
        held=False,
        drifts=(FileDrift(name="Python", path="p", old_blob="o", new_blob="n"),),
    )
    monkeypatch.setattr(
        cobo_globals,
        "run_check",
        MagicMock(return_value=CheckResult(reports=(outdated,))),
    )
    result = runner.invoke(app_with_globals(tmp_path), ["check"])
    assert result.exit_code == 1, result.output
    assert "outdated" in result.output


def test_clone_root_provider_maps_source_to_cache_path() -> None:
    """_clone_root_provider returns the cache clone root for the source name."""
    source = Source(name="gi", url="https://github.com/x/y", extension=".gitignore")
    assert cobo_globals._clone_root_provider(source) == source_clone_root("gi")  # noqa: SLF001


def test_print_check_table_renders_all_status_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_print_check_table renders error/held/outdated/up-to-date rows."""
    buf = io.StringIO()
    monkeypatch.setattr(cobo_globals, "_console", Console(file=buf, width=200))
    reports = (
        FragmentReport(
            path="a.txt",
            source="s",
            held=False,
            drifts=(FileDrift(name="n", path="p", old_blob="o", new_blob="x"),),
        ),
        FragmentReport(path="b.txt", source="s", held=True, drifts=()),
        FragmentReport(path="c.txt", source="s", held=False, drifts=(), error="boom"),
        FragmentReport(path="d.txt", source="s", held=False, drifts=()),
    )
    cobo_globals._print_check_table(CheckResult(reports))  # noqa: SLF001
    out = buf.getvalue()
    assert "outdated" in out
    assert "up to date" in out
    assert "held" in out
    assert "boom" in out


def test_fragment_report_rejects_held_with_drifts() -> None:
    """A held report carrying drifts is an illegal state and is rejected."""
    drift = FileDrift(name="n", path="p", old_blob="o", new_blob="x")
    with pytest.raises(ValueError, match="held"):
        FragmentReport(path="a", source="s", held=True, drifts=(drift,))


def test_fragment_report_rejects_error_with_drifts() -> None:
    """An errored report cannot also carry drifts."""
    drift = FileDrift(name="n", path="p", old_blob="o", new_blob="x")
    with pytest.raises(ValueError, match="errored"):
        FragmentReport(path="a", source="s", held=False, drifts=(drift,), error="boom")


def test_sync_result_rejects_changed_failed_overlap() -> None:
    """A path cannot be both changed and failed in the same SyncResult."""
    with pytest.raises(ValueError, match="both changed and failed"):
        SyncResult(
            changed=(".gitignore",),
            failed=(FailedFragment(path=".gitignore", reason="x"),),
            check=CheckResult(reports=()),
        )
