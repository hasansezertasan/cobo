"""Integration tests for record/check/sync against local clones."""

from __future__ import annotations

import subprocess  # noqa: S404
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cobo.commands import record as record_module
from cobo.commands.check import run_check
from cobo.commands.record import record_dump
from cobo.commands.sync import run_sync
from cobo.config.schema import Source
from cobo.errors import UserError
from cobo.lock.io import read_lock, write_lock
from cobo.lock.schema import Fragment, LockedFile, Lockfile
from cobo.source_commands import build_source_subapp
from cobo.sources.repo import clone_or_pull, current_commit_sha

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.integration

runner = CliRunner()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],  # noqa: S607
        check=True,
    )


def make_source(tmp_path: Path, files: dict[str, str]) -> tuple[Source, Path]:
    """Create a bare upstream repo and return (Source, clone_path).

    Returns:
        A Source pointing at the bare repo and the path to clone into.
    """
    upstream = tmp_path / "upstream.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    for name, content in files.items():
        target = seed / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)  # noqa: S603, S607
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "seed")
    subprocess.run(  # noqa: S603
        ["git", "init", "-q", "--bare", "-b", "main", str(upstream)],  # noqa: S607
        check=True,
    )
    _git(seed, "remote", "add", "origin", str(upstream))
    _git(seed, "push", "-q", "origin", "main")
    source = Source(
        name="gi",
        url=str(upstream),
        extension=".gitignore",
        branch="main",
        multi_dump=True,
    )
    return source, tmp_path / "clone"


def advance_source(tmp_path: Path, name: str, content: str) -> None:
    """Commit a new version of ``name`` to the upstream and push."""
    seed = tmp_path / "seed"
    (seed / name).write_text(content, encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "update")
    _git(seed, "push", "-q", "origin", "main")


def delete_from_source(tmp_path: Path, name: str) -> None:
    """Delete ``name`` from the upstream repo and push the removal."""
    seed = tmp_path / "seed"
    (seed / name).unlink()
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "delete")
    _git(seed, "push", "-q", "origin", "main")


def test_record_dump_writes_lock_entry(tmp_path: Path) -> None:
    """record_dump persists a fragment with per-file path/commit/blob."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    out = tmp_path / ".gitignore"
    lock_path = tmp_path / "cobo.lock"
    record_dump(
        source=source,
        clone_root=clone,
        names=["Python"],
        out_path=out,
        lock_path=lock_path,
        commit_sha=current_commit_sha(clone),
    )
    lock = read_lock(lock_path)
    assert len(lock.fragments) == 1
    frag = lock.fragments[0]
    assert frag.path == ".gitignore"
    assert frag.source == "gi"
    assert frag.files[0].name == "Python"
    assert frag.files[0].path == "Python.gitignore"
    assert len(frag.files[0].blob) == 40  # noqa: PLR2004


def test_dump_lock_without_out_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --lock` without `--out` is a usage error (exit 2)."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", "Python", "--lock"])
    assert result.exit_code == 2, result.output  # noqa: PLR2004


def test_dump_out_and_lock_writes_file_and_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --out FILE --lock` writes the file and records it in cobo.lock."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", "Python", "--out", str(out), "--lock"])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == "*.pyc\n"
    lock = read_lock(tmp_path / "cobo.lock")
    assert lock.fragments[0].path == ".gitignore"
    assert lock.fragments[0].files[0].name == "Python"


def test_dump_out_creates_missing_parent_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --out` creates the output's parent directories if they are absent."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "nested" / "dir" / ".gitignore"
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", "Python", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == "*.pyc\n"


def test_record_dump_cross_drive_raises_user_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cross-drive output/lock pair is a clean UserError, not a raw traceback."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)

    def _raise_cross_drive(*_args: object, **_kwargs: object) -> str:
        msg = "path is on mount 'C:', start on mount 'D:'"
        raise ValueError(msg)

    monkeypatch.setattr(record_module.os.path, "relpath", _raise_cross_drive)
    with pytest.raises(UserError, match="different drives"):
        record_dump(
            source=source,
            clone_root=clone,
            names=["Python"],
            out_path=tmp_path / ".gitignore",
            lock_path=tmp_path / "cobo.lock",
            commit_sha=current_commit_sha(clone),
        )


def test_dump_lock_cross_drive_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --lock` surfaces a cross-drive record failure as exit 1, not a crash."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)

    def _raise_cross_drive(*_args: object, **_kwargs: object) -> str:
        msg = "path is on mount 'C:', start on mount 'D:'"
        raise ValueError(msg)

    monkeypatch.setattr(record_module.os.path, "relpath", _raise_cross_drive)
    out = tmp_path / ".gitignore"
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", "Python", "--out", str(out), "--lock"])
    assert result.exit_code == 1, result.output
    assert "different drives" in result.output


def _provider_factory(clone: Path) -> Callable[[Source], Path]:
    def provider(_source: Source) -> Path:
        return clone

    return provider


def _record(tmp_path: Path, source: Source, clone: Path, names: list[str]) -> Path:
    out = tmp_path / ".gitignore"
    lock_path = tmp_path / "cobo.lock"
    record_dump(
        source=source,
        clone_root=clone,
        names=names,
        out_path=out,
        lock_path=lock_path,
        commit_sha=current_commit_sha(clone),
    )
    return lock_path


def test_check_reports_no_drift_when_unchanged(tmp_path: Path) -> None:
    """A freshly recorded fragment shows no drift."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    result = run_check(
        read_lock(lock_path), {source.name: source}, _provider_factory(clone)
    )
    assert result.outdated_count == 0


