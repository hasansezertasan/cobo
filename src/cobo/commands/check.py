"""Drift detection across all tracked fragments (the `cobo check` core)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from cobo.errors import FileAbsentError, GitError
from cobo.exit_codes import ExitCode
from cobo.lock.diff import compute_fragment_drift
from cobo.sources import managed
from cobo.sources.managed import BlockState
from cobo.sources.repo import blob_sha_for_path, clone_or_pull

if TYPE_CHECKING:
    from collections.abc import Mapping

    from cobo.config.schema import Source
    from cobo.lock.diff import FileDrift
    from cobo.lock.schema import BlobSha, Fragment, Lockfile

CloneRootProvider = Callable[(["Source"], Path)]

# On-disk block states that ``managed.weave`` refuses (so ``sync`` needs
# ``--force``). ABSENT is excluded — ``sync`` simply recreates a missing file.
_SYNC_BLOCKED_STATES = frozenset({
    BlockState.MODIFIED,
    BlockState.MALFORMED,
    BlockState.MISSING,
})


def is_excluded(path: str, patterns: Sequence[str]) -> bool:
    """Whether ``path`` matches any of the glob ``patterns``.

    Args:
        path: A fragment output path (relative to the lockfile directory).
        patterns: Glob patterns (``fnmatch`` syntax) to test against.

    Returns:
        True when ``path`` matches at least one pattern.
    """
    return any(fnmatch(path, pattern) for pattern in patterns)


def selected_fragments(lock: Lockfile, exclude: Sequence[str]) -> list[Fragment]:
    """Return the fragments not filtered out by ``exclude``.

    Args:
        lock: The parsed lockfile.
        exclude: Glob patterns; fragments whose path matches are dropped.

    Returns:
        Lockfile fragments, in order, whose path matches no exclude pattern.
    """
    return [frag for frag in lock.fragments if not is_excluded(frag.path, exclude)]


@dataclass(frozen=True, slots=True)
class FragmentReport:
    """Per-fragment outcome of a check.

    Attributes:
        path: Output path of the fragment.
        source: Source name.
        held: True when update=False (skipped).
        drifts: Files whose content changed (empty when clean or held).
        error: Non-None when the fragment could not be evaluated.
        local_state: On-disk managed-block state, or None when not evaluated
            (held, errored, or the check ran without a lock directory).
    """

    path: str
    source: str
    held: bool
    drifts: tuple[FileDrift, ...]
    error: str | None = None
    local_state: BlockState | None = None

    def __post_init__(self) -> None:
        """Enforce that held / errored / drifted are mutually exclusive states.

        Raises:
            ValueError: When ``path``/``source`` are empty, or the report mixes
                states that cannot co-occur (a held report with an error or
                drifts, or an errored report that also carries drifts).
        """
        if not self.path:
            msg = "FragmentReport.path must be non-empty"
            raise ValueError(msg)
        if not self.source:
            msg = "FragmentReport.source must be non-empty"
            raise ValueError(msg)
        if self.held and (self.error is not None or self.drifts):
            msg = "a held FragmentReport cannot also have an error or drifts"
            raise ValueError(msg)
        if self.error is not None and self.drifts:
            msg = "an errored FragmentReport cannot also have drifts"
            raise ValueError(msg)

    @property
    def outdated(self) -> bool:
        """Whether this fragment needs an update.

        Returns:
            True when not held, not errored, and at least one file drifted.
        """
        return not self.held and self.error is None and bool(self.drifts)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Aggregate result of checking every fragment.

    Attributes:
        reports: One report per fragment, in lockfile order.
    """

    reports: tuple[FragmentReport, ...]

    @property
    def outdated_count(self) -> int:
        """Number of fragments that need updating.

        Returns:
            Count of reports whose ``outdated`` is True.
        """
        return sum(1 for r in self.reports if r.outdated)

    @property
    def error_count(self) -> int:
        """Number of fragments that could not be evaluated.

        Returns:
            Count of reports carrying an error (e.g. unknown or unreachable
            source). These are never counted as ``outdated``.
        """
        return sum(1 for r in self.reports if r.error is not None)

    @property
    def locally_modified_count(self) -> int:
        """Number of fragments whose managed block was edited on disk.

        Returns:
            Count of reports whose ``local_state`` is ``MODIFIED``.
        """
        return sum(1 for r in self.reports if r.local_state is BlockState.MODIFIED)

    @property
    def sync_blocked_count(self) -> int:
        """Number of fragments a later ``sync`` would refuse without ``--force``.

        Returns:
            Count of reports whose ``local_state`` is MODIFIED (block edited),
            MALFORMED (broken markers), or MISSING (no markers) — the three
            states ``managed.weave`` rejects. ABSENT is excluded: ``sync``
            recreates a missing output file.
        """
        return sum(1 for r in self.reports if r.local_state in _SYNC_BLOCKED_STATES)

    def exit_code(self, *, strict: bool = False) -> ExitCode:
        """Map this result to a process exit code.

        Args:
            strict: When True, an errored fragment (not just a drifted or
                sync-blocked one) also yields a failure code — the CI-gate
                behavior of ``--strict``.

        Returns:
            ``ExitCode.FAILURE`` when updates are available or a fragment's
            on-disk block would block ``sync`` (edited/missing/broken markers)
            (or, under ``strict``, when any fragment errored); ``ExitCode.OK``
            otherwise.
        """
        if self.outdated_count or self.sync_blocked_count:
            return ExitCode.FAILURE
        if strict and self.error_count:
            return ExitCode.FAILURE
        return ExitCode.OK


