"""Typer app assembly for cobo.

`build_app()` resolves config once at process start, attaches global commands,
and registers one Typer subapp per configured source.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from cobo.config.loader import load_config
from cobo.globals import attach_globals
from cobo.paths import cache_root, config_path, source_clone_root
from cobo.source_commands import build_source_subapp

if TYPE_CHECKING:
    from cobo.config.schema import Source


def build_app() -> typer.Typer:
    """Resolve config and assemble the full Typer app.

    Returns:
        Fully configured Typer app with global commands and source subapps.
    """
    user_config_file = _user_config_path()
    config = load_config(user_config_path=user_config_file)
    parent = typer.Typer(
        name="cobo",
        help="cobo — copy boilerplates from configurable git repositories.",
        no_args_is_help=True,
        rich_markup_mode="rich",
    )
    attach_globals(
        parent,
        config=config,
        cache_root=cache_root(),
        user_config_file=user_config_file,
    )
    for name, source in config.sources.items():
        parent.add_typer(
            build_source_subapp(source, clone_root_provider=_default_clone_root),
            name=name,
        )
    return parent


def _user_config_path() -> Path:
    """Resolve the user config path, honoring the COBO_CONFIG env override.

    Returns:
        Path from COBO_CONFIG env var if set, otherwise the platform default.
    """
    override = os.environ.get("COBO_CONFIG")
    if override:
        return Path(override)
    return config_path()


def _default_clone_root(source: Source) -> Path:
    """Production clone-root provider used by the assembled app.

    Returns:
        Resolved clone root directory for the given source.
    """
    return source_clone_root(source.name)


app: typer.Typer = build_app()
