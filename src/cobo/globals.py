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
from cobo.commands.check import CheckResult, FragmentReport, run_check
from cobo.commands.lock_import import run_import
from cobo.commands.record import resolve_lock_path
from cobo.commands.sync import run_sync
from cobo.errors import ConfigError, GitError, UserError
from cobo.exit_codes import ExitCode
from cobo.lock.io import find_lock, read_lock
from cobo.paths import source_clone_root
from cobo.sources.managed import BlockState
from cobo.sources.repo import clone_or_pull

if TYPE_CHECKING:
    from cobo.config.schema import CoboConfig, Source
    from cobo.lock.schema import Lockfile

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
    _register_lock(app, config=config)


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


def _load_lock_or_exit(lock_path: Path) -> Lockfile:
    """Read a lockfile, exiting cleanly (code 2) if it is malformed.

    Args:
        lock_path: Path to the cobo.lock to parse.

    Returns:
        The parsed Lockfile.

    Raises:
        Exit: Code 2 with the underlying message when the lockfile is malformed
            or its version is unsupported (a ``ConfigError``), so the user sees
            a readable error rather than a raw traceback.
    """
    try:
        return read_lock(lock_path)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(ExitCode.USAGE) from exc


def _register_check(app: typer.Typer, *, config: CoboConfig) -> None:
    @app.command()
    def check(
        json_output: bool = typer.Option(  # noqa: FBT001
            False,  # noqa: FBT003
            "--json",
            help="Emit machine-readable JSON.",
        ),
        strict: bool = typer.Option(  # noqa: FBT001
            False,  # noqa: FBT003
            "--strict",
            help="Also exit non-zero when a fragment errored (e.g. its source "
            "is unknown or unreachable). Useful as a CI gate.",
        ),
        exclude: list[str] = typer.Option(  # noqa: B008
            [],
            "--exclude",
            help="Glob pattern of fragment paths to skip. Repeatable.",
        ),
    ) -> None:
        """Report fragments whose origin has drifted from the lockfile.

        Raises:
            Exit: Code 2 when no cobo.lock is found or it is malformed; code 1
                when updates are available (or, with --strict, when any fragment
                errored); code 0 when everything is up to date.
        """
        lock_path = find_lock(Path.cwd())
        if lock_path is None:
            typer.echo("No cobo.lock found. Run `cobo <source> dump --lock`.", err=True)
            raise typer.Exit(ExitCode.USAGE)
        result = run_check(
            _load_lock_or_exit(lock_path),
            config.sources,
            _clone_root_provider,
            exclude=exclude,
            lock_dir=lock_path.parent,
        )
        if json_output:
            typer.echo(json.dumps(_result_to_dict(result)))
        else:
            _print_check_table(result)
        raise typer.Exit(result.exit_code(strict=strict))


def _result_to_dict(result: CheckResult) -> dict[str, object]:
    """Convert a CheckResult to a JSON-serializable dict.

    Returns:
        A dict with ``outdated_count``, ``error_count`` and a ``fragments`` array.
    """
    return {
        "outdated_count": result.outdated_count,
        "error_count": result.error_count,
        "locally_modified_count": result.locally_modified_count,
        "fragments": [
            {
                "path": r.path,
                "source": r.source,
                "held": r.held,
                "outdated": r.outdated,
                "error": r.error,
                "local_state": r.local_state.value if r.local_state else None,
                "files": [
                    {"name": d.name, "old_blob": d.old_blob, "new_blob": d.new_blob}
                    for d in r.drifts
                ],
            }
            for r in result.reports
        ],
    }


_LOCAL_LABELS = {
    BlockState.MODIFIED: "locally modified",
    BlockState.MISSING: "no cobo markers",
    BlockState.MALFORMED: "malformed markers",
    BlockState.ABSENT: "file missing",
}


