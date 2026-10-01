r"""End-to-end tests for `dump --eol lf` line-ending normalization.

These pin the fix for the LF-enforcing-consumer problem: a block sealed with
``--eol lf`` has no CRLF line endings, so a downstream tool that normalizes line
terminators to LF (git ``eol=lf``) leaves the block byte-for-byte as sealed and
``cobo check`` stays green — unlike the default ``preserve`` policy. A lone CR
that is pattern content (macOS ``Icon[\r]``) survives ``lf`` untouched (#124).
"""

from __future__ import annotations

import os
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

    from typer.testing import Result

pytestmark = pytest.mark.integration

runner = CliRunner()

# macOS boilerplate carrying both a CRLF line ending (``.Trashes\r\n``) and a
# semantic lone CR: ``Icon[\r]`` is github/gitignore's char-class matching the
# macOS custom-icon file ``Icon\r``. ``lf`` must fix the first and keep the second.
_CR_BODY = "# macOS\n.DS_Store\nIcon[\r]\n.Trashes\r\n"
_ICON = b"\nIcon[\r]\n"
# A second CR-bearing boilerplate so multi-dump and per-fragment tests are real.
_CR_BODY2 = "# Windows\nThumbs.db\ndesktop.ini\r\n"


def _assert_lf_sealed(raw: bytes) -> None:
    r"""Assert ``raw`` has no CRLF yet still carries the semantic ``Icon[\r]`` CR."""
    assert b"\r\n" not in raw
    assert _ICON in raw


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
    (repo / "Windows.gitignore").write_bytes(_CR_BODY2.encode("utf-8"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)  # noqa: S603, S607
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _bump_upstream(clone: Path, *names: str) -> None:
    """Commit a new CRLF-terminated line to each boilerplate so sync re-renders.

    Without an upstream change ``sync`` sees no drift and never calls
    ``_rerender``, so the eol policy it re-applies would go untested.
    """
    for name in names:
        path = clone / f"{name}.gitignore"
        path.write_bytes(path.read_bytes() + b"bumped\r\n")
    _git(clone, "commit", "-q", "-am", "bump")


def _stdout_bytes(result: Result) -> bytes:
    r"""Return CliRunner stdout with the platform newline folded back to LF.

    The runner's text wrapper writes ``\n`` as ``os.linesep``, so on Windows
    every LF reaches ``stdout_bytes`` as CRLF; undo that so only the CRs cobo
    emitted remain.
    """
    return result.stdout_bytes.replace(os.linesep.encode(), b"\n")


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


def test_dump_eol_lf_strips_crlf_and_seal_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --eol lf` writes a CRLF-free block whose seal matches the LF body."""
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
    _assert_lf_sealed(raw)
    # The seal agrees with the on-disk (LF) body: integrity is intact.
    assert classify(raw.decode("utf-8"), "#") is BlockState.MATCH
    # The lock records the policy so sync will re-apply it.
    assert 'eol = "lf"' in (tmp_path / "cobo.lock").read_text(encoding="utf-8")


def test_preserve_keeps_cr_but_breaks_under_lf_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default preserve policy seals the CR, so an LF consumer breaks the seal.

    This is the failure the ``lf`` policy fixes: folding CRLF to LF (what git
    ``eol=lf`` does) turns an otherwise-clean block into MODIFIED.
    """
    app = _app(_clone_with_cr(tmp_path))
    monkeypatch.chdir(tmp_path)  # lock lands beside the output, like a real repo
    out = tmp_path / ".gitignore"
    result = runner.invoke(
        app, ["gitignore", "dump", "macOS", "--out", str(out), "--lock"]
    )
    assert result.exit_code == 0, result.output
    # Raw bytes: the upstream CRLF is sealed verbatim.
    sealed = out.read_bytes().decode("utf-8")
    assert "\r\n" in sealed
    assert classify(sealed, "#") is BlockState.MATCH
    # Simulate an LF-enforcing consumer (git ``text eol=lf``) rewriting the file.
    stripped = sealed.replace("\r\n", "\n")
    assert classify(stripped, "#") is BlockState.MODIFIED


def test_lf_block_survives_git_lf_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r"""An lf-sealed block is unchanged by a git-style CRLF->LF consumer.

    The positive counterpart of the preserve test above: the semantic
    ``Icon[\r]`` CR is not a line terminator, so git ``text eol=lf`` keeps it
    and the seal still matches.
    """
    app = _app(_clone_with_cr(tmp_path))
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    result = runner.invoke(
        app,
        ["gitignore", "dump", "macOS", "--eol", "lf", "--out", str(out), "--lock"],
    )
    assert result.exit_code == 0, result.output
    raw = out.read_bytes()
    assert _ICON in raw
    sealed = raw.decode("utf-8")
    assert sealed.replace("\r\n", "\n") == sealed
    assert classify(sealed, "#") is BlockState.MATCH


def test_sync_honors_persisted_lf_and_never_reintroduces_crlf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sync` re-applies the fragment's lf policy; the worktree CRLF stays stripped.

    The clone's boilerplate still carries the CRLF, so a naive re-render would
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
    _bump_upstream(clone, "macOS")

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
    assert b"\nbumped\n" in raw  # sync really re-rendered the new upstream
    _assert_lf_sealed(raw)
    assert classify(raw.decode("utf-8"), "#") is BlockState.MATCH
    # The lock keeps the lf policy across the sync.
    synced = read_lock(tmp_path / "cobo.lock")
    assert synced.fragments[0].eol == "lf"


def test_lock_import_preserves_lf_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-importing an lf-sealed fragment keeps eol="lf" (does not reset it).

    ``lock import`` does not rewrite the file, so silently downgrading to
    preserve would let the next sync re-introduce CRLF line endings.
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


def test_dump_eol_lf_to_stdout_strips_crlf(tmp_path: Path) -> None:
    """`dump --eol lf` without --out still emits CRLF-free content."""
    app = _app(_clone_with_cr(tmp_path))
    result = runner.invoke(app, ["gitignore", "dump", "macOS", "--eol", "lf"])
    assert result.exit_code == 0, result.output
    _assert_lf_sealed(_stdout_bytes(result))


def test_dump_preserve_to_stdout_keeps_crlf(tmp_path: Path) -> None:
    r"""Negative control: `dump --eol preserve` to stdout keeps the CRLF.

    Proves the CliRunner stdout bytes do not themselves strip `\r\n`, so the
    lf-stdout assertion above is meaningful rather than vacuously true.
    """
    app = _app(_clone_with_cr(tmp_path))
    result = runner.invoke(app, ["gitignore", "dump", "macOS", "--eol", "preserve"])
    assert result.exit_code == 0, result.output
    # Raw bytes: ``Result.output`` folds every CRLF to LF, hiding the CR.
    assert b"\r\n" in _stdout_bytes(result)


def test_redump_without_eol_keeps_lf_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-dumping without --eol keeps the fragment's lf policy (no silent reset).

    Regression for the footgun where an omitted --eol reverted an lf fragment to
    preserve and reintroduced the CRLF the policy exists to remove.
    """
    clone = _clone_with_cr(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    app = _app(clone)
    first = runner.invoke(
        app, ["gitignore", "dump", "macOS", "--eol", "lf", "--out", str(out), "--lock"]
    )
    assert first.exit_code == 0, first.output
    # Re-dump WITHOUT --eol (the common "refresh the pin" case).
    again = runner.invoke(
        app, ["gitignore", "dump", "macOS", "--out", str(out), "--lock"]
    )
    assert again.exit_code == 0, again.output
    _assert_lf_sealed(out.read_bytes())
    assert read_lock(tmp_path / "cobo.lock").fragments[0].eol == "lf"


def test_explicit_preserve_overrides_stored_lf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit `--eol preserve` intentionally downgrades a stored lf fragment."""
    clone = _clone_with_cr(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    app = _app(clone)
    runner.invoke(
        app, ["gitignore", "dump", "macOS", "--eol", "lf", "--out", str(out), "--lock"]
    )
    override = runner.invoke(
        app,
        [
            "gitignore",
            "dump",
            "macOS",
            "--eol",
            "preserve",
            "--out",
            str(out),
            "--lock",
        ],
    )
    assert override.exit_code == 0, override.output
    assert b"\r\n" in out.read_bytes()
    assert read_lock(tmp_path / "cobo.lock").fragments[0].eol == "preserve"


def test_multi_boilerplate_eol_lf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--eol lf` normalizes a multi-boilerplate dump and both headers survive."""
    clone = _clone_with_cr(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    result = runner.invoke(
        _app(clone),
        [
            "gitignore",
            "dump",
            "macOS",
            "Windows",
            "--eol",
            "lf",
            "--out",
            str(out),
            "--lock",
        ],
    )
    assert result.exit_code == 0, result.output
    raw = out.read_bytes()
    _assert_lf_sealed(raw)
    text = raw.decode("utf-8")
    assert classify(text, "#") is BlockState.MATCH
    both_headers = 2  # one provenance header per boilerplate
    assert text.count("Generated by cobo") == both_headers


def test_content_edit_on_lf_block_is_still_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine content edit to an lf-sealed block is MODIFIED (drift not laundered).

    Guards the contract "survive LF re-encoding without blinding integrity checks":
    normalization must not make `check`/`classify` swallow real edits.
    """
    clone = _clone_with_cr(tmp_path)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    runner.invoke(
        _app(clone),
        ["gitignore", "dump", "macOS", "--eol", "lf", "--out", str(out), "--lock"],
    )
    text = out.read_bytes().decode("utf-8")
    edited = text.replace(".DS_Store\n", ".DS_Store\n.env\n", 1)
    assert edited != text
    assert classify(edited, "#") is BlockState.MODIFIED


def test_sync_isolates_per_fragment_eol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One lock with an lf and a preserve fragment: sync keeps each policy separate."""
    clone = _clone_with_cr(tmp_path)
    monkeypatch.chdir(tmp_path)
    app = _app(clone)
    a = tmp_path / "a.gitignore"
    b = tmp_path / "b.gitignore"
    runner.invoke(
        app, ["gitignore", "dump", "macOS", "--eol", "lf", "--out", str(a), "--lock"]
    )
    runner.invoke(
        app,
        [
            "gitignore",
            "dump",
            "Windows",
            "--eol",
            "preserve",
            "--out",
            str(b),
            "--lock",
        ],
    )
    _bump_upstream(clone, "macOS", "Windows")
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
    assert b"\nbumped\n" in a.read_bytes()  # both fragments were re-rendered
    assert b"\nbumped\r\n" in b.read_bytes()
    _assert_lf_sealed(a.read_bytes())  # lf fragment stays CRLF-free
    assert b"\r\n" in b.read_bytes()  # preserve fragment keeps its CRLF
    eols = {f.path: f.eol for f in read_lock(tmp_path / "cobo.lock").fragments}
    assert eols == {"a.gitignore": "lf", "b.gitignore": "preserve"}
