"""Frozen dataclasses describing the cobo.lock contents."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import NewType

# Distinct names for the two git object kinds stored per file. They are plain
# strings at runtime, but the aliases make a commit/blob mix-up a type error
# rather than a silent, content-addressed bug.
CommitSha = NewType("CommitSha", str)
BlobSha = NewType("BlobSha", str)

# A full git object name: 40 hex chars (SHA-1) or 64 (SHA-256). Abbreviated or
# malformed SHAs never match the resolved full SHA and would read as permanent
# phantom drift, so they are rejected at construction.
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def is_full_sha(value: str) -> bool:
    """Whether ``value`` is a full lowercase hex git object name (40 or 64).

    Returns:
        True for a 40-char (SHA-1) or 64-char (SHA-256) lowercase hex string.
    """
    return _SHA_RE.fullmatch(value) is not None


def _validate_repo_rel_path(path: str) -> None:
    """Reject an empty, absolute, or non-POSIX (backslash) repo-relative path.

    Raises:
        ValueError: When ``path`` is empty, absolute, or contains a backslash.
    """
    if not path:
        msg = "LockedFile.path must be non-empty"
        raise ValueError(msg)
    if path.startswith("/") or "\\" in path:
        msg = f"LockedFile.path must be a repo-relative POSIX path, got {path!r}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class LockedFile:
    """One input file that contributed to a dumped fragment.

    Attributes:
        name: The boilerplate name as dumped (e.g. "Python").
        path: Repo-relative POSIX path inside the source clone.
        commit: Full SHA the file was rendered from (provenance/header URL).
        blob: Blob SHA at that commit; the content-addressed drift key.
    """

    name: str
    path: str
    commit: CommitSha
    blob: BlobSha

    def __post_init__(self) -> None:
        """Validate field non-emptiness and SHA format at construction.

        Raises:
            ValueError: When ``name``/``path`` are empty, ``path`` is not a
                repo-relative POSIX path, or ``commit``/``blob`` are not full
                hex SHAs.
        """
        if not self.name:
            msg = "LockedFile.name must be non-empty"
            raise ValueError(msg)
        _validate_repo_rel_path(self.path)
        for label, sha in (("commit", self.commit), ("blob", self.blob)):
            if not is_full_sha(sha):
                msg = f"LockedFile.{label} must be a full hex SHA, got {sha!r}"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Fragment:
    """One output file produced by cobo, tracked for updates.

    Attributes:
        path: Output path, relative to the lockfile's directory.
        source: Name of the source the inputs came from.
        files: The input files concatenated into this output, in order.
        update: When False, check/sync skip this fragment (held back).
    """

    path: str
    source: str
    files: tuple[LockedFile, ...]
    update: bool = True

    def __post_init__(self) -> None:
        """Reject empty path/source and fragments that track no input files.

        Raises:
            ValueError: When ``path``/``source`` are empty, ``files`` is empty
                (a fragment with no inputs would render nothing), or two files
                share the same ``path``.
        """
        if not self.path:
            msg = "Fragment.path must be non-empty"
            raise ValueError(msg)
        if not self.source:
            msg = "Fragment.source must be non-empty"
            raise ValueError(msg)
        if not self.files:
            msg = f"Fragment {self.path!r} must track at least one file"
            raise ValueError(msg)
        file_paths = [f.path for f in self.files]
        if len(set(file_paths)) != len(file_paths):
            dupes = sorted({p for p in file_paths if file_paths.count(p) > 1})
            msg = f"Fragment {self.path!r} has duplicate file paths: {dupes}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Lockfile:
    """The whole cobo.lock document.

    Attributes:
        version: Lockfile schema version (currently 1).
        fragments: Tracked output files.
    """

    version: int
    fragments: tuple[Fragment, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Reject a version below 1 and duplicate fragment paths.

        Raises:
            ValueError: When ``version`` is below 1, or two fragments share the
                same ``path`` (the output path is the fragment's primary key, as
                relied on by ``upsert_fragment`` and check/sync lookups). The
                exact supported version is enforced separately on the read path
                (see ``read_lock``).
        """
        if self.version < 1:
            msg = f"Lockfile.version must be >= 1, got {self.version}"
            raise ValueError(msg)
        paths = [f.path for f in self.fragments]
        if len(set(paths)) != len(paths):
            dupes = sorted({p for p in paths if paths.count(p) > 1})
            msg = f"duplicate fragment paths in lockfile: {dupes}"
            raise ValueError(msg)
