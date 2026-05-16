"""Frozen dataclasses describing a configured source and the resolved config."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING

from cobo.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class Source:
    """A single configured boilerplate source.

    Attributes:
        name: TOML section key; also the CLI subcommand name.
        url: Git URL to clone.
        extension: File suffix used to discover boilerplates (e.g. ".gitignore").
        description: Human-readable label.
        branch: Branch to track.
        multi_dump: If True, `dump` accepts multiple names and concatenates them.
        inject_header: If True, prepend a provenance comment block on dump.
        comment_prefix: Prefix used for header lines.
        subpath: If non-empty, only scan this subdirectory for boilerplates.
    """

    name: str
    url: str
    extension: str
    description: str = ""
    branch: str = "main"
    multi_dump: bool = False
    inject_header: bool = False
    comment_prefix: str = "#"
    subpath: str = ""

    def __post_init__(self) -> None:
        """Reject subpaths that could escape the clone root.

        Raises:
            ConfigError: When ``subpath`` is absolute, contains a ``..``
                segment, or contains a null byte.
        """
        sp = self.subpath
        if not sp:
            return
        if "\0" in sp:
            msg = f"Source '{self.name}': subpath contains null byte"
            raise ConfigError(msg)
        candidate = PurePosixPath(sp.replace("\\", "/"))
        if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            msg = (
                f"Source '{self.name}': subpath '{sp}' must be relative and "
                f"must not contain '..' segments"
            )
            raise ConfigError(msg)


@dataclass(frozen=True, slots=True)
class CoboConfig:
    """Fully-resolved configuration after merging baked defaults and user TOML.

    Attributes:
        default_branch: Fallback branch when a source omits its own.
        sources: Source instances keyed by name.
    """

    default_branch: str
    sources: Mapping[str, Source] = field(default_factory=lambda: MappingProxyType({}))
