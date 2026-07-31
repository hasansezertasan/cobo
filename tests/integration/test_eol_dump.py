"""End-to-end tests for `dump --eol lf` line-ending normalization.

These pin the fix for the LF-enforcing-consumer problem: a block sealed with
``--eol lf`` has no carriage returns, so a downstream tool that normalizes to LF
(copier, git ``eol=lf``) leaves the block byte-for-byte as sealed and
``cobo check`` stays green — unlike the default ``preserve`` policy.
"""

from __future__ import annotations

import subprocess  # noqa: S404
from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from cobo.commands.lock_import import run_import
from cobo.commands.sync import run_sync
from cobo.config.schema import Source
from cobo.lock.io import read_lock
from cobo.source_commands import build_source_subapp
from cobo.sources.managed import BlockState, classify

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

runner = CliRunner()

# A boilerplate carrying the macOS lone-CR trick (``Icon\r``) that upstream
# github/gitignore ships and that LF-enforcing consumers rewrite.
_CR_BODY = "# macOS\n.DS_Store\nIcon\r\n.Trashes\n"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],  # noqa: S607
        check=True,
    )


def _clone_with_cr(tmp_path: Path) -> Path:
    """Materialize a fake gitignore clone whose boilerplate contains a lone CR.

    Returns:
        Path to the initialized git repo directory.
    """
    repo = tmp_path / "clone"
    repo.mkdir()
    (repo / "macOS.gitignore").write_bytes(_CR_BODY.encode("utf-8"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)  # noqa: S603, S607
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _app(clone: Path) -> typer.Typer:
    source = Source(
        name="gitignore",
        url="https://example.com/g.git",
        extension=".gitignore",
        multi_dump=True,
        inject_header=True,
    )
    parent = typer.Typer()
    parent.add_typer(
        build_source_subapp(source, clone_root_provider=lambda _s: clone),
        name="gitignore",
    )
    return parent


def test_dump_eol_lf_strips_cr_and_seal_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --eol lf` writes a CR-free block whose seal matches the LF body."""
    app = _app(_clone_with_cr(tmp_path))
    monkeypatch.chdir(tmp_path)  # lock lands beside the output, like a real repo
    out = tmp_path / ".gitignore"
    result = runner.invoke(
        app,
        ["gitignore", "dump", "macOS", "--eol", "lf", "--out", str(out), "--lock"],
    )
    assert result.exit_code == 0, result.output
    # Assert on raw bytes: read_text would hide a CR via newline translation.
    raw = out.read_bytes()
    assert b"\r" not in raw
    # The seal agrees with the on-disk (LF) body: integrity is intact.
    assert classify(raw.decode("utf-8"), "#") is BlockState.MATCH
    # The lock records the policy so sync will re-apply it.
    assert 'eol = "lf"' in (tmp_path / "cobo.lock").read_text(encoding="utf-8")


def test_preserve_keeps_cr_but_breaks_under_lf_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default preserve policy seals the CR, so an LF consumer breaks the seal.

    This is the failure the ``lf`` policy fixes: stripping the CR (what copier /
    git eol=lf do) turns an otherwise-clean block into MODIFIED.
    """
    app = _app(_clone_with_cr(tmp_path))
    monkeypatch.chdir(tmp_path)  # lock lands beside the output, like a real repo
    out = tmp_path / ".gitignore"
    result = runner.invoke(
        app, ["gitignore", "dump", "macOS", "--out", str(out), "--lock"]
    )
    assert result.exit_code == 0, result.output
    # Raw bytes: the CR the macOS trick carries is sealed verbatim.
    sealed = out.read_bytes().decode("utf-8")
    assert "\r" in sealed
    assert classify(sealed, "#") is BlockState.MATCH
    # Simulate an LF-enforcing consumer rewriting the file.
    stripped = sealed.replace("\r\n", "\n").replace("\r", "\n")
    assert classify(stripped, "#") is BlockState.MODIFIED


def test_sync_honors_persisted_lf_and_never_reintroduces_cr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sync` re-applies the fragment's lf policy; the worktree CR stays stripped.

    The clone's boilerplate still carries the lone CR, so a naive re-render would
    put it back. Because the lock recorded eol="lf", sync normalizes again and
    the block stays byte-identical and intact.
    """
    clone = _clone_with_cr(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    dumped = runner.invoke(
        _app(clone),
        ["gitignore", "dump", "macOS", "--eol", "lf", "--out", str(out), "--lock"],
    )
    assert dumped.exit_code == 0, dumped.output

    source = Source(
        name="gitignore",
        url="https://example.com/g.git",
        extension=".gitignore",
        multi_dump=True,
        inject_header=True,
    )
    run_sync(
        read_lock(tmp_path / "cobo.lock"),
        {"gitignore": source},
        clone_root_provider=lambda _s: clone,
        lock_dir=tmp_path,
        lock_path=tmp_path / "cobo.lock",
        refresh=False,
        force=True,
    )
    raw = out.read_bytes()
    assert b"\r" not in raw
    assert classify(raw.decode("utf-8"), "#") is BlockState.MATCH
    # The lock keeps the lf policy across the sync.
    synced = read_lock(tmp_path / "cobo.lock")
    assert synced.fragments[0].eol == "lf"


def test_lock_import_preserves_lf_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-importing an lf-sealed fragment keeps eol="lf" (does not reset it).

    ``lock import`` does not rewrite the file, so silently downgrading to
    preserve would let the next sync re-introduce carriage returns.
    """
    clone = _clone_with_cr(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    dumped = runner.invoke(
        _app(clone),
        ["gitignore", "dump", "macOS", "--eol", "lf", "--out", str(out), "--lock"],
    )
    assert dumped.exit_code == 0, dumped.output

    source = Source(
        name="gitignore",
        url="https://example.com/g.git",
        extension=".gitignore",
        multi_dump=True,
        inject_header=True,
    )
    run_import(
        [out],
        {"gitignore": source},
        clone_root_provider=lambda _s: clone,
        lock_path=tmp_path / "cobo.lock",
        refresh=False,
    )
    assert read_lock(tmp_path / "cobo.lock").fragments[0].eol == "lf"


def test_dump_eol_lf_to_stdout_strips_cr(tmp_path: Path) -> None:
    """`dump --eol lf` without --out still emits LF-only content."""
    app = _app(_clone_with_cr(tmp_path))
    result = runner.invoke(app, ["gitignore", "dump", "macOS", "--eol", "lf"])
    assert result.exit_code == 0, result.output
    assert "\r" not in result.output
