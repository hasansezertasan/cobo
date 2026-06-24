"""Drift detection across all tracked fragments (the `cobo check` core)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cobo.errors import GitError
from cobo.lock.diff import compute_fragment_drift
from cobo.sources.repo import blob_sha_for_path, clone_or_pull

if TYPE_CHECKING:
    from collections.abc import Mapping

    from cobo.config.schema import Source
    from cobo.lock.diff import FileDrift
    from cobo.lock.schema import Fragment, Lockfile

CloneRootProvider = Callable[(["Source"], Path)]


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
        Map of repo-relative path -> current blob SHA, or None when a file
        could not be resolved (e.g. it was deleted upstream).
    """
    if refresh:
        clone_or_pull(source, clone_root)
    blobs: dict[str, str | None] = {}
    for file in fragment.files:
        try:
            blobs[file.path] = blob_sha_for_path(clone_root, file.path)
        except GitError:
            blobs[file.path] = None
    return blobs


def run_check(
    lock: Lockfile,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    *,
    refresh: bool = True,
) -> CheckResult:
    """Check every fragment for drift.

    Args:
        lock: The parsed lockfile.
        sources: Resolved sources keyed by name.
        clone_root_provider: Maps a Source to its clone path.
        refresh: When True, refresh each source clone before reading blobs.

    Returns:
        A CheckResult with one report per fragment.
    """
    reports: list[FragmentReport] = [
        _check_fragment(frag, sources, clone_root_provider, refresh)
        for frag in lock.fragments
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
