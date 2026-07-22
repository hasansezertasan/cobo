"""Apply fragment updates in place and advance the lockfile (`cobo sync`)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from cobo.commands.check import run_check
from cobo.errors import GitError, UserError
from cobo.exit_codes import ExitCode
from cobo.lock.io import write_lock
from cobo.lock.schema import Fragment, LockedFile, Lockfile
from cobo.sources import managed
from cobo.sources.render import dump_locked as render_dump_locked
from cobo.sources.repo import blob_sha_for_path, current_commit_sha

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
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

    def __post_init__(self) -> None:
        """Reject an empty path or reason.

        Raises:
            ValueError: When ``path`` or ``reason`` is empty (a failure with no
                cause is not actionable).
        """
        if not self.path:
            msg = "FailedFragment.path must be non-empty"
            raise ValueError(msg)
        if not self.reason:
            msg = "FailedFragment.reason must be non-empty"
            raise ValueError(msg)


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

    @property
    def exit_code(self) -> ExitCode:
        """Map this result to a process exit code.

        Returns:
            ``ExitCode.FAILURE`` when any fragment failed to re-render;
            ``ExitCode.OK`` otherwise (including a clean sync that applied
            updates — sync does not fail merely because work was done).
        """
        return ExitCode.FAILURE if self.failed else ExitCode.OK


def run_sync(  # noqa: C901,PLR0913
    lock: Lockfile,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    *,
    lock_dir: Path,
    lock_path: Path,
    dry_run: bool = False,
    refresh: bool = True,
    force: bool = False,
    exclude: Sequence[str] = (),
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
        force: When True, overwrite a locally edited managed block instead of
            refusing, and rebuild a file whose markers are missing/malformed.
        exclude: Glob patterns; matching fragments are left untouched in both
            the working tree and the rewritten lockfile.

    Returns:
        A SyncResult describing changed/failed fragments.

    Raises:
        UserError: When fragment outputs were rewritten but the lockfile could
            not be written back (a partial update the caller must surface).
    """
    result = run_check(
        lock, sources, clone_root_provider, refresh=refresh, exclude=exclude
    )
    # Each report already carries its fragment's output path (unique per
    # lockfile), so key directly off the reports. Excluded fragments are absent
    # from the reports and fall through the ``.get`` below to be preserved.
    report_by_path = {report.path: report for report in result.reports}
    changed: list[str] = []
    failed: list[FailedFragment] = []
    new_fragments: list[Fragment] = []
    for frag in lock.fragments:
        report = report_by_path.get(frag.path)
        if report is None:  # excluded — carry the entry through unchanged
            new_fragments.append(frag)
            continue
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
                force=force,
            )
        except (UserError, GitError, OSError) as exc:
            failed.append(FailedFragment(path=frag.path, reason=str(exc)))
            new_fragments.append(frag)
            continue
        changed.append(frag.path)
        new_fragments.append(rebuilt)
    if changed and not dry_run:
        try:
            write_lock(
                lock_path,
                Lockfile(version=lock.version, fragments=tuple(new_fragments)),
            )
        except OSError as exc:
            # The fragment outputs are already rewritten on disk, but the lock
            # never advanced. Surface that partial state instead of crashing
            # with a raw traceback so `check` does not report perpetual drift
            # without explanation.
            msg = (
                f"Re-rendered {len(changed)} fragment(s) but could not update "
                f"{lock_path}: {exc}. The working tree was modified; re-run "
                f"`cobo sync` once the lockfile is writable."
            )
            raise UserError(msg) from exc
    return SyncResult(changed=tuple(changed), failed=tuple(failed), check=result)


def _rerender(  # noqa: PLR0913
    frag: Fragment,
    source: Source,
    clone_root_provider: CloneRootProvider,
    lock_dir: Path,
    *,
    dry_run: bool,
    force: bool,
) -> Fragment:
    """Re-render one fragment's output and return its advanced lock entry.

    The freshly rendered content is woven back into the existing file's managed
    block (``managed.weave``), preserving any user content outside it. A locally
    edited block, or missing/malformed markers, raises ``ManagedBlockError``
    unless ``force`` is set.

    Propagates ``UserError`` (including ``ManagedBlockError``), ``GitError``
    (including ``FileAbsentError``), or ``OSError`` from ``render_dump_locked``,
    ``managed.weave``, ``blob_sha_for_path``, or the file write when the block
    was edited, a file was removed upstream, the clone is unreadable, or the
    output path is unwritable. An unexpected ``CoboError`` subtype is *not*
    caught here, so a genuine defect surfaces rather than being absorbed into a
    per-fragment failure.

    Returns:
        The fragment with each file's commit/blob refreshed to the clone HEAD.
    """
    clone_root = clone_root_provider(source)
    commit = current_commit_sha(clone_root)
    repo_rel_paths = [f.path for f in frag.files]
    content = render_dump_locked(source, clone_root, repo_rel_paths, commit)
    target = lock_dir / frag.path
    # Decode bytes directly to preserve an embedded ``\r`` (e.g. macOS's
    # ``Icon\r``); read_text would translate it and read as a tampered block.
    existing = target.read_bytes().decode("utf-8") if target.exists() else None
    # Weave first (even in dry-run) so a refusal surfaces before anything is
    # written; only the write itself is skipped under dry-run.
    payload = managed.weave(existing, content, source.comment_prefix, force=force)
    if not dry_run:
        target.write_bytes(payload.encode("utf-8"))
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