def test_check_detects_drift_after_upstream_change(tmp_path: Path) -> None:
    """Advancing the upstream file makes the fragment outdated."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    result = run_check(
        read_lock(lock_path), {source.name: source}, _provider_factory(clone)
    )
    assert result.outdated_count == 1


def test_check_skips_held_fragment(tmp_path: Path) -> None:
    """update=False fragments are reported as held, never outdated."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    lock = read_lock(lock_path)
    held = replace(lock.fragments[0], update=False)
    write_lock(lock_path, Lockfile(version=1, fragments=(held,)))
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    result = run_check(
        read_lock(lock_path), {source.name: source}, _provider_factory(clone)
    )
    assert result.outdated_count == 0
    assert result.reports[0].held is True


def test_sync_rewrites_file_and_advances_lock(tmp_path: Path) -> None:
    """Sync re-renders the drifted file and updates its blob in the lock."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    old_blob = read_lock(lock_path).fragments[0].files[0].blob
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")

    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert result.changed == (".gitignore",)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "*.pyc\n*.pyo\n"
    assert read_lock(lock_path).fragments[0].files[0].blob != old_blob


def test_sync_dry_run_writes_nothing(tmp_path: Path) -> None:
    """dry_run reports changes but does not touch files or the lock."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    old_commit = read_lock(lock_path).fragments[0].files[0].commit
    out = tmp_path / ".gitignore"
    out.write_text("*.pyc\n", encoding="utf-8")
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")

    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
        dry_run=True,
    )
    assert result.changed == (".gitignore",)
    assert out.read_text(encoding="utf-8") == "*.pyc\n"  # unchanged
    assert read_lock(lock_path).fragments[0].files[0].commit == old_commit


def test_sync_skips_held_fragment(tmp_path: Path) -> None:
    """A held fragment is never rewritten."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    lock = read_lock(lock_path)
    write_lock(
        lock_path,
        Lockfile(version=1, fragments=(replace(lock.fragments[0], update=False),)),
    )
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert result.changed == ()


def test_sync_isolates_failed_fragment(tmp_path: Path) -> None:
    """If a tracked file vanishes upstream, sync isolates that fragment."""
    source, clone = make_source(
        tmp_path,
        {"Python.gitignore": "*.pyc\n", "Node.gitignore": "node_modules/\n"},
    )
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    delete_from_source(tmp_path, "Python.gitignore")
    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert result.changed == ()
    assert tuple(f.path for f in result.failed) == (".gitignore",)
    assert result.failed[0].reason  # the cause is captured, not discarded


def test_record_dump_preserves_held_flag(tmp_path: Path) -> None:
    """Re-recording a held (update=false) fragment must keep it held."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    out = tmp_path / ".gitignore"
    lock_path = tmp_path / "cobo.lock"
    record_dump(
        source=source,
        clone_root=clone,
        names=["Python"],
        out_path=out,
        lock_path=lock_path,
        commit_sha=current_commit_sha(clone),
    )
    # User pins the fragment as held.
    lock = read_lock(lock_path)
    write_lock(
        lock_path,
        Lockfile(version=1, fragments=(replace(lock.fragments[0], update=False),)),
    )
    # Re-record the same output: held flag must survive.
    record_dump(
        source=source,
        clone_root=clone,
        names=["Python"],
        out_path=out,
        lock_path=lock_path,
        commit_sha=current_commit_sha(clone),
    )
    assert read_lock(lock_path).fragments[0].update is False


