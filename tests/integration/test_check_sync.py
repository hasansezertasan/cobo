"""Integration tests for record/check/sync against local clones."""

from __future__ import annotations

import subprocess  # noqa: S404
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from cobo import globals as cobo_globals
from cobo.commands import check as check_module
from cobo.commands import record as record_module
from cobo.commands import sync as sync_module
from cobo.commands.check import run_check
from cobo.commands.lock_import import run_import
from cobo.commands.record import record_dump
from cobo.commands.sync import run_sync
from cobo.config.schema import CoboConfig, Source
from cobo.errors import UserError
from cobo.globals import attach_globals
from cobo.lock.io import read_lock, write_lock
from cobo.lock.schema import Fragment, LockedFile, Lockfile, is_full_sha
from cobo.source_commands import build_source_subapp
from cobo.sources import managed
from cobo.sources.render import dump as render_dump
from cobo.sources.repo import clone_or_pull, current_commit_sha

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.integration

runner = CliRunner()


def _body(path: Path, source: Source) -> str:
    """Return the managed-block body of a tracked file (markers stripped).

    Returns:
        The content cobo owns between the begin/end markers.
    """
    text = path.read_text(encoding="utf-8")
    return managed.parse(text, source.comment_prefix).body


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
    # Content-addressed drift key; SHA-1 (40) or SHA-256 (64), not a fixed width.
    assert is_full_sha(frag.files[0].blob)


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
    assert _body(out, source) == "*.pyc\n"
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
    assert _body(tmp_path / ".gitignore", source) == "*.pyc\n*.pyo\n"
    assert read_lock(lock_path).fragments[0].files[0].blob != old_blob


