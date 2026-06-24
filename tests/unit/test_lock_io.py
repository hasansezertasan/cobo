"""Tests for reading and writing cobo.lock."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cobo.errors import ConfigError
from cobo.lock.io import (
    LOCK_FILENAME,
    empty_lock,
    find_lock,
    read_lock,
    upsert_fragment,
    write_lock,
)
from cobo.lock.schema import Fragment, LockedFile, Lockfile

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _frag(path: str = ".gitignore", *, update: bool = True) -> Fragment:
    return Fragment(
        path=path,
        source="gitignore",
        update=update,
        files=(
            LockedFile(
                name="Python", path="Python.gitignore", commit="a" * 40, blob="b" * 40
            ),
        ),
    )


def test_write_then_read_roundtrips(tmp_path: Path) -> None:
    """A written lockfile parses back to an equal Lockfile."""
    lock = Lockfile(version=1, fragments=(_frag(), _frag("mise.toml", update=False)))
    target = tmp_path / LOCK_FILENAME
    write_lock(target, lock)
    assert read_lock(target) == lock


def test_write_is_atomic_no_temp_left_behind(tmp_path: Path) -> None:
    """Writing leaves only cobo.lock (no stray temp files)."""
    target = tmp_path / LOCK_FILENAME
    write_lock(target, Lockfile(version=1, fragments=(_frag(),)))
    assert [p.name for p in tmp_path.iterdir()] == [LOCK_FILENAME]


def test_find_lock_walks_upward(tmp_path: Path) -> None:
    """find_lock locates cobo.lock in a parent directory."""
    (tmp_path / LOCK_FILENAME).write_text("version = 1\n", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_lock(nested) == tmp_path / LOCK_FILENAME


def test_find_lock_returns_none_when_absent(tmp_path: Path) -> None:
    """find_lock returns None when no lockfile exists above start."""
    assert find_lock(tmp_path) is None


def test_read_rejects_unknown_version(tmp_path: Path) -> None:
    """An unsupported version raises ConfigError, never silent acceptance."""
    target = tmp_path / LOCK_FILENAME
    target.write_text("version = 99\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        read_lock(target)


def test_read_rejects_malformed_toml(tmp_path: Path) -> None:
    """Malformed TOML raises ConfigError."""
    target = tmp_path / LOCK_FILENAME
    target.write_text("version = = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        read_lock(target)


def test_upsert_replaces_existing_path() -> None:
    """upsert_fragment replaces a fragment with the same output path."""
    lock = empty_lock()
    lock = upsert_fragment(lock, _frag())
    replacement = Fragment(
        path=".gitignore",
        source="gitignore",
        files=(
            LockedFile(
                name="Node", path="Node.gitignore", commit="c" * 40, blob="d" * 40
            ),
        ),
    )
    lock = upsert_fragment(lock, replacement)
    assert len(lock.fragments) == 1
    assert lock.fragments[0].files[0].name == "Node"


def test_upsert_appends_new_path() -> None:
    """upsert_fragment appends when the output path is new."""
    lock = upsert_fragment(empty_lock(), _frag())
    lock = upsert_fragment(lock, _frag("mise.toml"))
    assert {f.path for f in lock.fragments} == {".gitignore", "mise.toml"}


def test_read_rejects_fragment_missing_required_key(tmp_path: Path) -> None:
    """A fragment file entry missing a required key raises ConfigError."""
    target = tmp_path / LOCK_FILENAME
    target.write_text(
        'version = 1\n\n[[fragment]]\npath = ".gitignore"\nsource = "gi"\n'
        'update = true\n\n  [[fragment.files]]\n  name = "Python"\n'
        '  path = "Python.gitignore"\n  commit = "abc"\n',  # missing `blob`
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        read_lock(target)


def test_string_values_are_escaped(tmp_path: Path) -> None:
    """Paths containing quotes/backslashes round-trip safely."""
    frag = Fragment(
        path='weird".gitignore',
        source="gitignore",
        files=(
            LockedFile(
                name="A\\B", path="dir/A.gitignore", commit="a" * 40, blob="b" * 40
            ),
        ),
    )
    target = tmp_path / LOCK_FILENAME
    write_lock(target, Lockfile(version=1, fragments=(frag,)))
    assert read_lock(target) == Lockfile(version=1, fragments=(frag,))
