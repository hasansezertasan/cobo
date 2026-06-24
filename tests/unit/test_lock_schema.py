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
