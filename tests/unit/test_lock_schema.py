"""Tests for the lockfile dataclasses."""

import pytest

from cobo.lock.schema import Fragment, LockedFile, Lockfile

pytestmark = pytest.mark.unit


def _file() -> LockedFile:
    return LockedFile(
        name="Python", path="Python.gitignore", commit="a" * 40, blob="b" * 40
    )


def test_locked_file_is_frozen() -> None:
    """LockedFile instances are immutable."""
    locked = _file()
    with pytest.raises((AttributeError, TypeError)):
        locked.name = "Other"  # type: ignore[misc]


def test_fragment_defaults_to_update_true() -> None:
    """A Fragment created without `update` defaults to True."""
    frag = Fragment(path=".gitignore", source="gitignore", files=(_file(),))
    assert frag.update is True


def test_fragment_can_be_pinned() -> None:
    """update=False marks a held-back fragment."""
    frag = Fragment(path="mise.toml", source="mise", files=(_file(),), update=False)
    assert frag.update is False


def test_lockfile_holds_version_and_fragments() -> None:
    """Lockfile carries a schema version and a tuple of fragments."""
    frag = Fragment(path=".gitignore", source="gitignore", files=(_file(),))
    lock = Lockfile(version=1, fragments=(frag,))
    assert lock.version == 1
    assert lock.fragments[0].files[0].blob == "b" * 40


@pytest.mark.parametrize("bad", ["", "abc123", "a" * 39, "g" * 40, "A" * 40])
def test_locked_file_rejects_malformed_sha(bad: str) -> None:
    """Abbreviated, short, uppercase, or non-hex SHAs are rejected."""
    with pytest.raises(ValueError, match="hex SHA"):
        LockedFile(name="Python", path="Python.gitignore", commit=bad, blob="b" * 40)


def test_locked_file_accepts_sha256() -> None:
    """A 64-char SHA-256 object name is accepted."""
    locked = LockedFile(
        name="Python", path="Python.gitignore", commit="a" * 64, blob="b" * 64
    )
    assert locked.commit == "a" * 64


def test_locked_file_rejects_empty_name_and_path() -> None:
    """Empty name or path is rejected at construction."""
    with pytest.raises(ValueError, match="name"):
        LockedFile(name="", path="p", commit="a" * 40, blob="b" * 40)
    with pytest.raises(ValueError, match="path"):
        LockedFile(name="n", path="", commit="a" * 40, blob="b" * 40)


def test_fragment_rejects_empty_files() -> None:
    """A fragment with no input files renders nothing and is rejected."""
    with pytest.raises(ValueError, match="at least one file"):
        Fragment(path=".gitignore", source="gitignore", files=())


def test_fragment_rejects_empty_path_and_source() -> None:
    """Empty output path or source name is rejected at construction."""
    with pytest.raises(ValueError, match="path"):
        Fragment(path="", source="gitignore", files=(_file(),))
    with pytest.raises(ValueError, match="source"):
        Fragment(path=".gitignore", source="", files=(_file(),))


def test_lockfile_rejects_version_below_one() -> None:
    """A version below 1 is rejected."""
    with pytest.raises(ValueError, match="version"):
        Lockfile(version=0, fragments=())


@pytest.mark.parametrize("bad", ["/abs/Python.gitignore", "a\\b.gitignore"])
def test_locked_file_rejects_non_posix_path(bad: str) -> None:
    """Absolute or backslash paths are not repo-relative POSIX and are rejected."""
    with pytest.raises(ValueError, match="POSIX"):
        LockedFile(name="Python", path=bad, commit="a" * 40, blob="b" * 40)


def test_fragment_rejects_duplicate_file_paths() -> None:
    """Two files sharing a path within one fragment is rejected."""
    dupe = _file()
    with pytest.raises(ValueError, match="duplicate file paths"):
        Fragment(path=".gitignore", source="gitignore", files=(dupe, dupe))


def test_lockfile_rejects_duplicate_fragment_paths() -> None:
    """Two fragments sharing an output path (the primary key) is rejected."""
    frag = Fragment(path=".gitignore", source="gitignore", files=(_file(),))
    with pytest.raises(ValueError, match="duplicate fragment paths"):
        Lockfile(version=1, fragments=(frag, frag))


@pytest.mark.parametrize("bad", ["../escape", "a/../../etc", "/abs/path", "a\\b"])
def test_locked_file_rejects_unsafe_path(bad: str) -> None:
    """A traversal/absolute/backslash repo path is rejected at construction."""
    with pytest.raises(ValueError, match=r"LockedFile\.path"):
        LockedFile(name="Python", path=bad, commit="a" * 40, blob="b" * 40)


@pytest.mark.parametrize("bad", ["../out", "nested/../../x", "/abs", "a\\b"])
def test_fragment_rejects_unsafe_path(bad: str) -> None:
    """A traversal/absolute/backslash output path is rejected (it is a write target)."""
    with pytest.raises(ValueError, match=r"Fragment\.path"):
        Fragment(path=bad, source="gitignore", files=(_file(),))
