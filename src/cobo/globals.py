"""Global (non-source-specific) commands for cobo."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from cobo import __version__
from cobo.commands.check import CheckResult, run_check
from cobo.commands.sync import run_sync
from cobo.errors import GitError
from cobo.lock.io import find_lock, read_lock
from cobo.paths import source_clone_root
from cobo.sources.repo import clone_or_pull

if TYPE_CHECKING:
    from cobo.config.schema import CoboConfig, Source

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
    _register_check(app, config=config)
    _register_sync(app, config=config)


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


def _clone_root_provider(source: Source) -> Path:
    """Map a source to its cache clone path.

    Returns:
        The clone root directory for the source.
    """
    return source_clone_root(source.name)


def _register_check(app: typer.Typer, *, config: CoboConfig) -> None:
    @app.command()
    def check(
        json_output: bool = typer.Option(  # noqa: FBT001
            False,  # noqa: FBT003
            "--json",
            help="Emit machine-readable JSON.",
        ),
    ) -> None:
        """Report fragments whose origin has drifted from the lockfile.

        Raises:
            Exit: Code 2 when no cobo.lock is found; code 1 when updates are
                available; code 0 when everything is up to date.
        """
        lock_path = find_lock(Path.cwd())
        if lock_path is None:
            typer.echo("No cobo.lock found. Run `cobo <source> dump --lock`.", err=True)
            raise typer.Exit(2)
        result = run_check(read_lock(lock_path), config.sources, _clone_root_provider)
        if json_output:
            typer.echo(json.dumps(_result_to_dict(result)))
        else:
            _print_check_table(result)
        raise typer.Exit(1 if result.outdated_count else 0)


def _result_to_dict(result: CheckResult) -> dict[str, object]:
    """Convert a CheckResult to a JSON-serializable dict.

    Returns:
        A dict with ``outdated_count`` and a ``fragments`` array.
    """
    return {
        "outdated_count": result.outdated_count,
        "fragments": [
            {
                "path": r.path,
                "source": r.source,
                "held": r.held,
                "outdated": r.outdated,
                "error": r.error,
                "files": [
                    {"name": d.name, "old_blob": d.old_blob, "new_blob": d.new_blob}
                    for d in r.drifts
                ],
            }
            for r in result.reports
        ],
    }


def _print_check_table(result: CheckResult) -> None:
    """Print a Rich table summarizing the check result."""
    table = Table("Fragment", "Source", "Status")
    for r in result.reports:
        if r.error is not None:
            status = f"error: {r.error}"
        elif r.held:
            status = "held"
        elif r.outdated:
            status = f"outdated ({len(r.drifts)} file(s))"
        else:
            status = "up to date"
        table.add_row(r.path, r.source, status)
    _console.print(table)
    _console.print(f"{result.outdated_count} fragment(s) need updating.")


def _register_sync(app: typer.Typer, *, config: CoboConfig) -> None:  # noqa: C901
    @app.command()
    def sync(
        dry_run: bool = typer.Option(  # noqa: FBT001
            False,  # noqa: FBT003
            "--dry-run",
            help="Show what would change without writing.",
        ),
    ) -> None:
        """Re-render outdated fragments and open them for commit.

        Raises:
            Exit: Code 2 when no cobo.lock is found; code 1 when any fragment
                failed to re-render; code 0 otherwise.
        """
        lock_path = find_lock(Path.cwd())
        if lock_path is None:
            typer.echo("No cobo.lock found. Run `cobo <source> dump --lock`.", err=True)
            raise typer.Exit(2)
        result = run_sync(
            read_lock(lock_path),
            config.sources,
            _clone_root_provider,
            lock_dir=lock_path.parent,
            lock_path=lock_path,
            dry_run=dry_run,
        )
        for path in result.changed:
            typer.echo(f"updated: {path}")
        for failure in result.failed:
            typer.echo(f"failed: {failure.path}: {failure.reason}", err=True)
        if not result.changed and not result.failed:
            typer.echo("All fragments up to date.")
        raise typer.Exit(1 if result.failed else 0)
