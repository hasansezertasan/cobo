"""Drift detection across all tracked fragments (the `cobo check` core)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from cobo.errors import FileAbsentError, GitError
from cobo.lock.diff import compute_fragment_drift
from cobo.sources.repo import blob_sha_for_path, clone_or_pull

if TYPE_CHECKING:
    from collections.abc import Mapping

    from cobo.config.schema import Source
    from cobo.lock.diff import FileDrift
    from cobo.lock.schema import Fragment, Lockfile

CloneRootProvider = Callable[(["Source"], Path)]


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
    """

    path: str
    source: str
    held: bool
    drifts: tuple[FileDrift, ...]
    error: str | None = None

    def __post_init__(self) -> None:
        """Enforce that held / errored / drifted are mutually exclusive states.

        Raises:
            ValueError: When the report mixes states that cannot co-occur (a
                held report with an error or drifts, or an errored report that
                also carries drifts).
        """
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


def gather_current_blobs(
    fragment: Fragment, source: Source, clone_root: Path, *, refresh: bool
) -> dict[str, str | None]:
    """Resolve the current blob SHA for each of a fragment's files.

    Args:
        fragment: The fragment whose files to resolve.
        source: The source to (optionally) refresh.
        clone_root: The source clone path.
        refresh: When True, clone/pull before reading blobs.

    Returns:
        Map of repo-relative path -> current blob SHA, or None when the file is
        genuinely gone upstream (its path no longer resolves at HEAD).

    Note:
        Only an absent path (``FileAbsentError``) is mapped to None. A broken
        clone or failed refresh raises ``GitError`` from ``clone_or_pull`` /
        ``blob_sha_for_path`` so it surfaces as a fragment error rather than as
        phantom drift across every file.
    """
    if refresh:
        clone_or_pull(source, clone_root)
    blobs: dict[str, str | None] = {}
    for file in fragment.files:
        try:
            blobs[file.path] = blob_sha_for_path(clone_root, file.path)
        except FileAbsentError:
            blobs[file.path] = None
    return blobs


def run_check(
    lock: Lockfile,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    *,
    refresh: bool = True,
    exclude: Sequence[str] = (),
) -> CheckResult:
    """Check every fragment for drift.

    Args:
        lock: The parsed lockfile.
        sources: Resolved sources keyed by name.
        clone_root_provider: Maps a Source to its clone path.
        refresh: When True, refresh each source clone before reading blobs.
        exclude: Glob patterns; matching fragments are skipped entirely (not
            evaluated and absent from the result).

    Returns:
        A CheckResult with one report per non-excluded fragment.
    """
    reports: list[FragmentReport] = [
        _check_fragment(frag, sources, clone_root_provider, refresh)
        for frag in selected_fragments(lock, exclude)
    ]
    return CheckResult(tuple(reports))


def _check_fragment(
    frag: Fragment,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    refresh: bool,  # noqa: FBT001
) -> FragmentReport:
    """Evaluate one fragment.

    Args:
        frag: The fragment to evaluate.
        sources: Resolved sources keyed by name.
        clone_root_provider: Maps a Source to its clone path.
        refresh: When True, refresh the clone before reading blobs.

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
    try:
        blobs = gather_current_blobs(
            frag, source, clone_root_provider(source), refresh=refresh
        )
    except GitError as exc:
        return FragmentReport(
            path=frag.path, source=frag.source, held=False, drifts=(), error=str(exc)
        )
    return FragmentReport(
        path=frag.path,
        source=frag.source,
        held=False,
        drifts=compute_fragment_drift(frag, blobs),
    )