def test_sync_dry_run_writes_nothing(tmp_path: Path) -> None:
    """dry_run reports changes but does not touch files or the lock."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    old_commit = read_lock(lock_path).fragments[0].files[0].commit
    out = tmp_path / ".gitignore"
    before = managed.wrap("*.pyc\n", source.comment_prefix)
    # write_bytes, not write_text: cobo always writes LF, and write_text would
    # translate to CRLF on Windows and mismatch the LF-based block hash.
    out.write_bytes(before.encode("utf-8"))
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
    assert out.read_bytes() == before.encode("utf-8")  # unchanged
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


def test_sync_isolates_one_fragment_advances_sibling(tmp_path: Path) -> None:
    """One failing fragment is isolated while a healthy sibling still syncs.

    Guards the per-fragment isolation loop: the survivor's output is rewritten
    and its lock entry advanced, while the failed fragment keeps its old entry.
    """
    source, clone = make_source(
        tmp_path,
        {"Python.gitignore": "*.pyc\n", "Node.gitignore": "node_modules/\n"},
    )
    clone_or_pull(source, clone)
    # Record two fragments: ".gitignore" (Python) and "node.gitignore" (Node).
    py_lock = tmp_path / "cobo.lock"
    record_dump(
        source=source,
        clone_root=clone,
        names=["Python"],
        out_path=tmp_path / ".gitignore",
        lock_path=py_lock,
        commit_sha=current_commit_sha(clone),
    )
    record_dump(
        source=source,
        clone_root=clone,
        names=["Node"],
        out_path=tmp_path / "node.gitignore",
        lock_path=py_lock,
        commit_sha=current_commit_sha(clone),
    )
    old_node_blob = next(
        f.files[0].blob
        for f in read_lock(py_lock).fragments
        if f.path == "node.gitignore"
    )
    # Both drift, but Python's tracked file is deleted upstream (un-syncable).
    advance_source(tmp_path, "Node.gitignore", "node_modules/\ndist/\n")
    delete_from_source(tmp_path, "Python.gitignore")

    result = run_sync(
        read_lock(py_lock),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=py_lock,
    )

    assert result.changed == ("node.gitignore",)
    assert tuple(f.path for f in result.failed) == (".gitignore",)
    lock = read_lock(py_lock)
    node = next(f for f in lock.fragments if f.path == "node.gitignore")
    py = next(f for f in lock.fragments if f.path == ".gitignore")
    assert node.files[0].blob != old_node_blob  # survivor advanced
    assert py.files[0].path == "Python.gitignore"  # failed entry untouched
    assert _body(tmp_path / "node.gitignore", source) == "node_modules/\ndist/\n"


def test_sync_rerenders_multi_file_fragment_on_partial_drift(tmp_path: Path) -> None:
    """A fragment of several files re-renders fully when only one file drifts."""
    source, clone = make_source(
        tmp_path,
        {"Python.gitignore": "*.pyc\n", "Node.gitignore": "node_modules/\n"},
    )
    clone_or_pull(source, clone)
    # One fragment concatenating two input files.
    lock_path = _record(tmp_path, source, clone, ["Python", "Node"])
    frag = read_lock(lock_path).fragments[0]
    assert tuple(f.path for f in frag.files) == ("Python.gitignore", "Node.gitignore")
    py_blob = frag.files[0].blob
    node_blob = frag.files[1].blob
    # Only the Node input drifts upstream.
    advance_source(tmp_path, "Node.gitignore", "node_modules/\ndist/\n")

    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )

    assert result.changed == (".gitignore",)
    out = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "*.pyc" in out  # unchanged input still rendered
    assert "dist/" in out  # drifted input picked up
    new_files = read_lock(lock_path).fragments[0].files
    assert new_files[0].blob == py_blob  # unchanged file keeps its blob
    assert new_files[1].blob != node_blob  # drifted file advanced


def _record_two(tmp_path: Path, source: Source, clone: Path) -> Path:
    """Record two fragments (.gitignore from Python, node.gitignore from Node).

    Returns:
        The path to the written cobo.lock.
    """
    lock_path = tmp_path / "cobo.lock"
    for name, out in (("Python", ".gitignore"), ("Node", "node.gitignore")):
        record_dump(
            source=source,
            clone_root=clone,
            names=[name],
            out_path=tmp_path / out,
            lock_path=lock_path,
            commit_sha=current_commit_sha(clone),
        )
    return lock_path


def test_check_exclude_skips_matching_fragment(tmp_path: Path) -> None:
    """--exclude drops a drifted fragment from evaluation and the result."""
    source, clone = make_source(
        tmp_path,
        {"Python.gitignore": "*.pyc\n", "Node.gitignore": "node_modules/\n"},
    )
    clone_or_pull(source, clone)
    lock_path = _record_two(tmp_path, source, clone)
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")

    result = run_check(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        exclude=[".gitignore"],
    )

    assert result.outdated_count == 0  # the only drift was excluded
    assert all(r.path != ".gitignore" for r in result.reports)


def test_sync_exclude_leaves_fragment_untouched(tmp_path: Path) -> None:
    """An excluded, drifted fragment is left as-is in the file and the lock."""
    source, clone = make_source(
        tmp_path,
        {"Python.gitignore": "*.pyc\n", "Node.gitignore": "node_modules/\n"},
    )
    clone_or_pull(source, clone)
    lock_path = _record_two(tmp_path, source, clone)
    out = tmp_path / ".gitignore"
    out.write_text("*.pyc\n", encoding="utf-8")
    old_blob = next(
        f.files[0].blob
        for f in read_lock(lock_path).fragments
        if f.path == ".gitignore"
    )
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")

    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
        exclude=[".gitignore"],
    )

    assert ".gitignore" not in result.changed
    assert out.read_text(encoding="utf-8") == "*.pyc\n"  # file untouched
    # Excluded entry is preserved verbatim in the rewritten lock.
    py = next(f for f in read_lock(lock_path).fragments if f.path == ".gitignore")
    assert py.files[0].blob == old_blob


def _dump_with_header(tmp_path: Path, files: dict[str, str]) -> tuple[Source, Path]:
    """Make a header-injecting source and clone it.

    Returns:
        The header-injecting Source and its clone path.
    """
    source, clone = make_source(tmp_path, files)
    source = replace(source, inject_header=True)
    clone_or_pull(source, clone)
    return source, clone


def test_lock_import_adopts_file_from_header(tmp_path: Path) -> None:
    """Import reconstructs a lock entry from a dumped file's provenance header."""
    source, clone = _dump_with_header(tmp_path, {"Python.gitignore": "*.pyc\n"})
    out = tmp_path / ".gitignore"
    out.write_text(
        render_dump(source, clone, ["Python"], current_commit_sha(clone)),
        encoding="utf-8",
    )
    lock_path = tmp_path / "cobo.lock"

    result = run_import(
        [out], {source.name: source}, _provider_factory(clone), lock_path=lock_path
    )

    assert result.failed == ()
    assert tuple(i.path for i in result.imported) == (str(out),)
    frag = read_lock(lock_path).fragments[0]
    assert frag.path == ".gitignore"
    assert frag.source == source.name
    assert frag.files[0].name == "Python"


