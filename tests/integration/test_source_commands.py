"""Tests for the per-source Typer subapp factory."""

from __future__ import annotations

import subprocess  # noqa: S404
from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from cobo import source_commands as sc
from cobo.config.schema import Source
from cobo.errors import GitError, UserError
from cobo.source_commands import build_source_subapp

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

runner = CliRunner()


@pytest.fixture
def fake_clone(tmp_path: Path) -> Path:
    """Materialize a fake clone with one boilerplate file and one commit.

    Returns:
        Path to the initialized git repo directory.
    """
    repo = tmp_path / "clone"
    repo.mkdir()
    (repo / "Python.gitignore").write_text("*.pyc\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)  # noqa: S603, S607
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)  # noqa: S603, S607
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "seed",
        ],
        check=True,
    )
    return repo


def gitignore_source() -> Source:
    """Build a gitignore-flavored Source for test fixtures.

    Returns:
        A Source configured for gitignore files with multi-dump enabled.
    """
    return Source(
        name="gitignore",
        url="https://example.com/g.git",
        extension=".gitignore",
        multi_dump=True,
    )


def make_app(source: Source, clone_root: Path) -> typer.Typer:
    """Wrap the per-source subapp in a top-level app for CliRunner.

    Returns:
        A Typer app with the source subapp registered.
    """
    parent = typer.Typer()
    parent.add_typer(
        build_source_subapp(source, clone_root_provider=lambda _src: clone_root),
        name=source.name,
    )
    return parent


def test_list_outputs_known_names(fake_clone: Path) -> None:
    """The `list` subcommand prints discovered names."""
    app = make_app(gitignore_source(), fake_clone)
    result = runner.invoke(app, ["gitignore", "list"])
    assert result.exit_code == 0, result.output
    assert "Python" in result.output


def test_dump_outputs_content(fake_clone: Path) -> None:
    """The `dump` subcommand prints the file content."""
    app = make_app(gitignore_source(), fake_clone)
    result = runner.invoke(app, ["gitignore", "dump", "Python"])
    assert result.exit_code == 0, result.output
    assert "*.pyc" in result.output


def test_dump_rejects_multiple_names_when_multi_disabled(fake_clone: Path) -> None:
    """A source with multi_dump=False exits non-zero for >1 name."""
    single = Source(
        name="mise",
        url="https://example.com/m.git",
        extension=".gitignore",
        multi_dump=False,
    )
    app = make_app(single, fake_clone)
    result = runner.invoke(app, ["mise", "dump", "a", "b"])
    assert result.exit_code != 0


def test_search_matches_case_insensitive(fake_clone: Path) -> None:
    """The `search` subcommand matches substrings case-insensitively."""
    app = make_app(gitignore_source(), fake_clone)
    result = runner.invoke(app, ["gitignore", "search", "py"])
    assert result.exit_code == 0, result.output
    assert "Python" in result.output


def test_remote_prints_source_url(fake_clone: Path) -> None:
    """The `remote` subcommand prints the source's git URL."""
    app = make_app(gitignore_source(), fake_clone)
    result = runner.invoke(app, ["gitignore", "remote"])
    assert result.exit_code == 0, result.output
    assert "example.com" in result.output


def test_root_prints_clone_path(fake_clone: Path) -> None:
    """The `root` subcommand prints the clone path."""
    app = make_app(gitignore_source(), fake_clone)
    result = runner.invoke(app, ["gitignore", "root"])
    assert result.exit_code == 0, result.output
    assert str(fake_clone) in result.output


def test_update_prints_ok_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`<source> update` prints `<name>: ok` when clone/pull succeeds."""
    monkeypatch.setattr(sc, "clone_or_pull", lambda *_a, **_k: None)
    app = make_app(gitignore_source(), tmp_path / "absent")
    result = runner.invoke(app, ["gitignore", "update"])
    assert result.exit_code == 0, result.output
    assert "gitignore: ok" in result.output


def test_update_exits_two_on_git_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`<source> update` exits 2 when clone_or_pull raises GitError."""

    def boom(*_a: object, **_k: object) -> None:
        msg = "no remote"
        raise GitError(msg)

    monkeypatch.setattr(sc, "clone_or_pull", boom)
    app = make_app(gitignore_source(), tmp_path / "absent")
    result = runner.invoke(app, ["gitignore", "update"])
    assert result.exit_code == 2  # noqa: PLR2004


def test_list_exits_when_clone_missing(tmp_path: Path) -> None:
    """`list` exits non-zero and prompts for `update` when clone path absent."""
    app = make_app(gitignore_source(), tmp_path / "missing")
    result = runner.invoke(app, ["gitignore", "list"])
    assert result.exit_code == 1
    assert "has not been cloned" in (result.output + (result.stderr or ""))


def test_search_exits_when_clone_missing(tmp_path: Path) -> None:
    """`search` exits non-zero when clone path absent."""
    app = make_app(gitignore_source(), tmp_path / "missing")
    result = runner.invoke(app, ["gitignore", "search", "py"])
    assert result.exit_code == 1


def test_dump_exits_when_clone_missing(tmp_path: Path) -> None:
    """`dump` exits non-zero when clone path absent."""
    app = make_app(gitignore_source(), tmp_path / "missing")
    result = runner.invoke(app, ["gitignore", "dump", "Python"])
    assert result.exit_code == 1


def test_dump_exits_one_on_user_error(
    fake_clone: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`dump` exits 1 when render raises UserError (e.g., unknown name)."""

    def boom(*_a: object, **_k: object) -> str:
        msg = "unknown boilerplate"
        raise UserError(msg)

    monkeypatch.setattr(sc, "render_dump", boom)
    app = make_app(gitignore_source(), fake_clone)
    result = runner.invoke(app, ["gitignore", "dump", "Python"])
    assert result.exit_code == 1
