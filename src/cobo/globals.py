"""Global (non-source-specific) commands for cobo."""

from __future__ import annotations

import platform
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from cobo import __version__
from cobo.errors import GitError
from cobo.paths import source_clone_root
from cobo.sources.repo import clone_or_pull

if TYPE_CHECKING:
    from pathlib import Path

    from cobo.config.schema import CoboConfig

_console = Console()


def attach_globals(
    app: typer.Typer,
    config: CoboConfig,
    cache_root: Path,
    user_config_file: Path,
) -> None:
    """Register all global commands on the given Typer app.

    Args:
        app: The Typer application to register commands on.
        config: Resolved cobo configuration.
        cache_root: Top-level cache directory path.
        user_config_file: Path to the user config TOML file.
    """
    _register_version(app)
    _register_info(app, config=config, cache_root=cache_root)
    _register_update(app, config=config)
    _register_list_sources(app, config=config)
    _register_root(app, cache_root=cache_root)
    _register_config(app, config=config)
    _register_config_path(app, user_config_file=user_config_file)


def _register_version(app: typer.Typer) -> None:
    @app.command()
    def version() -> None:
        """Print the cobo package version."""
        typer.echo(__version__)


def _register_info(app: typer.Typer, *, config: CoboConfig, cache_root: Path) -> None:
    @app.command()
    def info() -> None:
        """Print application metadata."""
        typer.echo(f"Application Version: {__version__}")
        py_ver = platform.python_version()
        py_impl = platform.python_implementation()
        typer.echo(f"Python Version: {py_ver} ({py_impl})")
        typer.echo(f"Platform: {platform.system()}")
        typer.echo(f"Cache Root: {cache_root}")
        typer.echo(f"Configured Sources: {', '.join(sorted(config.sources))}")
        typer.echo(
            "Note: source clones under the cache root are disposable;"
            " running `update` performs a hard reset and discards any"
            " local edits.",
        )


def _register_update(app: typer.Typer, *, config: CoboConfig) -> None:
    @app.command()
    def update() -> None:
        """Clone or pull every configured source.

        Exits non-zero if any source fails so callers (CI, scripts) can detect
        partial failure.

        Raises:
            Exit: With code equal to the number of failed sources.
        """
        failures = 0
        for name, source in config.sources.items():
            try:
                clone_or_pull(source, source_clone_root(name))
                typer.echo(f"{name}: ok")
            except GitError as exc:
                failures += 1
                typer.echo(f"{name}: failed — {exc}", err=True)
        if failures:
            raise typer.Exit(failures)


def _register_list_sources(app: typer.Typer, *, config: CoboConfig) -> None:
    @app.command(name="list-sources")
    def list_sources() -> None:
        """Print a table of configured sources."""
        table = Table("Name", "Description", "Multi-dump", "Cloned")
        for name, source in sorted(config.sources.items()):
            cloned = "yes" if source_clone_root(name).exists() else "no"
            table.add_row(name, source.description, str(source.multi_dump), cloned)
        _console.print(table)


def _register_root(app: typer.Typer, *, cache_root: Path) -> None:
    @app.command()
    def root() -> None:
        """Print the top-level cache directory path."""
        typer.echo(str(cache_root))


def _register_config(app: typer.Typer, *, config: CoboConfig) -> None:
    @app.command(name="config")
    def config_cmd() -> None:
        """Print the resolved merged config as TOML."""
        for name, source in sorted(config.sources.items()):
            typer.echo(f"[sources.{name}]")
            typer.echo(f'url = "{source.url}"')
            typer.echo(f'branch = "{source.branch}"')
            typer.echo(f'extension = "{source.extension}"')
            typer.echo(f"multi_dump = {str(source.multi_dump).lower()}")
            typer.echo(f"inject_header = {str(source.inject_header).lower()}")
            typer.echo(f'comment_prefix = "{source.comment_prefix}"')
            typer.echo(f'subpath = "{source.subpath}"')
            typer.echo("")


def _register_config_path(app: typer.Typer, *, user_config_file: Path) -> None:
    @app.command(name="config-path")
    def config_path_cmd() -> None:
        """Print the user config file path (whether it exists or not)."""
        typer.echo(str(user_config_file))
