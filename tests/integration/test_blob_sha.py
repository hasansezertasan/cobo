"""Tests for blob_sha_for_path against a real local clone."""

from __future__ import annotations

import subprocess  # noqa: S404
from typing import TYPE_CHECKING

import pytest
from git import GitCommandError

from cobo.config.schema import Source
from cobo.errors import FileAbsentError, GitError
from cobo.sources import repo as repo_module
from cobo.sources.repo import blob_sha_for_path, clone_or_pull

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],  # noqa: S607
        check=True,
    )


def _make_bare_repo(tmp_path: Path) -> Path:
    upstream = tmp_path / "upstream.git"
    seed = tmp_path / "seed"
    (seed / "Global").mkdir(parents=True)
    (seed / "Python.gitignore").write_text("*.pyc\n", encoding="utf-8")
    (seed / "Global" / "macOS.gitignore").write_text("Icon\r\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)  # noqa: S603, S607
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "seed")
    subprocess.run(  # noqa: S603
        ["git", "init", "-q", "--bare", "-b", "main", str(upstream)],  # noqa: S607
        check=True,
    )
    _git(seed, "remote", "add", "origin", str(upstream))
    _git(seed, "push", "-q", "origin", "main")
    return upstream


def test_blob_sha_matches_git_rev_parse(tmp_path: Path) -> None:
    """blob_sha_for_path equals `git rev-parse HEAD:<path>`."""
    upstream = _make_bare_repo(tmp_path)
    clone = tmp_path / "clone"
    clone_or_pull(
        Source(name="x", url=str(upstream), extension=".gitignore", branch="main"),
        clone,
    )
    got = blob_sha_for_path(clone, "Python.gitignore")
    expected = subprocess.run(  # noqa: S603
        ["git", "-C", str(clone), "rev-parse", "HEAD:Python.gitignore"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert got == expected


def test_blob_sha_resolves_nested_path(tmp_path: Path) -> None:
    """Nested paths (the old URL-bug case) resolve correctly."""
    upstream = _make_bare_repo(tmp_path)
    clone = tmp_path / "clone"
    clone_or_pull(
        Source(name="x", url=str(upstream), extension=".gitignore", branch="main"),
        clone,
    )
    assert blob_sha_for_path(clone, "Global/macOS.gitignore")


def test_blob_sha_missing_path_raises_file_absent(tmp_path: Path) -> None:
    """A path absent from HEAD raises FileAbsentError (a GitError subclass)."""
    upstream = _make_bare_repo(tmp_path)
    clone = tmp_path / "clone"
    clone_or_pull(
        Source(name="x", url=str(upstream), extension=".gitignore", branch="main"),
        clone,
    )
    with pytest.raises(FileAbsentError):
        blob_sha_for_path(clone, "Nope.gitignore")


def test_blob_sha_invalid_clone_raises_git_error(tmp_path: Path) -> None:
    """A non-repository path raises plain GitError, not FileAbsentError."""
    not_a_repo = tmp_path / "empty"
    not_a_repo.mkdir()
    with pytest.raises(GitError) as exc_info:
        blob_sha_for_path(not_a_repo, "Python.gitignore")
    assert not isinstance(exc_info.value, FileAbsentError)


def test_blob_sha_other_rev_parse_failure_raises_git_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-absence rev-parse failure surfaces as GitError, not FileAbsentError.

    A corrupt object or ambiguous ref must not be misread as "file removed
    upstream", which would register as phantom drift.
    """

    class _FakeGit:
        @staticmethod
        def rev_parse(_arg: str) -> str:
            raise GitCommandError(["git", "rev-parse"], 128, b"fatal: bad object HEAD")

    class _FakeRepo:
        def __init__(self, _path: object) -> None:
            self.git = _FakeGit()

    monkeypatch.setattr(repo_module, "Repo", _FakeRepo)
    with pytest.raises(GitError) as exc_info:
        blob_sha_for_path(tmp_path, "hello.gitignore")
    assert not isinstance(exc_info.value, FileAbsentError)
