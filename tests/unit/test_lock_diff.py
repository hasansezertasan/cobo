"""Tests for the pure drift computation."""

import pytest

from cobo.lock.diff import compute_fragment_drift
from cobo.lock.schema import Fragment, LockedFile

pytestmark = pytest.mark.unit


def _frag() -> Fragment:
    return Fragment(
        path=".gitignore",
        source="gitignore",
        files=(
            LockedFile(name="Python", path="Python.gitignore", commit="c1", blob="p1"),
            LockedFile(name="Node", path="Node.gitignore", commit="c1", blob="n1"),
        ),
    )


def test_no_drift_when_blobs_match() -> None:
    """Matching current blobs produce no drift."""
    drifts = compute_fragment_drift(
        _frag(), {"Python.gitignore": "p1", "Node.gitignore": "n1"}
    )
    assert drifts == ()


def test_detects_single_changed_file() -> None:
    """Only the file whose blob changed is reported."""
    drifts = compute_fragment_drift(
        _frag(), {"Python.gitignore": "p1", "Node.gitignore": "n2"}
    )
    assert len(drifts) == 1
    assert drifts[0].name == "Node"
    assert drifts[0].old_blob == "n1"
    assert drifts[0].new_blob == "n2"


def test_missing_current_blob_is_drift_with_none() -> None:
    """A vanished file (None current blob) counts as drift."""
    drifts = compute_fragment_drift(
        _frag(), {"Python.gitignore": "p1", "Node.gitignore": None}
    )
    assert len(drifts) == 1
    assert drifts[0].new_blob is None
