"""Tests for COBO_CONFIG env override on the user config path."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cobo.cli import _user_config_path  # noqa: PLC2701

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_cobo_config_env_overrides_platform_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When COBO_CONFIG is set, it takes precedence over the platform default."""
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("COBO_CONFIG", str(target))
    assert _user_config_path() == target


def test_user_config_path_falls_back_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without COBO_CONFIG, the platform default config path is returned."""
    monkeypatch.delenv("COBO_CONFIG", raising=False)
    from cobo.paths import config_path  # noqa: PLC0415

    assert _user_config_path() == config_path()
