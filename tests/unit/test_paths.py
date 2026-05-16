"""Tests for path resolution helpers."""

from pathlib import Path

import pytest

from cobo.paths import (
    cache_root,
    config_path,
    source_clone_root,
)

pytestmark = pytest.mark.unit


def test_cache_root_is_path_under_user_cache() -> None:
    """Cache root resolves to a path containing the app name 'cobo'."""
    result = cache_root()
    assert isinstance(result, Path)
    assert "cobo" in str(result)


def test_config_path_ends_with_config_toml() -> None:
    """Config path ends with 'config.toml' under the platform's config directory."""
    result = config_path()
    assert isinstance(result, Path)
    assert result.name == "config.toml"


def test_source_clone_root_includes_source_name() -> None:
    """Per-source clone root nests the source name under cache_root/sources/."""
    result = source_clone_root("gitignore")
    assert result.parent == cache_root() / "sources"
    assert result.name == "gitignore"