def gather_current_blobs(
    fragment: Fragment, clone_root: Path
) -> dict[str, BlobSha | None]:
    """Resolve the current blob SHA for each of a fragment's files.

    Reads from an already-refreshed clone (the caller refreshes each source
    once, in ``run_check``).

    Args:
        fragment: The fragment whose files to resolve.
        clone_root: The source clone path.

    Returns:
        Map of repo-relative path -> current blob SHA, or None when the file is
        genuinely gone upstream (its path no longer resolves at HEAD).

    Note:
        Only an absent path (``FileAbsentError``) is mapped to None. A broken
        clone raises ``GitError`` from ``blob_sha_for_path`` so it surfaces as a
        fragment error rather than as phantom drift across every file.
    """
    blobs: dict[str, BlobSha | None] = {}
    for file in fragment.files:
        try:
            blobs[file.path] = blob_sha_for_path(clone_root, file.path)
        except FileAbsentError:
            blobs[file.path] = None
    return blobs


def _refresh_sources(
    frags: list[Fragment],
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
) -> dict[str, str]:
    """Clone/pull each unique source once; return per-source refresh errors.

    Refreshing per unique source (rather than per fragment) avoids repeated
    network round-trips when several fragments share one upstream repo.

    Returns:
        Map of source name -> error message for sources whose refresh failed;
        an unknown source is skipped (reported per fragment instead).
    """
    errors: dict[str, str] = {}
    for name in dict.fromkeys(frag.source for frag in frags):
        source = sources.get(name)
        if source is None:
            continue
        try:
            clone_or_pull(source, clone_root_provider(source))
        except GitError as exc:
            errors[name] = str(exc)
    return errors


def run_check(  # noqa: PLR0913
    lock: Lockfile,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    *,
    refresh: bool = True,
    exclude: Sequence[str] = (),
    lock_dir: Path | None = None,
) -> CheckResult:
    """Check every fragment for drift.

    Args:
        lock: The parsed lockfile.
        sources: Resolved sources keyed by name.
        clone_root_provider: Maps a Source to its clone path.
        refresh: When True, refresh each unique source clone once before reading
            blobs (not once per fragment).
        exclude: Glob patterns; matching fragments are skipped entirely (not
            evaluated and absent from the result).
        lock_dir: Directory the fragment output paths are relative to. When
            given, each evaluated fragment's on-disk managed block is also
            classified (populating ``FragmentReport.local_state``); omit to
            check upstream drift only.

    Returns:
        A CheckResult with one report per non-excluded fragment.
    """
    frags = selected_fragments(lock, exclude)
    refresh_errors = (
        _refresh_sources(frags, sources, clone_root_provider) if refresh else {}
    )
    reports = [
        _check_fragment(frag, sources, clone_root_provider, refresh_errors, lock_dir)
        for frag in frags
    ]
    return CheckResult(tuple(reports))


def _check_fragment(
    frag: Fragment,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    refresh_errors: Mapping[str, str],
    lock_dir: Path | None,
) -> FragmentReport:
    """Evaluate one fragment against its already-refreshed source clone.

    Args:
        frag: The fragment to evaluate.
        sources: Resolved sources keyed by name.
        clone_root_provider: Maps a Source to its clone path.
        refresh_errors: Per-source refresh failures from ``_refresh_sources``.
        lock_dir: Directory output paths are relative to (for local-state
            classification), or None to skip it.

    Returns:
        Its FragmentReport (held, errored, clean, or drifted).
    """
    source = sources.get(frag.source)
    if source is None:
        return FragmentReport(
            path=frag.path,
            source=frag.source,
            held=False,
            drifts=(),
            error=f"unknown source '{frag.source}'",
        )
    if not frag.update:
        return FragmentReport(path=frag.path, source=frag.source, held=True, drifts=())
    refresh_error = refresh_errors.get(frag.source)
    if refresh_error is not None:
        return FragmentReport(
            path=frag.path,
            source=frag.source,
            held=False,
            drifts=(),
            error=refresh_error,
        )
    try:
        blobs = gather_current_blobs(frag, clone_root_provider(source))
    except GitError as exc:
        return FragmentReport(
            path=frag.path, source=frag.source, held=False, drifts=(), error=str(exc)
        )
    return FragmentReport(
        path=frag.path,
        source=frag.source,
        held=False,
        drifts=compute_fragment_drift(frag, blobs),
        local_state=_local_state(frag, source, lock_dir),
    )


def _local_state(
    frag: Fragment, source: Source, lock_dir: Path | None
) -> BlockState | None:
    """Classify a fragment's on-disk managed block.

    Args:
        frag: The fragment being evaluated.
        source: Its resolved source (for the comment prefix).
        lock_dir: Directory the output path is relative to, or None to skip.

    Returns:
        The BlockState of the output file, ABSENT when it is missing, or None
        when ``lock_dir`` is None or the file cannot be read.
    """
    if lock_dir is None:
        return None
    target = lock_dir / frag.path
    try:
        # Decode bytes directly: read_text's universal-newline translation would
        # collapse an embedded ``\r`` (e.g. macOS's ``Icon\r`` trick) and make an
        # intact block hash-mismatch as if it were edited.
        text = target.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return BlockState.ABSENT
    except OSError:
        return None
    return managed.classify(text, source.comment_prefix)
