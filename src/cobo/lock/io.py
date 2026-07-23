"""Read, write, locate, and update the cobo.lock file."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Any

from cobo.errors import ConfigError
from cobo.lock.schema import Fragment, LockedFile, Lockfile

if TYPE_CHECKING:
    from pathlib import Path

LOCK_FILENAME = "cobo.lock"
_SUPPORTED_VERSION = 1


def empty_lock() -> Lockfile:
    """Return a fresh, empty lockfile at the current schema version.

    Returns:
        A Lockfile with version 1 and no fragments.
    """
    return Lockfile(version=_SUPPORTED_VERSION, fragments=())


def find_lock(start: Path) -> Path | None:
    """Search ``start`` and its ancestors for a cobo.lock file.

    Ascends one directory at a time but stops at the repository root — the first
    directory containing a ``.git`` entry — so discovery never escapes the
    project into unrelated parent directories (or ``$HOME`` / ``/``). A cobo.lock
    lives beside the files it tracks (its ``[[fragment]]`` paths are relative to
    its own directory), so it always sits at or below that boundary.

    Returns:
        The path to the nearest cobo.lock at or above ``start`` within the
        repository, or None.
    """
    for directory in (start, *start.parents):
        candidate = directory / LOCK_FILENAME
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists():  # repo boundary: don't ascend past it
            break
    return None


def read_lock(path: Path) -> Lockfile:
    """Parse a cobo.lock file into a Lockfile.

    Returns:
        The parsed Lockfile.

    Raises:
        ConfigError: When the lockfile cannot be read, the TOML is malformed,
            or the version is unsupported.
    """
    try:
        with path.open("rb") as fh:
            data: dict[str, Any] = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        msg = f"Malformed lockfile {path}: {exc}"
        raise ConfigError(msg) from exc
    except OSError as exc:
        # The existence check in find_lock can race with permission changes or
        # the path becoming a directory; map to a clean ConfigError so callers
        # report exit 2 rather than crashing with a raw traceback.
        msg = f"Could not read lockfile {path}: {exc}"
        raise ConfigError(msg) from exc

    version = data.get("version")
    if version != _SUPPORTED_VERSION:
        msg = f"Unsupported lockfile version {version!r} in {path} (expected 1)"
        raise ConfigError(msg)

    fragments = tuple(_parse_fragment(raw, path) for raw in data.get("fragment", []))
    return Lockfile(version=_SUPPORTED_VERSION, fragments=fragments)


def _parse_fragment(raw: dict[str, Any], path: Path) -> Fragment:
    """Build a Fragment from a raw TOML table.

    Returns:
        The parsed Fragment.

    Raises:
        ConfigError: When a required key is missing or a value is invalid (an
            empty field, a malformed SHA, or a fragment with no files).
    """
    try:
        files = tuple(
            LockedFile(
                name=f["name"], path=f["path"], commit=f["commit"], blob=f["blob"]
            )
            for f in raw["files"]
        )
        return Fragment(
            path=raw["path"],
            source=raw["source"],
            files=files,
            update=raw.get("update", True),
        )
    except KeyError as exc:
        msg = f"Lockfile {path}: fragment missing required key {exc}"
        raise ConfigError(msg) from exc
    except ValueError as exc:
        msg = f"Lockfile {path}: invalid fragment ({exc})"
        raise ConfigError(msg) from exc


def upsert_fragment(lock: Lockfile, fragment: Fragment) -> Lockfile:
    """Return a new Lockfile with ``fragment`` added or replaced by output path.

    Returns:
        A new Lockfile; the matching fragment (same ``path``) is replaced,
        otherwise ``fragment`` is appended.
    """
    kept = tuple(f for f in lock.fragments if f.path != fragment.path)
    return Lockfile(version=lock.version, fragments=(*kept, fragment))


def write_lock(path: Path, lock: Lockfile) -> None:
    """Atomically serialize ``lock`` to ``path``.

    The document is written to a sibling temp file and renamed, so a crash
    mid-write never leaves a half-written cobo.lock.

    Raises:
        OSError: When the temp file cannot be written or renamed (e.g. a full
            or read-only disk). The partial temp file is removed first so a
            failed write does not leave a stray ``cobo.lock.tmp`` behind.
    """
    text = _serialize(lock)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _serialize(lock: Lockfile) -> str:
    """Render a Lockfile as TOML text.

    Returns:
        TOML matching the format ``read_lock`` parses.
    """
    lines = [f"version = {lock.version}", ""]
    for frag in lock.fragments:
        lines.extend((
            "[[fragment]]",
            f"path = {_q(frag.path)}",
            f"source = {_q(frag.source)}",
            f"update = {str(frag.update).lower()}",
        ))
        for file in frag.files:
            lines.extend((
                "",
                "  [[fragment.files]]",
                f"  name = {_q(file.name)}",
                f"  path = {_q(file.path)}",
                f"  commit = {_q(file.commit)}",
                f"  blob = {_q(file.blob)}",
            ))
        lines.append("")
    # Blank lines separate fragments; drop the trailing one so the file ends in
    # exactly one newline (POSIX text-file convention; keeps end-of-file-fixer
    # and other tooling from rewriting a cobo-generated lockfile).
    return "\n".join(lines).rstrip("\n") + "\n"


def _q(value: str) -> str:
    """Quote and escape a string as a TOML basic string.

    Returns:
        ``value`` wrapped in double quotes with backslash, quote, newline,
        carriage return, and tab escaped.
    """
    escaped = (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'
