"""Tests for the config loader."""

from typing import TYPE_CHECKING

import pytest

from cobo.config.loader import load_config
from cobo.errors import ConfigError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def write_toml(tmp_path: Path, content: str) -> Path:
    """Write a temp config file and return its path.

    Returns:
        Path to the written TOML file.
    """
    target = tmp_path / "config.toml"
    target.write_text(content, encoding="utf-8")
    return target


def test_baked_sources_are_present_with_empty_user_config(tmp_path: Path) -> None:
    """A missing user config yields all baked sources only."""
    cfg = load_config(user_config_path=tmp_path / "missing.toml")
    assert set(cfg.sources) == {
        "gitignore",
        "gitattributes",
        "editorconfig",
        "mise",
        "licenses",
    }


def test_user_config_can_override_baked_field(tmp_path: Path) -> None:
    """Partially overriding a baked source merges fields, not replaces."""
    path = write_toml(
        tmp_path,
        """
[sources.mise]
branch = "develop"
""",
    )
    cfg = load_config(user_config_path=path)
    mise = cfg.sources["mise"]
    assert mise.branch == "develop"
    assert mise.url == "https://github.com/hasansezertasan/mise-cookbooks"


def test_user_config_can_add_new_source(tmp_path: Path) -> None:
    """A new section becomes a new source."""
    path = write_toml(
        tmp_path,
        """
[sources.dockerfiles]
url = "https://example.invalid/you/dockerfiles"
extension = ".Dockerfile"
""",
    )
    cfg = load_config(user_config_path=path)
    assert "dockerfiles" in cfg.sources
    assert cfg.sources["dockerfiles"].url == "https://example.invalid/you/dockerfiles"


def test_new_source_without_url_raises(tmp_path: Path) -> None:
    """A user-added source missing required url raises ConfigError."""
    path = write_toml(
        tmp_path,
        """
[sources.broken]
extension = ".foo"
""",
    )
    with pytest.raises(ConfigError, match="url"):
        load_config(user_config_path=path)


def test_malformed_toml_raises(tmp_path: Path) -> None:
    """A syntactically invalid TOML file raises ConfigError."""
    path = write_toml(tmp_path, "not = valid = toml")
    with pytest.raises(ConfigError):
        load_config(user_config_path=path)


def test_unknown_field_is_ignored_with_stderr_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unrecognized field is dropped and a warning is printed to stderr."""
    path = write_toml(
        tmp_path,
        """
[sources.mise]
totally_unknown_field = 42
""",
    )
    cfg = load_config(user_config_path=path)
    assert "mise" in cfg.sources
    captured = capsys.readouterr()
    assert "totally_unknown_field" in captured.err


def test_default_branch_top_level_applies_when_omitted(tmp_path: Path) -> None:
    """A new source omitting branch inherits cobo.default_branch."""
    path = write_toml(
        tmp_path,
        """
[cobo]
default_branch = "trunk"

[sources.new]
url = "https://example.com/new.git"
extension = ".x"
""",
    )
    cfg = load_config(user_config_path=path)
    assert cfg.sources["new"].branch == "trunk"


def test_default_branch_does_not_override_baked_branches(tmp_path: Path) -> None:
    """`default_branch` is a fallback for user sources, not baked ones.

    gitattributes pins ``master``; setting default_branch=trunk must not
    change it.
    """
    path = write_toml(
        tmp_path,
        """
[cobo]
default_branch = "trunk"
""",
    )
    cfg = load_config(user_config_path=path)
    assert cfg.sources["gitattributes"].branch == "master"
    assert cfg.sources["mise"].branch == "main"


def test_subpath_with_parent_segment_raises(tmp_path: Path) -> None:
    """A subpath containing `..` is rejected at config-load time."""
    path = write_toml(
        tmp_path,
        """
[sources.bad]
url = "https://example.com/x.git"
extension = ".x"
subpath = "../../etc"
""",
    )
    with pytest.raises(ConfigError, match="subpath"):
        load_config(user_config_path=path)


def test_absolute_subpath_raises(tmp_path: Path) -> None:
    """An absolute subpath is rejected at config-load time."""
    path = write_toml(
        tmp_path,
        """
[sources.bad]
url = "https://example.com/x.git"
extension = ".x"
subpath = "/etc"
""",
    )
    with pytest.raises(ConfigError, match="subpath"):
        load_config(user_config_path=path)
