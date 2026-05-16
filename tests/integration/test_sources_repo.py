"""Tests for the git layer (no network: uses local bare repos in tmp_path)."""

from __future__ import annotations

import subprocess  # noqa: S404
from typing import TYPE_CHECKING

import pytest

from cobo.config.schema import Source
from cobo.errors import ConfigError, GitError
from cobo.sources.repo import clone_or_pull, current_commit_sha

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_MIN_SHA_LENGTH = 7


def _make_bare_repo(tmp_path: Path) -> Path:
    """Create a local bare repo with one commit; return its path.

    Returns:
        Path to the bare upstream repo.
    """
    upstream = tmp_path / "upstream.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)  # noqa: S603, S607
    (seed / "hello.gitignore").write_text("*.tmp\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(seed), "add", "."], check=True)  # noqa: S603, S607
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(seed),
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
    subprocess.run(  # noqa: S603
        ["git", "init", "-q", "--bare", "-b", "main", str(upstream)],  # noqa: S607
        check=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(seed), "remote", "add", "origin", str(upstream)],  # noqa: S607
        check=True,
    )
    subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "main"], check=True)  # noqa: S603, S607
    return upstream


def test_clone_creates_clone_dir_when_absent(tmp_path: Path) -> None:
    """clone_or_pull clones a missing repo."""
    upstream = _make_bare_repo(tmp_path)
    clone_to = tmp_path / "clone"
    source = Source(name="x", url=str(upstream), extension=".gitignore", branch="main")
    clone_or_pull(source, clone_to)
    assert (clone_to / "hello.gitignore").is_file()


def test_pull_updates_existing_clone(tmp_path: Path) -> None:
    """A second call pulls without re-cloning."""
    upstream = _make_bare_repo(tmp_path)
    clone_to = tmp_path / "clone"
    source = Source(name="x", url=str(upstream), extension=".gitignore", branch="main")
    clone_or_pull(source, clone_to)
    clone_or_pull(source, clone_to)  # second call must not raise
    assert (clone_to / "hello.gitignore").is_file()


def test_unreachable_url_raises_git_error(tmp_path: Path) -> None:
    """A non-existent upstream raises GitError."""
    source = Source(
        name="x",
        url=str(tmp_path / "does-not-exist.git"),
        extension=".gitignore",
    )
    with pytest.raises(GitError):
        clone_or_pull(source, tmp_path / "clone")


def test_existing_dir_not_a_repo_raises_git_error(tmp_path: Path) -> None:
    """A pre-existing non-repo directory at clone_root is wrapped as GitError."""
    upstream = _make_bare_repo(tmp_path)
    clone_to = tmp_path / "clone"
    clone_to.mkdir()
    (clone_to / "junk.txt").write_text("not a repo")
    source = Source(name="x", url=str(upstream), extension=".gitignore", branch="main")
    with pytest.raises(GitError):
        clone_or_pull(source, clone_to)


def test_pull_honors_configured_branch_after_change(tmp_path: Path) -> None:
    """Changing source.branch between calls re-checks-out the new branch."""
    upstream = _make_bare_repo(tmp_path)
    # Add a second branch upstream with a distinct file.
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(upstream), str(work)], check=True)  # noqa: S603, S607
    subprocess.run(  # noqa: S603
        ["git", "-C", str(work), "checkout", "-q", "-b", "other"],  # noqa: S607
        check=True,
    )
    (work / "other.gitignore").write_text("*.log\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)  # noqa: S603, S607
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(work),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "other",
        ],
        check=True,
    )
    subprocess.run(  # noqa: S603
        ["git", "-C", str(work), "push", "-q", "origin", "other"],  # noqa: S607
        check=True,
    )

    clone_to = tmp_path / "clone"
    clone_or_pull(
        Source(name="x", url=str(upstream), extension=".gitignore", branch="main"),
        clone_to,
    )
    assert (clone_to / "hello.gitignore").is_file()
    assert not (clone_to / "other.gitignore").exists()

    clone_or_pull(
        Source(name="x", url=str(upstream), extension=".gitignore", branch="other"),
        clone_to,
    )
    assert (clone_to / "other.gitignore").is_file()


def test_current_commit_sha_raises_git_error_for_non_repo(tmp_path: Path) -> None:
    """current_commit_sha wraps InvalidGitRepositoryError as GitError."""
    bogus = tmp_path / "not-a-repo"
    bogus.mkdir()
    with pytest.raises(GitError):
        current_commit_sha(bogus)


def test_current_commit_sha_returns_short_hex(tmp_path: Path) -> None:
    """current_commit_sha returns the HEAD SHA of the clone."""
    upstream = _make_bare_repo(tmp_path)
    clone_to = tmp_path / "clone"
    source = Source(name="x", url=str(upstream), extension=".gitignore", branch="main")
    clone_or_pull(source, clone_to)
    sha = current_commit_sha(clone_to)
    assert len(sha) >= _MIN_SHA_LENGTH
    assert all(c in "0123456789abcdef" for c in sha)


def test_pull_discards_local_modifications_in_clone(tmp_path: Path) -> None:
    """The cache clone is disposable: local edits are discarded on pull."""
    upstream = _make_bare_repo(tmp_path)
    clone_to = tmp_path / "clone"
    source = Source(name="x", url=str(upstream), extension=".gitignore", branch="main")
    clone_or_pull(source, clone_to)
    tampered = clone_to / "hello.gitignore"
    tampered.write_text("TAMPERED\n", encoding="utf-8")
    clone_or_pull(source, clone_to)
    assert tampered.read_text(encoding="utf-8") == "*.tmp\n"


@pytest.mark.parametrize("bad_branch", ["", "-rf", "--upload-pack=evil", "with space"])
def test_invalid_branch_raises_config_error(tmp_path: Path, bad_branch: str) -> None:
    """Branch names that could be interpreted as CLI options are rejected."""
    upstream = _make_bare_repo(tmp_path)
    clone_to = tmp_path / "clone"
    source = Source(
        name="x", url=str(upstream), extension=".gitignore", branch=bad_branch
    )
    with pytest.raises(ConfigError):
        clone_or_pull(source, clone_to)
