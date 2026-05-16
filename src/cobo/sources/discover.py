"""Boilerplate discovery: list, search, and find by name."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cobo.errors import UserError

if TYPE_CHECKING:
    from pathlib import Path

    from cobo.config.schema import Source


def list_boilerplates(source: Source, clone_root: Path) -> list[str]:
    """Return sorted boilerplate names (sans extension) discovered in a clone.

    Names are deduplicated case-insensitively: when the same basename appears
    in multiple subdirectories, only one entry is reported.

    Returns:
        Sorted, deduplicated list of boilerplate names without their extension.
    """
    scan_root = _scan_root(source, clone_root)
    ext = source.extension
    seen: dict[str, str] = {}
    for path in scan_root.rglob(f"*{ext}"):
        if not path.is_file():
            continue
        stem = path.name[: -len(ext)]
        seen.setdefault(stem.lower(), stem)
    return sorted(seen.values())


def search_boilerplates(source: Source, clone_root: Path, term: str) -> list[str]:
    """Return boilerplate names matching `term` as a case-insensitive substring.

    Returns:
        Filtered list of boilerplate names containing `term` (case-insensitive).
    """
    needle = term.lower()
    return [n for n in list_boilerplates(source, clone_root) if needle in n.lower()]


def find_boilerplate(source: Source, clone_root: Path, name: str) -> Path:
    """Resolve a boilerplate name to its file path (case-insensitive).

    Returns:
        Path to the matching boilerplate file.

    Raises:
        UserError: When the name is invalid or no file matches.
    """
    _validate_name(name)
    needle = name.lower()
    scan_root = _scan_root(source, clone_root)
    matches: list[Path] = [
        path
        for path in scan_root.rglob(f"*{source.extension}")
        if path.is_file() and path.name[: -len(source.extension)].lower() == needle
    ]
    if not matches:
        msg = f"Boilerplate '{name}' not found in source '{source.name}'"
        raise UserError(msg)
    matches.sort(key=lambda p: (len(p.relative_to(scan_root).parts), str(p)))
    return matches[0]


_FORBIDDEN_NAME_CHARS = frozenset("/\\\0")


def _validate_name(name: str) -> None:
    """Reject boilerplate names that contain path separators or are empty.

    Raises:
        UserError: When the name is empty, contains separators/null bytes, or
            is a path-traversal segment.
    """
    if not name:
        msg = "Boilerplate name must not be empty"
        raise UserError(msg)
    if any(ch in _FORBIDDEN_NAME_CHARS for ch in name):
        msg = f"Boilerplate name must not contain path separators: '{name}'"
        raise UserError(msg)
    if name in {".", ".."}:
        msg = f"Boilerplate name must not be a path-traversal segment: '{name}'"
        raise UserError(msg)


def _scan_root(source: Source, clone_root: Path) -> Path:
    """Apply the source's optional subpath to the clone root.

    Defense-in-depth: even though :class:`~cobo.config.schema.Source` rejects
    unsafe subpaths at construction time, the resolved scan root is verified
    to remain inside ``clone_root`` so a future bypass of that check cannot
    escape the cache.

    Returns:
        The effective directory to scan for boilerplate files.

    Raises:
        UserError: When the resolved scan root would escape ``clone_root``.
    """
    if not source.subpath:
        return clone_root
    candidate = (clone_root / source.subpath).resolve()
    root = clone_root.resolve()
    if root != candidate and root not in candidate.parents:
        msg = f"Source '{source.name}': subpath '{source.subpath}' escapes clone root"
        raise UserError(msg)
    return candidate
