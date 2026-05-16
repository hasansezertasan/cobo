"""Tests for the config dataclasses."""

import dataclasses

import pytest

from cobo.config.schema import CoboConfig, Source

pytestmark = pytest.mark.unit


def make_source(**overrides: object) -> Source:
    """Build a Source with sensible defaults for tests.

    Returns:
        A Source dataclass instance.
    """
    base: dict[str, object] = {
        "name": "demo",
        "url": "https://example.com/demo.git",
        "extension": ".demo",
    }
    base.update(overrides)
    return Source(**base)  # type: ignore[arg-type]


def test_source_is_frozen() -> None:
    """Source instances are immutable after construction."""
    source = make_source()
    with pytest.raises(dataclasses.FrozenInstanceError):
        source.name = "other"  # type: ignore[misc]


def test_source_defaults_are_applied() -> None:
    """Omitted fields fall back to spec-defined defaults."""
    source = make_source()
    assert not source.description
    assert source.branch == "main"
    assert source.multi_dump is False
    assert source.inject_header is False
    assert source.comment_prefix == "#"
    assert not source.subpath


def test_source_required_fields_must_be_set() -> None:
    """Constructing a Source without url or extension is a TypeError."""
    with pytest.raises(TypeError):
        Source(name="x")  # type: ignore[call-arg]


def test_cobo_config_holds_sources_by_name() -> None:
    """CoboConfig keys sources by their TOML section name."""
    s = make_source(name="gitignore")
    cfg = CoboConfig(default_branch="main", sources={"gitignore": s})
    assert cfg.sources["gitignore"] is s
    assert cfg.default_branch == "main"


def test_cobo_config_is_frozen() -> None:
    """CoboConfig instances are immutable after construction."""
    cfg = CoboConfig(default_branch="main", sources={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.default_branch = "develop"  # type: ignore[misc]
