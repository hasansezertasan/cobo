"""Assemble and persist a lockfile fragment for `dump --lock`."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from cobo.lock.io import (
    LOCK_FILENAME,
    empty_lock,
    find_lock,
    read_lock,
    upsert_fragment,
    write_lock,
)
from cobo.lock.schema import Fragment, LockedFile
from cobo.sources.discover import find_boilerplate
from cobo.sources.repo import blob_sha_for_path

if TYPE_CHECKING:
    from pathlib import Path

    from cobo.config.schema import Source


def record_dump(  # noqa: PLR0913
    *,
    source: Source,
    clone_root: Path,
    names: list[str],
    out_path: Path,
    lock_path: Path,
    commit_sha: str,
) -> None:
    """Upsert a fragment for a just-written dump into the lockfile.

    The fragment's output ``path`` is stored relative to the lockfile's
    directory so the lock is portable across checkouts.

    Args:
        source: The source dumped from.
        clone_root: The source clone the files were rendered from.
        names: Boilerplate names included in the output, in order.
        out_path: The file the dump was written to.
        lock_path: Where the lockfile lives (created if absent).
        commit_sha: Full HEAD SHA of the clone at render time.
    """
    files: list[LockedFile] = []
    for name in names:
        path = find_boilerplate(source, clone_root, name)
        repo_rel = path.relative_to(clone_root).as_posix()
        files.append(
            LockedFile(
                name=name,
                path=repo_rel,
                commit=commit_sha,
                blob=blob_sha_for_path(clone_root, repo_rel),
            )
        )
    rel_out = os.path.relpath(out_path.resolve(), lock_path.parent.resolve())
    fragment = Fragment(
        path=rel_out.replace(os.sep, "/"),
        source=source.name,
        files=tuple(files),
    )
    base = read_lock(lock_path) if lock_path.exists() else empty_lock()
    write_lock(lock_path, upsert_fragment(base, fragment))


def resolve_lock_path(start: Path) -> Path:
    """Return the lockfile path to write: an existing one upward, else here.

    Returns:
        The nearest existing cobo.lock above ``start``, or ``start/cobo.lock``.
    """
    found = find_lock(start)
    return found if found is not None else start / LOCK_FILENAME
