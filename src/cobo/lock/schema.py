"""Frozen dataclasses describing the cobo.lock contents."""

from __future__ import annotations

from dataclasses import dataclass, field


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


@dataclass(frozen=True, slots=True)
class Lockfile:
    """The whole cobo.lock document.

    Attributes:
        version: Lockfile schema version (currently 1).
        fragments: Tracked output files.
    """

    version: int
    fragments: tuple[Fragment, ...] = field(default_factory=tuple)
