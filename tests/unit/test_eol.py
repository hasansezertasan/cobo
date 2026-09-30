"""Tests for the line-ending normalization policy."""

from __future__ import annotations

import pytest

from cobo.eol import LF, PRESERVE, VALID, normalize_eol

pytestmark = pytest.mark.unit


def test_preserve_leaves_bytes_untouched() -> None:
    """``preserve`` returns the text verbatim, keeping CRLF and a lone CR."""
    body = "a\r\nIcon[\r]\nb\n"
    assert normalize_eol(body, PRESERVE) == body


def test_lf_collapses_crlf() -> None:
    """``lf`` turns every CRLF line terminator into LF."""
    body = "a\r\nb\r\nc\n"
    assert normalize_eol(body, LF) == "a\nb\nc\n"


def test_lf_keeps_cr_inside_a_char_class() -> None:
    r"""``lf`` keeps a lone CR that is a pattern byte (macOS ``Icon[\r]``).

    Regression for #124: collapsing it split ``Icon[\r]`` into ``Icon[`` and
    ``]``, so the macOS custom-icon file was no longer ignored.
    """
    body = "Icon[\r]\r\n.HFS+ Private Directory Data[\r]\n"
    assert normalize_eol(body, LF) == "Icon[\r]\n.HFS+ Private Directory Data[\r]\n"


def test_lf_keeps_lone_cr_at_end_of_text() -> None:
    """A trailing lone CR is not followed by LF, so ``lf`` leaves it alone."""
    assert normalize_eol("a\nIcon\r", LF) == "a\nIcon\r"


def test_lf_collapses_a_cr_run_before_lf() -> None:
    r"""Every CR directly before LF is part of the terminator.

    Dropping only one would leave ``\r\n`` behind for an LF consumer to rewrite.
    """
    assert normalize_eol("Icon\r\r\nb\n", LF) == "Icon\nb\n"


@pytest.mark.parametrize("body", ["a\r\nb", "Icon[\r]\r\n", "x\r\r\r\ny\r", "\r\n\r\n"])
def test_lf_is_idempotent_and_leaves_no_crlf(body: str) -> None:
    """Once normalized, a body has no CRLF and re-normalizing is a no-op."""
    once = normalize_eol(body, LF)
    assert "\r\n" not in once
    assert normalize_eol(once, LF) == once


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
