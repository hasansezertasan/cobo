"""Tests for the line-ending normalization policy."""

from __future__ import annotations

import pytest

from cobo.eol import LF, PRESERVE, VALID, normalize_eol

pytestmark = pytest.mark.unit


def test_preserve_leaves_bytes_untouched() -> None:
    """``preserve`` returns the text verbatim, keeping a lone CR."""
    body = "a\r\nIcon\r\nb\n"
    assert normalize_eol(body, PRESERVE) == body


def test_lf_collapses_crlf_and_lone_cr() -> None:
    r"""``lf`` turns every CRLF and lone CR into LF (macOS ``Icon\\r`` case)."""
    body = "a\r\nIcon\rb\r\n"
    assert normalize_eol(body, LF) == "a\nIcon\nb\n"


def test_lf_is_idempotent_on_lf_only_text() -> None:
    """Normalizing already-LF text is a no-op."""
    body = "a\nb\nc\n"
    assert normalize_eol(body, LF) == body


def test_valid_values() -> None:
    """The recognized policy values are exactly preserve and lf."""
    assert {"preserve", "lf"} == VALID


def test_unknown_policy_raises() -> None:
    """An unrecognized policy fails loud rather than silently preserving."""
    with pytest.raises(ValueError, match="unknown eol policy"):
        normalize_eol("Icon\r\n", "crlf")
