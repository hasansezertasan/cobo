"""Frozen dataclasses describing the cobo.lock contents."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A full git object name: 40 hex chars (SHA-1) or 64 (SHA-256). Abbreviated or
# malformed SHAs never match the resolved full SHA and would read as permanent
# phantom drift, so they are rejected at construction.
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


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
    commit: str
    blob: str

    def __post_init__(self) -> None:
        """Validate field non-emptiness and SHA format at construction.

        Raises:
            ValueError: When ``name``/``path`` are empty or ``commit``/``blob``
                are not full hex SHAs.
        """
        if not self.name:
            msg = "LockedFile.name must be non-empty"
            raise ValueError(msg)
        if not self.path:
            msg = "LockedFile.path must be non-empty"
            raise ValueError(msg)
        for label, sha in (("commit", self.commit), ("blob", self.blob)):
            if not _SHA_RE.fullmatch(sha):
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
            ValueError: When ``path``/``source`` are empty or ``files`` is empty
                (a fragment with no inputs would render nothing).
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
        """Reject a version below 1 (the exact gate lives in read_lock).

        Raises:
            ValueError: When ``version`` is below 1. The exact supported version
                is enforced separately on the read path (see ``read_lock``).
        """
        if self.version < 1:
            msg = f"Lockfile.version must be >= 1, got {self.version}"
            raise ValueError(msg)