def test_lock_import_multi_name_records_all_inputs(tmp_path: Path) -> None:
    """A multi-dump file with several headers imports every input boilerplate."""
    source, clone = _dump_with_header(
        tmp_path,
        {"Python.gitignore": "*.pyc\n", "Node.gitignore": "node_modules/\n"},
    )
    out = tmp_path / ".gitignore"
    out.write_text(
        render_dump(source, clone, ["Python", "Node"], current_commit_sha(clone)),
        encoding="utf-8",
    )
    lock_path = tmp_path / "cobo.lock"

    result = run_import(
        [out], {source.name: source}, _provider_factory(clone), lock_path=lock_path
    )

    assert result.imported[0].count == 2  # noqa: PLR2004
    names = [f.name for f in read_lock(lock_path).fragments[0].files]
    assert names == ["Python", "Node"]


def test_lock_import_no_header_is_a_failure(tmp_path: Path) -> None:
    """A file lacking a cobo header is reported as failed, not crashed."""
    source, clone = _dump_with_header(tmp_path, {"Python.gitignore": "*.pyc\n"})
    out = tmp_path / ".gitignore"
    out.write_text("*.pyc\n", encoding="utf-8")  # no header
    lock_path = tmp_path / "cobo.lock"

    result = run_import(
        [out], {source.name: source}, _provider_factory(clone), lock_path=lock_path
    )

    assert result.imported == ()
    assert tuple(f.path for f in result.failed) == (str(out),)
    assert "no cobo provenance header" in result.failed[0].reason
    assert not lock_path.exists()


def test_lock_import_unknown_source_is_a_failure(tmp_path: Path) -> None:
    """A header naming a source absent from config is a failure, isolated per file."""
    source, clone = _dump_with_header(tmp_path, {"Python.gitignore": "*.pyc\n"})
    out = tmp_path / ".gitignore"
    out.write_text(
        render_dump(source, clone, ["Python"], current_commit_sha(clone)),
        encoding="utf-8",
    )

    result = run_import(
        [out], {}, _provider_factory(clone), lock_path=tmp_path / "cobo.lock"
    )

    assert tuple(f.path for f in result.failed) == (str(out),)
    assert f"unknown source '{source.name}'" in result.failed[0].reason


def test_lock_import_mixed_sources_is_a_failure(tmp_path: Path) -> None:
    """A file whose headers reference two sources is rejected (before any clone)."""
    source, clone = _dump_with_header(tmp_path, {"Python.gitignore": "*.pyc\n"})
    marker = "# Generated by cobo (github.com/hasansezertasan/cobo)"
    content = (
        f"{marker}\n# gi/Python@5763345 — https://example.com/a\n*.pyc\n\n"
        f"{marker}\n# other/Node@5763345 — https://example.com/b\nnode_modules/\n"
    )
    out = tmp_path / ".gitignore"
    out.write_text(content, encoding="utf-8")

    result = run_import(
        [out], {source.name: source}, _provider_factory(clone), lock_path=tmp_path / "x"
    )

    assert tuple(f.path for f in result.failed) == (str(out),)
    assert "multiple sources" in result.failed[0].reason


def test_lock_import_preserves_held_flag(tmp_path: Path) -> None:
    """Re-importing a held fragment keeps update=false."""
    source, clone = _dump_with_header(tmp_path, {"Python.gitignore": "*.pyc\n"})
    out = tmp_path / ".gitignore"
    out.write_text(
        render_dump(source, clone, ["Python"], current_commit_sha(clone)),
        encoding="utf-8",
    )
    lock_path = tmp_path / "cobo.lock"
    run_import(
        [out], {source.name: source}, _provider_factory(clone), lock_path=lock_path
    )
    lock = read_lock(lock_path)
    write_lock(
        lock_path,
        Lockfile(version=1, fragments=(replace(lock.fragments[0], update=False),)),
    )

    run_import(
        [out], {source.name: source}, _provider_factory(clone), lock_path=lock_path
    )

    assert read_lock(lock_path).fragments[0].update is False


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
    assert _body(tmp_path / ".gitignore", source) == "NESTED2\n"
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


