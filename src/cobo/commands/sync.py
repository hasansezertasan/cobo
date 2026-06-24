"""Apply fragment updates in place and advance the lockfile (`cobo sync`)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from cobo.commands.check import run_check
from cobo.errors import CoboError
from cobo.lock.io import write_lock
from cobo.lock.schema import Fragment, LockedFile, Lockfile
from cobo.sources.render import dump_locked as render_dump_locked
from cobo.sources.repo import blob_sha_for_path, current_commit_sha

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from cobo.commands.check import CheckResult, CloneRootProvider
    from cobo.config.schema import Source


@dataclass(frozen=True, slots=True)
class FailedFragment:
    """A fragment that could not be synced, with the reason it failed.

    Attributes:
        path: Output path of the fragment.
        reason: Human-readable cause (the underlying error message).
    """

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Outcome of a sync run.

    Attributes:
        changed: Output paths that were (or, in dry-run, would be) rewritten.
        failed: Fragments that errored during re-render, each with its reason.
        check: The underlying CheckResult that drove the sync.
    """

    changed: tuple[str, ...]
    failed: tuple[FailedFragment, ...]
    check: CheckResult

    def __post_init__(self) -> None:
        """Enforce that no fragment is both changed and failed.

        Raises:
            ValueError: When a path appears in both ``changed`` and ``failed``.
        """
        overlap = set(self.changed) & {f.path for f in self.failed}
        if overlap:
            msg = f"fragments cannot be both changed and failed: {sorted(overlap)}"
            raise ValueError(msg)


def run_sync(  # noqa: C901,PLR0913
    lock: Lockfile,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    *,
    lock_dir: Path,
    lock_path: Path,
    dry_run: bool = False,
    refresh: bool = True,
) -> SyncResult:
    """Re-render outdated fragments and advance the lockfile.

    Args:
        lock: The parsed lockfile.
        sources: Resolved sources keyed by name.
        clone_root_provider: Maps a Source to its clone path.
        lock_dir: Directory the fragment output paths are relative to.
        lock_path: Where to write the updated lockfile.
        dry_run: When True, compute changes but write nothing.
        refresh: Forwarded to the underlying check (refresh clones).

    Returns:
        A SyncResult describing changed/failed fragments.
    """
    result = run_check(lock, sources, clone_root_provider, refresh=refresh)
    changed: list[str] = []
    failed: list[FailedFragment] = []
    new_fragments: list[Fragment] = []
    for frag, report in zip(lock.fragments, result.reports, strict=True):
        if report.error is not None:
            failed.append(FailedFragment(path=frag.path, reason=report.error))
            new_fragments.append(frag)
            continue
        if not report.outdated:
            new_fragments.append(frag)
            continue
        try:
            rebuilt = _rerender(
                frag,
                sources[frag.source],
                clone_root_provider,
                lock_dir,
                dry_run=dry_run,
            )
        except (CoboError, OSError) as exc:
            failed.append(FailedFragment(path=frag.path, reason=str(exc)))
            new_fragments.append(frag)
            continue
        changed.append(frag.path)
        new_fragments.append(rebuilt)
    if changed and not dry_run:
        write_lock(
            lock_path,
            Lockfile(version=lock.version, fragments=tuple(new_fragments)),
        )
    return SyncResult(changed=tuple(changed), failed=tuple(failed), check=result)


def _rerender(
    frag: Fragment,
    source: Source,
    clone_root_provider: CloneRootProvider,
    lock_dir: Path,
    *,
    dry_run: bool,
) -> Fragment:
    """Re-render one fragment's output and return its advanced lock entry.

    Propagates ``CoboError`` or ``OSError`` from ``render_dump_locked``,
    ``blob_sha_for_path``, or the file write when a file has been removed
    upstream, the clone is unreadable, or the output path is unwritable.

    Returns:
        The fragment with each file's commit/blob refreshed to the clone HEAD.
    """
    clone_root = clone_root_provider(source)
    commit = current_commit_sha(clone_root)
    repo_rel_paths = [f.path for f in frag.files]
    content = render_dump_locked(source, clone_root, repo_rel_paths, commit)
    if not dry_run:
        (lock_dir / frag.path).write_bytes(content.encode("utf-8"))
    new_files = tuple(
        LockedFile(
            name=f.name,
            path=f.path,
            commit=commit,
            blob=blob_sha_for_path(clone_root, f.path),
        )
        for f in frag.files
    )
    return replace(frag, files=new_files)