def test_check_reports_error_when_source_unreachable(tmp_path: Path) -> None:
    """A fragment whose source clone fails is reported as error, not a crash."""
    bad = Source(
        name="x",
        url=str(tmp_path / "nonexistent.git"),
        extension=".gitignore",
        branch="main",
    )
    frag = Fragment(
        path=".gitignore",
        source="x",
        files=(
            LockedFile(name="P", path="P.gitignore", commit="a" * 40, blob="b" * 40),
        ),
    )
    result = run_check(
        Lockfile(version=1, fragments=(frag,)),
        {"x": bad},
        lambda _s: tmp_path / "clone",
    )
    assert result.outdated_count == 0
    assert result.reports[0].error is not None


def add_to_source(tmp_path: Path, name: str, content: str) -> None:
    """Add a new file ``name`` to the upstream repo and push."""
    seed = tmp_path / "seed"
    target = seed / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "add")
    _git(seed, "push", "-q", "origin", "main")


def test_sync_renders_locked_path_not_rediscovered_name(tmp_path: Path) -> None:
    """Sync re-renders the exact locked path even when a shorter same-stem path appears.

    (Issue A: render from locked paths, not rediscovered names.)
    """
    source, clone = make_source(tmp_path, {"sub/Python.gitignore": "NESTED\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    assert read_lock(lock_path).fragments[0].files[0].path == "sub/Python.gitignore"
    # A shorter same-stem path now exists upstream AND the locked file drifts.
    add_to_source(tmp_path, "Python.gitignore", "ROOT\n")
    advance_source(tmp_path, "sub/Python.gitignore", "NESTED2\n")
    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert result.changed == (".gitignore",)
    # Content must come from the LOCKED nested path, not the rediscovered root file.
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "NESTED2\n"
    assert read_lock(lock_path).fragments[0].files[0].path == "sub/Python.gitignore"


def test_sync_reports_unreachable_source_as_failure(tmp_path: Path) -> None:
    """A fragment whose source can't be evaluated is a failure, not a silent no-op."""
    bad = Source(
        name="x", url=str(tmp_path / "nope.git"), extension=".gitignore", branch="main"
    )
    frag = Fragment(
        path=".gitignore",
        source="x",
        files=(
            LockedFile(name="P", path="P.gitignore", commit="a" * 40, blob="b" * 40),
        ),
    )
    result = run_sync(
        Lockfile(version=1, fragments=(frag,)),
        {"x": bad},
        lambda _s: tmp_path / "clone",
        lock_dir=tmp_path,
        lock_path=tmp_path / "cobo.lock",
    )
    assert result.changed == ()
    assert tuple(f.path for f in result.failed) == (".gitignore",)


def test_sync_isolates_write_failure(tmp_path: Path) -> None:
    """An OSError writing the output is isolated as a failed fragment, not a crash."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    # Make the output path unwritable by turning it into a directory.
    # (_record does not write the output file, so we create the dir directly.)
    out = tmp_path / ".gitignore"
    out.mkdir()
    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert result.changed == ()
    assert tuple(f.path for f in result.failed) == (".gitignore",)


def test_check_without_refresh_uses_existing_clone(tmp_path: Path) -> None:
    """run_check(refresh=False) reads the existing clone without re-pulling."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    result = run_check(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        refresh=False,
    )
    assert result.outdated_count == 0


def test_dump_out_without_lock_writes_file_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --out FILE` (no --lock) writes the file and records nothing."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", "Python", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == "*.pyc\n"
    assert not (tmp_path / "cobo.lock").exists()