def test_check_refresh_picks_up_upstream_change(tmp_path: Path) -> None:
    """run_check(refresh=True) re-pulls the clone, so it detects drift itself.

    Pairs with test_check_without_refresh_uses_existing_clone: the *same* setup
    reports clean without a refresh but outdated with one — proving the refresh
    is what surfaces the drift (the central `cobo check` flow in CI).
    """
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    # Without a refresh the stale clone still matches the lock.
    stale = run_check(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        refresh=False,
    )
    assert stale.outdated_count == 0
    # With the default refresh, run_check pulls and then sees the drift.
    refreshed = run_check(
        read_lock(lock_path), {source.name: source}, _provider_factory(clone)
    )
    assert refreshed.outdated_count == 1


def test_sync_lock_write_failure_raises_user_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the lock cannot be written after re-rendering, run_sync raises UserError.

    The output file is already rewritten on disk; surfacing a UserError (instead
    of a raw OSError traceback) lets the CLI report the partial state cleanly.
    """
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")

    def _boom(*_args: object, **_kwargs: object) -> None:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(sync_module, "write_lock", _boom)
    with pytest.raises(UserError, match="could not update"):
        run_sync(
            read_lock(lock_path),
            {source.name: source},
            _provider_factory(clone),
            lock_dir=tmp_path,
            lock_path=lock_path,
        )
    # The working tree was modified even though the lock did not advance.
    assert _body(tmp_path / ".gitignore", source) == "*.pyc\n*.pyo\n"


def _global_app(
    source: Source, clone: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> typer.Typer:
    """Build the real CLI app wired to a local source clone.

    Returns:
        A Typer app with global commands whose clone provider points at ``clone``.
    """
    monkeypatch.setattr(cobo_globals, "source_clone_root", lambda _name: clone)
    app = typer.Typer()
    attach_globals(
        app,
        config=CoboConfig(default_branch="main", sources={source.name: source}),
        cache_root=tmp_path,
        user_config_file=tmp_path / "config.toml",
    )
    return app


def test_check_cli_real_drift_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: real upstream drift drives `cobo check` to exit code 1.

    Joins the two halves the other tests cover separately — drift detection and
    the exit-code mapping — through the actual CLI command.
    """
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    _record(tmp_path, source, clone, ["Python"])
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(_global_app(source, clone, monkeypatch, tmp_path), ["check"])
    assert result.exit_code == 1, result.output
    assert "outdated" in result.output


def test_sync_cli_real_drift_advances_and_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: `cobo sync` re-renders a drifted fragment and exits 0."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    _record(tmp_path, source, clone, ["Python"])
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(_global_app(source, clone, monkeypatch, tmp_path), ["sync"])
    assert result.exit_code == 0, result.output
    assert "updated: .gitignore" in result.output
    assert _body(tmp_path / ".gitignore", source) == "*.pyc\n*.pyo\n"


