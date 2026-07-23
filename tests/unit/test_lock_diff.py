"""Tests for the pure drift computation."""

import pytest

from cobo.lock.diff import FileDrift, compute_fragment_drift
from cobo.lock.schema import Fragment, LockedFile

pytestmark = pytest.mark.unit


_COMMIT = "c" * 40
_PY_BLOB = "a" * 40
_NODE_BLOB = "b" * 40
_NODE_BLOB_CHANGED = "d" * 40


def _frag() -> Fragment:
    return Fragment(
        path=".gitignore",
        source="gitignore",
        files=(
            LockedFile(
                name="Python", path="Python.gitignore", commit=_COMMIT, blob=_PY_BLOB
            ),
            LockedFile(
                name="Node", path="Node.gitignore", commit=_COMMIT, blob=_NODE_BLOB
            ),
        ),
    )


def test_no_drift_when_blobs_match() -> None:
    """Matching current blobs produce no drift."""
    drifts = compute_fragment_drift(
        _frag(), {"Python.gitignore": _PY_BLOB, "Node.gitignore": _NODE_BLOB}
    )
    assert drifts == ()


def test_detects_single_changed_file() -> None:
    """Only the file whose blob changed is reported."""
    drifts = compute_fragment_drift(
        _frag(), {"Python.gitignore": _PY_BLOB, "Node.gitignore": _NODE_BLOB_CHANGED}
    )
    assert len(drifts) == 1
    assert drifts[0].name == "Node"
    assert drifts[0].old_blob == _NODE_BLOB
    assert drifts[0].new_blob == _NODE_BLOB_CHANGED


def test_missing_current_blob_is_drift_with_none() -> None:
    """A vanished file (None current blob) counts as drift."""
    drifts = compute_fragment_drift(
        _frag(), {"Python.gitignore": _PY_BLOB, "Node.gitignore": None}
    )
    assert len(drifts) == 1
    assert drifts[0].new_blob is None


def test_file_drift_rejects_non_drift() -> None:
    """A FileDrift whose old and new blobs are equal is not drift and is rejected."""
    with pytest.raises(ValueError, match="old_blob != new_blob"):
        FileDrift(name="Python", path="p", old_blob=_PY_BLOB, new_blob=_PY_BLOB)
