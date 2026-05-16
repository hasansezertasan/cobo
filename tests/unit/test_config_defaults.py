"""Tests for the baked default sources."""

import pytest

from cobo.config.defaults import BAKED_SOURCES

pytestmark = pytest.mark.unit


def test_gitignore_default_is_multi_dump() -> None:
    """The gitignore source allows concatenating multiple files in one dump."""
    source = BAKED_SOURCES["gitignore"]
    assert source.url == "https://github.com/github/gitignore"
    assert source.extension == ".gitignore"
    assert source.multi_dump is True
    assert source.inject_header is True


def test_mise_default_is_single_dump_with_header() -> None:
    """The mise source disallows multi-dump and injects a provenance header."""
    source = BAKED_SOURCES["mise"]
    assert source.url == "https://github.com/hasansezertasan/mise-cookbooks"
    assert source.extension == ".mise.toml"
    assert source.multi_dump is False
    assert source.inject_header is True


def test_gitattributes_default_is_multi_dump() -> None:
    """The gitattributes source allows concatenating multiple files in one dump."""
    source = BAKED_SOURCES["gitattributes"]
    assert source.url == "https://github.com/gitattributes/gitattributes"
    assert source.extension == ".gitattributes"
    assert source.multi_dump is True
    assert source.inject_header is False


def test_editorconfig_default_is_single_dump_with_header() -> None:
    """The editorconfig source disallows multi-dump and injects a provenance header."""
    source = BAKED_SOURCES["editorconfig"]
    assert source.url == "https://github.com/vinibrsl/editorconfig-templates"
    assert source.extension == ".editorconfig"
    assert source.multi_dump is False
    assert source.inject_header is True


def test_licenses_default_is_single_dump_no_header() -> None:
    """The licenses source copies SPDX license texts verbatim from a subpath."""
    source = BAKED_SOURCES["licenses"]
    assert source.url == "https://github.com/spdx/license-list-data"
    assert source.extension == ".txt"
    assert source.subpath == "text"
    assert source.multi_dump is False
    assert source.inject_header is False


def test_default_source_names_match_keys() -> None:
    """Source.name equals its dictionary key."""
    for key, source in BAKED_SOURCES.items():
        assert source.name == key