def test_dump_lock_with_malformed_existing_lock_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --lock` over a malformed cobo.lock exits 2 cleanly, not a traceback."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cobo.lock").write_text("this = is not (valid toml", encoding="utf-8")
    out = tmp_path / ".gitignore"
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", "Python", "--out", str(out), "--lock"])
    assert result.exit_code == 2, result.output  # noqa: PLR2004
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_sync_cli_dry_run_over_real_drift_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cobo sync --dry-run` over real drift exits 0 and writes nothing.

    Guards the CLI dry-run path end-to-end: a regression that stopped threading
    ``--dry-run`` into ``run_sync`` would advance the lock and rewrite the
    output, which this catches by asserting both are byte-for-byte unchanged.
    """
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / ".gitignore"
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    dumped = runner.invoke(sub, ["dump", "Python", "--out", str(out), "--lock"])
    assert dumped.exit_code == 0, dumped.output
    lock_path = tmp_path / "cobo.lock"
    out_before = out.read_bytes()
    lock_before = lock_path.read_bytes()
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    result = runner.invoke(
        _global_app(source, clone, monkeypatch, tmp_path), ["sync", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == out_before
    assert lock_path.read_bytes() == lock_before


def test_check_multi_file_fragment_one_input_deleted_reports_drift(
    tmp_path: Path,
) -> None:
    """A multi-file fragment with one input removed upstream drifts, not errors.

    Exercises ``gather_current_blobs``' distinction: an absent path maps to None
    (legitimate drift via ``FileAbsentError``) while the surviving file is
    unaffected, so the fragment is ``outdated`` and never ``error``.
    """
    source, clone = make_source(
        tmp_path,
        {"Python.gitignore": "*.pyc\n", "Node.gitignore": "node_modules/\n"},
    )
    clone_or_pull(source, clone)
    _record(tmp_path, source, clone, ["Python", "Node"])
    delete_from_source(tmp_path, "Node.gitignore")
    result = run_check(
        read_lock(tmp_path / "cobo.lock"),
        {source.name: source},
        _provider_factory(clone),
    )
    report = result.reports[0]
    assert report.error is None, report.error
    assert report.outdated
    assert {d.path for d in report.drifts} == {"Node.gitignore"}
    assert report.drifts[0].new_blob is None


def _dump_managed(tmp_path: Path, source: Source, clone: Path, name: str) -> Path:
    """Dump a single boilerplate to `.gitignore` with --lock; return the path.

    Returns:
        The written, managed output file.
    """
    out = tmp_path / ".gitignore"
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", name, "--out", str(out), "--lock"])
    assert result.exit_code == 0, result.output
    return out


def test_sync_preserves_user_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user's content below the end marker survives a block-refreshing sync."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = _dump_managed(tmp_path, source, clone, "Python")
    out.write_text(
        out.read_text(encoding="utf-8") + "my/custom/rule\n", encoding="utf-8"
    )
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    lock_path = tmp_path / "cobo.lock"

    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert result.changed == (".gitignore",)
    parsed = managed.parse(out.read_text(encoding="utf-8"), source.comment_prefix)
    assert parsed.body == "*.pyc\n*.pyo\n"  # block refreshed
    assert parsed.tail == "my/custom/rule\n"  # user tail preserved


def test_sync_refuses_locally_edited_block_then_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand-edited managed block is refused; --force overwrites it."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = _dump_managed(tmp_path, source, clone, "Python")
    out.write_text(
        out.read_text(encoding="utf-8").replace("*.pyc", "*.HACKED"), encoding="utf-8"
    )
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    lock_path = tmp_path / "cobo.lock"

    refused = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert refused.changed == ()
    assert tuple(f.path for f in refused.failed) == (".gitignore",)
    assert "edited locally" in refused.failed[0].reason
    assert "*.HACKED" in out.read_text(encoding="utf-8")  # untouched

    forced = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
        force=True,
    )
    assert forced.changed == (".gitignore",)
    assert _body(out, source) == "*.pyc\n*.pyo\n"


def test_sync_refuses_missing_markers_then_force(tmp_path: Path) -> None:
    """A tracked file with no markers is refused; --force rebuilds it fresh."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    out = tmp_path / ".gitignore"
    out.write_text("hand-written, no markers\n", encoding="utf-8")  # legacy file
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")

    refused = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert refused.changed == ()
    assert "no cobo" in refused.failed[0].reason

    forced = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
        force=True,
    )
    assert forced.changed == (".gitignore",)
    assert _body(out, source) == "*.pyc\n*.pyo\n"
    assert "hand-written" not in out.read_text(encoding="utf-8")


def test_dump_lock_redump_preserves_user_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running `dump --lock` over an existing managed file keeps the user tail."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = _dump_managed(tmp_path, source, clone, "Python")
    out.write_text(out.read_text(encoding="utf-8") + "keep-me\n", encoding="utf-8")

    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    redump = runner.invoke(sub, ["dump", "Python", "--out", str(out), "--lock"])
    assert redump.exit_code == 0, redump.output
    parsed = managed.parse(out.read_text(encoding="utf-8"), source.comment_prefix)
    assert parsed.tail == "keep-me\n"


def test_check_reports_locally_modified_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check flags a hand-edited managed block and fails (exit 1)."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = _dump_managed(tmp_path, source, clone, "Python")
    out.write_text(
        out.read_text(encoding="utf-8").replace("*.pyc", "*.HACKED"), encoding="utf-8"
    )
    lock_path = tmp_path / "cobo.lock"

    result = run_check(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
    )
    assert result.reports[0].local_state is managed.BlockState.MODIFIED
    assert result.locally_modified_count == 1
    assert result.exit_code() == 1


