"""Git clone and pull operations for a single source."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from cobo.errors import ConfigError, FileAbsentError, GitError
from cobo.lock.schema import BlobSha, CommitSha

if TYPE_CHECKING:
    from pathlib import Path

    from cobo.config.schema import Source


_REMOTE_NAME = "origin"
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _validate_branch(branch: str) -> None:
    """Reject branch names that could be interpreted as git CLI options.

    Raises:
        ConfigError: When the branch is empty, starts with ``-``, or contains
            characters outside the conservative allow-list.
    """
    if not branch or branch.startswith("-") or not _BRANCH_RE.fullmatch(branch):
        msg = f"Invalid branch name: '{branch}'"
        raise ConfigError(msg)


def clone_or_pull(source: Source, clone_root: Path) -> None:
    """Clone the source repo if absent, otherwise pull the configured branch.

    Args:
        source: Source whose url/branch to operate on.
        clone_root: Local path to clone into / pull within.

    Raises:
        GitError: Wrapping any git-layer failure (command errors, invalid
            existing clone directories, or missing paths).
    """
    _validate_branch(source.branch)
    try:
        if clone_root.exists():
            _pull(clone_root, source.branch)
            return
        clone_root.parent.mkdir(parents=True, exist_ok=True)
        Repo.clone_from(
            url=source.url,
            to_path=clone_root,
            branch=source.branch,
            depth=1,
            single_branch=True,
        )
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError) as exc:
        msg = f"git operation failed for source '{source.name}': {exc}"
        raise GitError(msg) from exc


def _pull(clone_root: Path, branch: str) -> None:
    """Fetch origin and hard-reset the local checkout to the configured branch.

    The cache clone is treated as disposable: any local modifications,
    untracked files, or divergent commits inside ``clone_root`` are discarded
    when the branch is force-recreated at ``FETCH_HEAD``.
    """
    repo = Repo(clone_root)
    origin = repo.remote(name=_REMOTE_NAME)
    origin.fetch(refspec=branch, depth=1)
    repo.git.checkout("-B", branch, "FETCH_HEAD")
    repo.git.reset("--hard", "FETCH_HEAD")
    repo.git.clean("-fdx")


def current_commit_sha(clone_root: Path) -> CommitSha:
    """Return HEAD's full SHA for an existing clone.

    Raises:
        GitError: When ``clone_root`` is not a valid git repository.
    """
    try:
        repo = Repo(clone_root)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        msg = f"not a git repository: {clone_root}"
        raise GitError(msg) from exc
    return CommitSha(repo.head.commit.hexsha)


def blob_sha_for_path(clone_root: Path, repo_path: str) -> BlobSha:
    """Return the blob SHA of ``repo_path`` at the clone's HEAD.

    Uses ``git rev-parse HEAD:<path>``, which works on a shallow (depth-1)
    clone and is content-addressed: the SHA changes iff the file content
    changes. This is the drift key for fragment updates.

    Args:
        clone_root: Path to an existing source clone.
        repo_path: Repo-relative POSIX path of the file at HEAD.

    Returns:
        The full hex blob SHA (40 chars for SHA-1 repos, 64 for SHA-256).

    Raises:
        FileAbsentError: When ``repo_path`` does not exist at HEAD (the file was
            removed upstream) — a legitimate drift signal. Note this is a
            subclass of ``GitError``, so callers that need to treat absence
            differently must catch ``FileAbsentError`` *before* ``GitError``.
        GitError: When the clone itself is invalid or missing (an infrastructure
            failure, not a deletion).
    """
    try:
        repo = Repo(clone_root)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        msg = f"could not resolve blob for '{repo_path}' in {clone_root}: {exc}"
        raise GitError(msg) from exc
    try:
        return BlobSha(str(repo.git.rev_parse(f"HEAD:{repo_path}")))
    except GitCommandError as exc:
        msg = f"path '{repo_path}' is absent at HEAD in {clone_root}: {exc}"
        raise FileAbsentError(msg) from exc
