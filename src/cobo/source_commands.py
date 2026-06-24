"""Factory that builds a Typer subapp for one configured source."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer

from cobo.commands.record import record_dump, resolve_lock_path
from cobo.config.schema import Source
from cobo.errors import GitError, UserError
from cobo.sources.discover import list_boilerplates, search_boilerplates
from cobo.sources.render import dump as render_dump
from cobo.sources.repo import clone_or_pull, current_commit_sha

CloneRootProvider = Callable[([Source], Path)]


def build_source_subapp(
    source: Source,
    clone_root_provider: CloneRootProvider,
) -> typer.Typer:
    """Construct the Typer subapp for one source.

    Returns:
        A Typer subapp with list, search, dump, update, root, and remote commands.
    """
    sub = typer.Typer(
        name=source.name,
        help=source.description or f"Commands for source '{source.name}'.",
        no_args_is_help=True,
    )
    _register_update(sub, source, clone_root_provider)
    _register_list(sub, source, clone_root_provider)
    _register_search(sub, source, clone_root_provider)
    _register_dump(sub, source, clone_root_provider)
    _register_root(sub, source, clone_root_provider)
    _register_remote(sub, source)
    return sub


def _register_update(
    sub: typer.Typer,
    source: Source,
    clone_root_provider: CloneRootProvider,
) -> None:
    @sub.command("update")
    def update_cmd() -> None:
        """Clone the source repo if absent, else pull.

        Raises:
            Exit: With code 2 if the git operation fails.
        """
        target = clone_root_provider(source)
        try:
            clone_or_pull(source, target)
        except GitError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc
        typer.echo(f"{source.name}: ok")


def _register_list(
    sub: typer.Typer,
    source: Source,
    clone_root_provider: CloneRootProvider,
) -> None:
    @sub.command("list")
    def list_cmd() -> None:
        """List the boilerplate names available in this source."""
        target = clone_root_provider(source)
        if not target.exists():
            _missing(source)
        for name in list_boilerplates(source, target):
            typer.echo(name)


def _register_search(
    sub: typer.Typer,
    source: Source,
    clone_root_provider: CloneRootProvider,
) -> None:
    @sub.command("search")
    def search_cmd(
        term: str = typer.Argument(..., help="Substring to search for."),
    ) -> None:
        """Search boilerplate names (case-insensitive substring)."""
        target = clone_root_provider(source)
        if not target.exists():
            _missing(source)
        for name in search_boilerplates(source, target, term):
            typer.echo(name)


def _register_dump(  # noqa: C901
    sub: typer.Typer,
    source: Source,
    clone_root_provider: CloneRootProvider,
) -> None:
    @sub.command("dump")
    def dump_cmd(  # noqa: C901
        names: list[str] = typer.Argument(..., help="Boilerplate name(s) to dump."),  # noqa: B008
        out: Path | None = typer.Option(  # noqa: B008
            None, "--out", help="Write output to this file instead of stdout."
        ),
        lock: bool = typer.Option(  # noqa: FBT001
            False,  # noqa: FBT003
            "--lock",
            help="Record this dump in cobo.lock (requires --out).",
        ),
    ) -> None:
        """Dump boilerplate(s) to stdout or a file, optionally recording in the lock.

        Raises:
            Exit: Code 1 if a name is not found or multi-dump is rejected;
                code 2 if --lock is used without --out.
        """
        target = clone_root_provider(source)
        if not target.exists():
            _missing(source)
        _enforce_multi_dump(source, names)
        if lock and out is None:
            typer.echo("--lock requires --out (a file path to track).", err=True)
            raise typer.Exit(2)
        commit_sha = current_commit_sha(target)
        try:
            content = render_dump(source, target, names, commit_sha)
        except UserError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        if out is None:
            typer.echo(content, nl=False)
            return
        out.write_bytes(content.encode("utf-8"))
        if lock:
            record_dump(
                source=source,
                clone_root=target,
                names=names,
                out_path=out,
                lock_path=resolve_lock_path(Path.cwd()),
                commit_sha=commit_sha,
            )


def _register_root(
    sub: typer.Typer,
    source: Source,
    clone_root_provider: CloneRootProvider,
) -> None:
    @sub.command("root")
    def root_cmd() -> None:
        """Print the clone path for this source."""
        typer.echo(str(clone_root_provider(source)))


def _register_remote(sub: typer.Typer, source: Source) -> None:
    @sub.command("remote")
    def remote_cmd() -> None:
        """Print the git URL for this source."""
        typer.echo(source.url)


def _missing(source: Source) -> None:
    """Tell the user they need to run update for this source.

    Raises:
        Exit: Always, with code 1.
    """
    typer.echo(
        f"Source '{source.name}' has not been cloned."
        f" Run `cobo {source.name} update` first.",
        err=True,
    )
    raise typer.Exit(1)


def _enforce_multi_dump(source: Source, names: list[str]) -> None:
    """Reject multiple names for sources where multi_dump is disabled.

    Raises:
        Exit: With code 1 when multi_dump is False and more than one name is given.
    """
    if not source.multi_dump and len(names) > 1:
        typer.echo(
            f"Source '{source.name}' does not allow multi-dump "
            f"(set multi_dump=true to enable). Got {len(names)} names.",
            err=True,
        )
        raise typer.Exit(1)
