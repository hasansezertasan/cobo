"""Path resolution for cobo (single ``~/.cobo`` root folder)."""

from __future__ import annotations

from pathlib import Path

APP_NAME = "cobo"
"""Application name, used to derive the root folder."""
ROOT_FOLDER_NAME = f".{APP_NAME}"
"""Name of the root folder (``.cobo``)."""
ROOT_FOLDER_PATH = Path.home() / ROOT_FOLDER_NAME
"""Path to the root folder (``~/.cobo``)."""


def cache_root() -> Path:
    """Return the top-level ``~/.cobo`` folder, creating it if needed."""
    ROOT_FOLDER_PATH.mkdir(parents=True, exist_ok=True)
    return ROOT_FOLDER_PATH


def config_path() -> Path:
    """Return the path to the user config file (existence not guaranteed)."""
    return cache_root() / "config.toml"


def source_clone_root(source_name: str) -> Path:
    """Return the clone directory for a given source name."""
    return cache_root() / "sources" / source_name
