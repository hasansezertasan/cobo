"""Assemble and persist a lockfile fragment for `dump --lock`."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from cobo.eol import PRESERVE
from cobo.errors import ConfigError, UserError
from cobo.lock.io import (
    LOCK_FILENAME,
    empty_lock,
    find_lock,
    read_lock,
    upsert_fragment,
    write_lock,
)
from cobo.lock.schema import CommitSha, Fragment, LockedFile
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
    commit_sha: CommitSha,
    eol: str | None = None,
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
        eol: Line-ending policy the block was sealed with, persisted so
            ``sync`` re-applies it ("preserve" or "lf"). ``None`` keeps the
            existing fragment's policy (or "preserve" for a new fragment) — so
            ``lock import``, which does not rewrite the file, never downgrades
            an ``lf`` fragment, mirroring how ``update`` is preserved.

    Propagates ``UserError`` from ``_relative_output_path`` when the output and
    the lockfile are on different drives (Windows), so no relative path links
    them.
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
    rel_out_posix = _relative_output_path(out_path, lock_path)
    base = read_lock(lock_path) if lock_path.exists() else empty_lock()
    existing = next((f for f in base.fragments if f.path == rel_out_posix), None)
    preserved_update = existing.update if existing is not None else True
    # eol=None means "don't change the policy": keep the existing fragment's
    # (or default to preserve for a new one). An explicit value overrides.
    effective_eol = (
        eol if eol is not None else (existing.eol if existing is not None else PRESERVE)
    )
    fragment = Fragment(
        path=rel_out_posix,
        source=source.name,
        files=tuple(files),
        update=preserved_update,
        eol=effective_eol,
    )
    write_lock(lock_path, upsert_fragment(base, fragment))


def _relative_output_path(out_path: Path, lock_path: Path) -> str:
    """Return ``out_path`` as a POSIX path relative to the lockfile's directory.

    Raises:
        UserError: When the output and the lockfile sit on different drives
            (Windows), so no relative path between them exists.
    """
    try:
        rel_out = os.path.relpath(out_path.resolve(), lock_path.parent.resolve())
    except ValueError as exc:
        msg = (
            f"Cannot record '{out_path}' in {lock_path}: the output and the"
            " lockfile are on different drives, so no relative path links them."
            " Place cobo.lock on the same drive as the output file."
        )
        raise UserError(msg) from exc
    return rel_out.replace(os.sep, "/")


def existing_fragment_eol(lock_path: Path, out_path: Path) -> str | None:
    """Return the EOL policy already recorded for ``out_path``, or None.

    Used by ``dump`` so that omitting ``--eol`` keeps the policy the fragment
    was last sealed with (mirroring how ``update`` is preserved) rather than
    silently resetting it to the CLI default. A missing or unreadable lock, or
    an untracked output, yields None (the caller then defaults to preserve); a
    genuinely malformed lock is surfaced later by ``record_dump``'s own read.

    Returns:
        The recorded ``eol`` string, or None when there is no matching fragment.
    """
    if not lock_path.exists():
        return None
    try:
        base = read_lock(lock_path)
        rel_out_posix = _relative_output_path(out_path, lock_path)
    except ConfigError, UserError:
        return None
    return next((f.eol for f in base.fragments if f.path == rel_out_posix), None)


def resolve_lock_path(start: Path, override: Path | None = None) -> Path:
    """Return the lockfile path to write.

    Args:
        start: Directory to begin discovery from (usually the cwd).
        override: An explicit path (from ``--lock-file`` / ``COBO_LOCK``) that
            bypasses discovery entirely.

    Returns:
        ``override`` when given; otherwise the nearest existing cobo.lock above
        ``start`` (bounded by the repo root), or ``start/cobo.lock``.
    """
    if override is not None:
        return override
    found = find_lock(start)
    return found if found is not None else start / LOCK_FILENAME
