"""Platform-specific path resolution for cobo."""

from __future__ import annotations

from typing import TYPE_CHECKING

from platformdirs import PlatformDirs

if TYPE_CHECKING:
    from pathlib import Path

_DIRS: PlatformDirs = PlatformDirs(
    appname="cobo",
    appauthor=False,
    version=None,
    roaming=False,
    ensure_exists=True,
)


def cache_root() -> Path:
    """Return the top-level cache directory for cobo."""
    return _DIRS.user_cache_path


def config_path() -> Path:
    """Return the path to the user config file (existence not guaranteed)."""
    return _DIRS.user_config_path / "config.toml"


def source_clone_root(source_name: str) -> Path:
    """Return the clone directory for a given source name."""
    return cache_root() / "sources" / source_name
