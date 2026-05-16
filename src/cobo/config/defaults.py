"""Baked-in default sources shipped with cobo."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from cobo.config.schema import Source

if TYPE_CHECKING:
    from collections.abc import Mapping

BAKED_SOURCES: Mapping[str, Source] = MappingProxyType({
    "gitignore": Source(
        name="gitignore",
        description="GitHub gitignore templates",
        url="https://github.com/github/gitignore",
        branch="main",
        extension=".gitignore",
        multi_dump=True,
        inject_header=True,
        comment_prefix="#",
        subpath="",
    ),
    "gitattributes": Source(
        name="gitattributes",
        description="Community gitattributes templates",
        url="https://github.com/gitattributes/gitattributes",
        branch="master",
        extension=".gitattributes",
        multi_dump=True,
        inject_header=False,
        comment_prefix="#",
        subpath="",
    ),
    "editorconfig": Source(
        name="editorconfig",
        description="EditorConfig templates",
        url="https://github.com/vinibrsl/editorconfig-templates",
        branch="master",
        extension=".editorconfig",
        multi_dump=False,
        inject_header=True,
        comment_prefix="#",
        subpath="",
    ),
    "mise": Source(
        name="mise",
        description="Mise cookbook configs",
        url="https://github.com/hasansezertasan/mise-cookbooks",
        branch="main",
        extension=".mise.toml",
        multi_dump=False,
        inject_header=True,
        comment_prefix="#",
        subpath="",
    ),
    "licenses": Source(
        name="licenses",
        description="SPDX license texts",
        url="https://github.com/spdx/license-list-data",
        branch="main",
        extension=".txt",
        multi_dump=False,
        inject_header=False,
        comment_prefix="#",
        subpath="text",
    ),
})
