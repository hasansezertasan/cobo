"""Tests for managed-region markers (wrap / parse / classify / weave)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cobo.errors import ManagedBlockError
from cobo.sources import managed
from cobo.sources.managed import BlockState

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_CP = "#"


def test_wrap_round_trips_through_parse() -> None:
    """Wrap then parse recovers the body and reports an intact block."""
    text = managed.wrap("alpha\nbeta\n", _CP)
    parsed = managed.parse(text, _CP)
    assert parsed.body == "alpha\nbeta\n"
    assert not parsed.head
    assert not parsed.tail
    assert not parsed.tampered


def test_wrap_normalizes_trailing_newlines() -> None:
    """A body with extra/absent trailing newlines becomes exactly one."""
    assert managed.parse(managed.wrap("x", _CP), _CP).body == "x\n"
    assert managed.parse(managed.wrap("x\n\n\n", _CP), _CP).body == "x\n"


def test_parse_preserves_user_tail_and_head() -> None:
    """Content outside the markers is captured verbatim as head/tail."""
    text = "top\n" + managed.wrap("body\n", _CP) + "mine\nkeep\n"
    parsed = managed.parse(text, _CP)
    assert parsed.head == "top\n"
    assert parsed.tail == "mine\nkeep\n"
    assert parsed.body == "body\n"


def test_tampered_when_body_edited() -> None:
    """Editing the body without updating the end-marker hash reads as tampered."""
    text = managed.wrap("original\n", _CP).replace("original", "hacked")
    assert managed.parse(text, _CP).tampered


def test_parse_no_markers_raises() -> None:
    """A file with no markers is a ManagedBlockError (unmanaged)."""
    with pytest.raises(ManagedBlockError, match="no cobo"):
        managed.parse("just some content\n", _CP)


def test_parse_duplicate_begin_raises() -> None:
    """Two begin markers is malformed, not two blocks."""
    text = managed.wrap("a\n", _CP) + managed.wrap("b\n", _CP)
    with pytest.raises(ManagedBlockError, match="malformed"):
        managed.parse(text, _CP)


def test_parse_end_before_begin_raises() -> None:
    """An end marker preceding its begin is malformed."""
    one = managed.wrap("a\n", _CP).splitlines(keepends=True)
    scrambled = "".join([one[-1], one[0], one[1]])  # end, begin, body
    with pytest.raises(ManagedBlockError, match="malformed"):
        managed.parse(scrambled, _CP)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (managed.wrap("body\n", _CP), BlockState.MATCH),
        (managed.wrap("body\n", _CP).replace("body", "edited"), BlockState.MODIFIED),
        ("no markers here\n", BlockState.MISSING),
        (managed.wrap("a\n", _CP) + managed.wrap("b\n", _CP), BlockState.MALFORMED),
    ],
)
def test_classify(text: str, expected: BlockState) -> None:
    """Classify maps each on-disk shape to its BlockState."""
    assert managed.classify(text, _CP) == expected


def test_weave_fresh_when_absent() -> None:
    """A None existing file yields a plain wrapped block (no preserved content)."""
    out = managed.weave(None, "body\n", _CP, force=False)
    assert managed.parse(out, _CP).body == "body\n"
    assert not managed.parse(out, _CP).tail


def test_weave_preserves_tail_and_replaces_body() -> None:
    """Weave keeps the user tail and swaps in the new body."""
    existing = managed.wrap("old\n", _CP) + "user tail\n"
    out = managed.weave(existing, "new\n", _CP, force=False)
    parsed = managed.parse(out, _CP)
    assert parsed.body == "new\n"
    assert parsed.tail == "user tail\n"


def test_weave_refuses_tampered_block() -> None:
    """A hand-edited block is refused without force."""
    tampered = managed.wrap("orig\n", _CP).replace("orig", "hacked") + "tail\n"
    with pytest.raises(ManagedBlockError, match="edited locally"):
        managed.weave(tampered, "new\n", _CP, force=False)


def test_weave_force_overwrites_tampered_but_keeps_tail() -> None:
    """--force regenerates a tampered block while still preserving the tail."""
    tampered = managed.wrap("orig\n", _CP).replace("orig", "hacked") + "tail\n"
    out = managed.weave(tampered, "new\n", _CP, force=True)
    parsed = managed.parse(out, _CP)
    assert parsed.body == "new\n"
    assert parsed.tail == "tail\n"


def test_weave_refuses_missing_markers() -> None:
    """An unmanaged existing file is refused without force."""
    with pytest.raises(ManagedBlockError, match="no cobo"):
        managed.weave("hand-written\n", "new\n", _CP, force=False)


def test_weave_force_rebuilds_missing_markers() -> None:
    """--force overwrites an unmanaged file entirely, discarding its content."""
    out = managed.weave("hand-written\n", "new\n", _CP, force=True)
    assert managed.parse(out, _CP).body == "new\n"
    assert "hand-written" not in out


def test_markers_use_source_comment_prefix() -> None:
    """A non-'#' comment prefix appears in the markers and parses back."""
    text = managed.wrap("body\n", "//")
    assert text.startswith("// >>> cobo:begin >>>")
    assert managed.parse(text, "//").body == "body\n"


def test_block_with_carriage_return_matches_only_when_read_as_bytes(
    tmp_path: Path,
) -> None:
    r"""A block with an embedded '\r' round-trips as MATCH via a bytes read.

    Regression: the macOS gitignore uses ``Icon\r`` as a lone-CR character class.
    check/sync/dump must read managed files as bytes — reading via ``read_text``
    translates the ``\r`` and makes an intact block hash-mismatch as MODIFIED.
    """
    path = tmp_path / "f"
    path.write_bytes(managed.wrap("Icon[\r]\nkeep\n", _CP).encode("utf-8"))
    as_bytes = path.read_bytes().decode("utf-8")
    assert managed.classify(as_bytes, _CP) == BlockState.MATCH
    # The trap this guards against: a text-mode read reports a false positive.
    as_text = path.read_text(encoding="utf-8")
    assert managed.classify(as_text, _CP) == BlockState.MODIFIED
