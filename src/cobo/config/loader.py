"""Resolve the merged cobo configuration from baked defaults and user TOML."""

from __future__ import annotations

import dataclasses
import sys
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from cobo.config.defaults import BAKED_SOURCES
from cobo.config.schema import CoboConfig, Source
from cobo.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_VALID_SOURCE_FIELDS: frozenset[str] = frozenset(
    f.name for f in dataclasses.fields(Source)
)


def load_config(user_config_path: Path | None = None) -> CoboConfig:
    """Build the resolved CoboConfig from baked defaults and an optional user TOML.

    The ``[cobo].default_branch`` setting is a fallback for user-defined
    sources that omit ``branch``; baked sources keep their own pinned branch
    (e.g. ``gitattributes`` tracks ``master``) regardless.

    Args:
        user_config_path: Path to the user TOML. If None or missing, only baked
            defaults are returned.

    Returns:
        Frozen CoboConfig.
    """  # ConfigError is raised by helpers _read_toml and _build_new_source
    user_data: dict[str, Any] = _read_toml(user_config_path)
    default_branch: str = user_data.get("cobo", {}).get("default_branch", "main")
    user_sources: dict[str, dict[str, Any]] = user_data.get("sources", {})

    merged: dict[str, Source] = {}
    for name, baked in BAKED_SOURCES.items():
        merged[name] = _merge_baked(name, baked, user_sources.get(name, {}))

    for name, raw in user_sources.items():
        if name in merged:
            continue
        merged[name] = _build_new_source(name, raw, default_branch)

    return CoboConfig(
        default_branch=default_branch,
        sources=MappingProxyType(merged),
    )


def _read_toml(path: Path | None) -> dict[str, Any]:
    """Read TOML from path. Missing file or None path returns empty dict.

    Returns:
        Parsed TOML as a nested dict, or an empty dict if path is absent.

    Raises:
        ConfigError: When the file contains invalid TOML.
    """
    if path is None or not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        msg = f"Malformed TOML in {path}: {exc}"
        raise ConfigError(msg) from exc


def _merge_baked(name: str, baked: Source, overrides: Mapping[str, Any]) -> Source:
    """Apply user overrides to a baked source, dropping unknown fields with a warning.

    Returns:
        Updated Source with user overrides applied.
    """
    clean = _filter_fields(name, overrides)
    return dataclasses.replace(baked, **clean)


def _build_new_source(
    name: str,
    raw: Mapping[str, Any],
    default_branch: str,
) -> Source:
    """Build a user-defined Source, validating required fields.

    Returns:
        A new Source constructed from the validated user TOML section.

    Raises:
        ConfigError: When the source is missing the required `url` or `extension` field.
    """
    clean = _filter_fields(name, raw)
    if "url" not in clean:
        msg = f"Source '{name}' is missing required field 'url'"
        raise ConfigError(msg)
    if "extension" not in clean:
        msg = f"Source '{name}' is missing required field 'extension'"
        raise ConfigError(msg)
    clean.setdefault("branch", default_branch)
    return Source(name=name, **clean)


def _filter_fields(source_name: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Drop unknown fields from a raw TOML section and warn about them.

    Unknown fields are printed to stderr so CLI users see typos immediately
    (``warnings.warn`` would be silenced by default in a Typer app).

    Returns:
        Dict of only known, valid Source fields from `raw`.
    """
    unknown = [k for k in raw if k not in _VALID_SOURCE_FIELDS or k == "name"]
    for key in unknown:
        print(  # noqa: T201
            f"cobo: warning: unknown field '{key}' in source '{source_name}' — ignored",
            file=sys.stderr,
        )
    return {k: raw[k] for k in raw if k in _VALID_SOURCE_FIELDS and k != "name"}