def test_check_local_state_absent_and_unreadable(tmp_path: Path) -> None:
    """Check maps a missing output to ABSENT and an unreadable one to None."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])  # lock only, no file

    absent = run_check(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
    )
    assert absent.reports[0].local_state is managed.BlockState.ABSENT

    (tmp_path / ".gitignore").mkdir()  # a directory: read_text raises OSError
    unreadable = run_check(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
    )
    assert unreadable.reports[0].local_state is None


def test_sync_cli_force_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`cobo sync --force` overwrites a locally edited block via the CLI."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = _dump_managed(tmp_path, source, clone, "Python")
    out.write_text(
        out.read_text(encoding="utf-8").replace("*.pyc", "*.HACKED"), encoding="utf-8"
    )
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")

    app = _global_app(source, clone, monkeypatch, tmp_path)
    refused = runner.invoke(app, ["sync"])
    assert refused.exit_code == 1, refused.output
    forced = runner.invoke(app, ["sync", "--force"])
    assert forced.exit_code == 0, forced.output
    assert _body(out, source) == "*.pyc\n*.pyo\n"


def test_check_cli_reports_locally_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cobo check` surfaces a locally modified block in its summary and exits 1."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = _dump_managed(tmp_path, source, clone, "Python")
    out.write_text(
        out.read_text(encoding="utf-8").replace("*.pyc", "*.HACKED"), encoding="utf-8"
    )
    result = runner.invoke(_global_app(source, clone, monkeypatch, tmp_path), ["check"])
    assert result.exit_code == 1, result.output
    assert "edited locally" in result.output


def test_dump_out_write_failure_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed output write is a clean exit 1, not a raw traceback."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "a-directory"
    out.mkdir()  # writing bytes to a directory raises OSError
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(sub, ["dump", "Python", "--out", str(out)])
    assert result.exit_code == 1, result.output
    assert "Could not write" in result.output


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (b"hand-written, no markers\n", "MISSING"),
        (None, "MALFORMED"),  # duplicate begin marker, filled in below
    ],
)
def test_check_flags_unsyncable_markers_as_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: bytes | None, expected: str
) -> None:
    """MISSING/MALFORMED marker states count toward sync_blocked_count (exit 1)."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    out = _dump_managed(tmp_path, source, clone, "Python")
    if mutate is not None:
        out.write_bytes(mutate)
    else:  # duplicate the block -> two begin markers -> MALFORMED
        out.write_bytes(out.read_bytes() * 2)

    result = run_check(
        read_lock(tmp_path / "cobo.lock"),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
    )
    assert result.reports[0].local_state is getattr(managed.BlockState, expected)
    assert result.sync_blocked_count == 1
    assert result.exit_code() == 1


def test_check_invalid_clone_without_refresh_reports_error(tmp_path: Path) -> None:
    """A blob read against a non-repo clone (refresh skipped) is a fragment error."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    not_repo = tmp_path / "not_a_repo"
    not_repo.mkdir()
    result = run_check(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(not_repo),
        refresh=False,
        lock_dir=tmp_path,
    )
    assert result.reports[0].error is not None


def test_check_refreshes_each_source_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two fragments from one source trigger a single clone_or_pull, not two."""
    source, clone = make_source(
        tmp_path,
        {"Python.gitignore": "*.pyc\n", "Node.gitignore": "node_modules/\n"},
    )
    clone_or_pull(source, clone)
    lock_path = tmp_path / "cobo.lock"
    for name, out in (("Python", ".gitignore"), ("Node", "node.gitignore")):
        record_dump(
            source=source,
            clone_root=clone,
            names=[name],
            out_path=tmp_path / out,
            lock_path=lock_path,
            commit_sha=current_commit_sha(clone),
        )
    calls: list[str] = []
    monkeypatch.setattr(
        check_module, "clone_or_pull", lambda s, _r: calls.append(s.name)
    )
    run_check(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
    )
    assert calls == ["gi"]  # one refresh for the shared source, not one per fragment


def test_dump_lock_file_override_writes_custom_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dump --lock --lock-file PATH` records into the given lockfile, not cwd.

    The lock and its output sit in the same directory so the recorded fragment
    path stays relative (no ``..``, which the schema rejects).
    """
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    out = proj / ".gitignore"
    custom = proj / "cobo.lock"
    sub = build_source_subapp(source, clone_root_provider=lambda _s: clone)
    result = runner.invoke(
        sub,
        ["dump", "Python", "--out", str(out), "--lock", "--lock-file", str(custom)],
    )
    assert result.exit_code == 0, result.output
    assert custom.is_file()  # written at the override path
    assert not (tmp_path / "cobo.lock").exists()  # not the default cwd location
    assert read_lock(custom).fragments[0].path == ".gitignore"
