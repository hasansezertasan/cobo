"""Integration tests for record/check/sync against local clones."""

from __future__ import annotations

import subprocess  # noqa: S404
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cobo.commands.record import record_dump
from cobo.config.schema import Source
from cobo.lock.io import read_lock
from cobo.source_commands import build_source_subapp
from cobo.sources.repo import clone_or_pull, current_commit_sha

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

runner = CliRunner()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],  # noqa: S607
        check=True,
    )


def make_source(tmp_path: Path, files: dict[str, str]) -> tuple[Source, Path]:
    """Create a bare upstream repo and return (Source, clone_path).

    Returns:
        A Source pointing at the bare repo and the path to clone into.
    """
    upstream = tmp_path / "upstream.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    for name, content in files.items():
        target = seed / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)  # noqa: S603, S607
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "seed")
    subprocess.run(  # noqa: S603
        ["git", "init", "-q", "--bare", "-b", "main", str(upstream)],  # noqa: S607
        check=True,
    )
    _git(seed, "remote", "add", "origin", str(upstream))
    _git(seed, "push", "-q", "origin", "main")
    source = Source(
        name="gi",
        url=str(upstream),
        extension=".gitignore",
        branch="main",
        multi_dump=True,
    )
    return source, tmp_path / "clone"


def advance_source(tmp_path: Path, name: str, content: str) -> None:
    """Commit a new version of ``name`` to the upstream and push."""
    seed = tmp_path / "seed"
    (seed / name).write_text(content, encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "update")
    _git(seed, "push", "-q", "origin", "main")


def test_record_dump_writes_lock_entry(tmp_path: Path) -> None:
    """record_dump persists a fragment with per-file path/commit/blob."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    out = tmp_path / ".gitignore"
    lock_path = tmp_path / "cobo.lock"
    record_dump(
        source=source,
        clone_root=clone,
        names=["Python"],
        out_path=out,
        lock_path=lock_path,
        commit_sha=current_commit_sha(clone),
    )
    lock = read_lock(lock_path)
    assert len(lock.fragments) == 1
    frag = lock.fragments[0]
    assert frag.path == ".gitignore"
    assert frag.source == "gi"
    assert frag.files[0].name == "Python"
    assert frag.files[0].path == "Python.gitignore"
    assert len(frag.files[0].blob) == 40  # noqa: PLR2004


def test_dump_lock_without_out_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --lock` without `--out` is a usage error (exit 2)."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", "Python", "--lock"])
    assert result.exit_code == 2, result.output  # noqa: PLR2004


def test_dump_out_and_lock_writes_file_and_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --out FILE --lock` writes the file and records it in cobo.lock."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", "Python", "--out", str(out), "--lock"])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == "*.pyc\n"
    lock = read_lock(tmp_path / "cobo.lock")
    assert lock.fragments[0].path == ".gitignore"
    assert lock.fragments[0].files[0].name == "Python"
