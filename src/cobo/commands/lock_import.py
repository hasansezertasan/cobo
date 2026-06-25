"""Adopt pre-existing dumps into the lockfile from their provenance headers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cobo.commands.record import record_dump
from cobo.errors import GitError, UserError
from cobo.sources.render import parse_provenance
from cobo.sources.repo import clone_or_pull, current_commit_sha

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from cobo.commands.check import CloneRootProvider
    from cobo.config.schema import Source


@dataclass(frozen=True, slots=True)
class ImportedFile:
    """A file successfully adopted into the lockfile.

    Attributes:
        path: The imported file's path (as given).
        count: Number of input boilerplates recorded for it.
    """

    path: str
    count: int


@dataclass(frozen=True, slots=True)
class FailedImport:
    """A file that could not be imported, with the reason.

    Attributes:
        path: The file's path (as given).
        reason: Human-readable cause.
    """

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Outcome of an import run.

    Attributes:
        imported: Files adopted into the lockfile.
        failed: Files that could not be imported.
    """

    imported: tuple[ImportedFile, ...]
    failed: tuple[FailedImport, ...]


def run_import(
    files: list[Path],
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    *,
    lock_path: Path,
    refresh: bool = True,
) -> ImportResult:
    """Reconstruct lockfile entries from each file's provenance header(s).

    Each file is processed independently; a failure on one is captured and the
    rest still import. Recording adopts the current upstream HEAD (cobo's shallow
    clones cannot resurrect the originally pinned commit).

    A ``ConfigError`` (a malformed existing cobo.lock) is *not* isolated per
    file — it is a single global problem, so it propagates to the caller to be
    reported once with exit 2, matching ``check``/``sync``.

    Args:
        files: Paths of previously dumped files to adopt.
        sources: Resolved sources keyed by name.
        clone_root_provider: Maps a Source to its clone path.
        lock_path: Where the lockfile lives (created if absent).
        refresh: When True, clone/pull each referenced source before recording.

    Returns:
        An ImportResult describing imported and failed files.
    """
    imported: list[ImportedFile] = []
    failed: list[FailedImport] = []
    for file in files:
        try:
            count = _import_one(
                file, sources, clone_root_provider, lock_path, refresh=refresh
            )
        except (UserError, GitError, OSError) as exc:
            failed.append(FailedImport(path=str(file), reason=str(exc)))
            continue
        imported.append(ImportedFile(path=str(file), count=count))
    return ImportResult(imported=tuple(imported), failed=tuple(failed))


def _import_one(
    file: Path,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    lock_path: Path,
    *,
    refresh: bool,
) -> int:
    """Import one file and return how many input boilerplates were recorded.

    Reads the file's provenance header(s), resolves the source, and re-records
    the dump at the current upstream HEAD. ``OSError`` (unreadable file) and
    ``GitError`` (clone/refresh or blob-resolution failure) propagate to the
    caller, which isolates them per file. A ``ConfigError`` from a malformed
    lockfile propagates further still (it is not a per-file fault).

    Returns:
        The number of input boilerplates recorded for the file.

    Raises:
        UserError: When the file has no cobo header, mixes sources, or names an
            unknown source.
    """
    content = file.read_text(encoding="utf-8")
    pairs = parse_provenance(content)
    if not pairs:
        msg = f"{file}: no cobo provenance header found (was it dumped with a header?)"
        raise UserError(msg)
    source_names = {source for source, _ in pairs}
    if len(source_names) > 1:
        joined = ", ".join(sorted(source_names))
        msg = f"{file}: header references multiple sources ({joined})"
        raise UserError(msg)
    source_name = pairs[0][0]
    source = sources.get(source_name)
    if source is None:
        msg = f"{file}: unknown source '{source_name}'"
        raise UserError(msg)
    names = [name for _, name in pairs]
    clone_root = clone_root_provider(source)
    if refresh:
        clone_or_pull(source, clone_root)
    record_dump(
        source=source,
        clone_root=clone_root,
        names=names,
        out_path=file,
        lock_path=lock_path,
        commit_sha=current_commit_sha(clone_root),
    )
    return len(names)