def _status_label(report: FragmentReport) -> str:
    """Return the human-readable status cell for one fragment report.

    Returns:
        An error string or ``held``; otherwise the drift status
        (``outdated (N file(s))`` or ``up to date``) with any local managed-block
        issue appended (e.g. ``up to date; locally modified``).
    """
    if report.error is not None:
        return f"error: {report.error}"
    if report.held:
        return "held"
    drift = (
        f"outdated ({len(report.drifts)} file(s))" if report.outdated else "up to date"
    )
    local = _LOCAL_LABELS.get(report.local_state) if report.local_state else None
    return f"{drift}; {local}" if local is not None else drift


def _print_check_table(result: CheckResult) -> None:
    """Print a Rich table summarizing the check result."""
    table = Table("Fragment", "Source", "Status")
    for r in result.reports:
        table.add_row(r.path, r.source, _status_label(r))
    _console.print(table)
    _console.print(f"{result.outdated_count} fragment(s) need updating.")
    if result.locally_modified_count:
        _console.print(
            f"{result.locally_modified_count} fragment(s) edited locally "
            "(sync will refuse without --force)."
        )
    if result.error_count:
        _console.print(f"{result.error_count} fragment(s) could not be evaluated.")


def _register_sync(app: typer.Typer, *, config: CoboConfig) -> None:  # noqa: C901
    @app.command()
    def sync(  # noqa: C901
        dry_run: bool = typer.Option(  # noqa: FBT001
            False,  # noqa: FBT003
            "--dry-run",
            help="Show what would change without writing.",
        ),
        force: bool = typer.Option(  # noqa: FBT001
            False,  # noqa: FBT003
            "--force",
            help="Overwrite a locally edited managed block (and rebuild files "
            "whose cobo markers are missing or malformed) instead of refusing.",
        ),
        exclude: list[str] = typer.Option(  # noqa: B008
            [],
            "--exclude",
            help="Glob pattern of fragment paths to skip. Repeatable.",
        ),
    ) -> None:
        """Re-render outdated fragments and open them for commit.

        Raises:
            Exit: Code 2 when no cobo.lock is found or it is malformed; code 1
                when any fragment failed to re-render (including a fragment
                whose managed block was edited locally, unless --force) or the
                lockfile could not be written back; code 0 otherwise.
        """
        lock_path = find_lock(Path.cwd())
        if lock_path is None:
            typer.echo("No cobo.lock found. Run `cobo <source> dump --lock`.", err=True)
            raise typer.Exit(ExitCode.USAGE)
        try:
            result = run_sync(
                _load_lock_or_exit(lock_path),
                config.sources,
                _clone_root_provider,
                lock_dir=lock_path.parent,
                lock_path=lock_path,
                dry_run=dry_run,
                force=force,
                exclude=exclude,
            )
        except UserError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(ExitCode.FAILURE) from exc
        for path in result.changed:
            typer.echo(f"updated: {path}")
        for failure in result.failed:
            typer.echo(f"failed: {failure.path}: {failure.reason}", err=True)
        if not result.changed and not result.failed:
            typer.echo("All fragments up to date.")
        raise typer.Exit(result.exit_code)


def _register_lock(app: typer.Typer, *, config: CoboConfig) -> None:
    sub = typer.Typer(no_args_is_help=True, help="Lockfile maintenance.")
    app.add_typer(sub, name="lock")

    @sub.command("import")
    def import_cmd(
        files: list[Path] = typer.Argument(  # noqa: B008
            ..., help="Previously dumped files to adopt into cobo.lock."
        ),
    ) -> None:
        """Adopt pre-existing dumps into cobo.lock from their provenance headers.

        Raises:
            Exit: Code 2 when the existing cobo.lock is malformed; code 1 when
                any file failed to import; code 0 otherwise.
        """
        try:
            result = run_import(
                files,
                config.sources,
                _clone_root_provider,
                lock_path=resolve_lock_path(Path.cwd()),
            )
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(ExitCode.USAGE) from exc
        for imported in result.imported:
            typer.echo(f"imported: {imported.path} ({imported.count} file(s))")
        for failure in result.failed:
            typer.echo(f"failed: {failure.path}: {failure.reason}", err=True)
        raise typer.Exit(result.exit_code)
