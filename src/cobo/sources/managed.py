"""Managed-region markers that let user edits survive ``cobo sync``.

A tracked file is split into a cobo-owned block, delimited by begin/end marker
comments, and free user content outside it. ``sync`` regenerates only the block
and re-attaches the user's content verbatim. The end marker carries a SHA-256 of
the block body so a hand-edit inside the block is detectable (and refused)
rather than silently overwritten.

Layout (``<cp>`` is the source's comment prefix, e.g. ``#``)::

    <user head, usually empty>
    <cp> >>> cobo:begin >>>
    <provenance header + rendered templates>   <- the block body
    <cp> <<< cobo:end sha256=<64 hex> <<<
    <user tail, preserved verbatim>
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum

from cobo.errors import ManagedBlockError

_BEGIN_BODY = ">>> cobo:begin >>>"
_END_PREFIX = "<<< cobo:end sha256="
_END_SUFFIX = " <<<"


def block_hash(body: str) -> str:
    """Return the SHA-256 hex digest of a block body.

    Returns:
        The 64-char lowercase hex digest of ``body`` encoded as UTF-8.
    """
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _normalize(body: str) -> str:
    r"""Collapse a body's trailing newlines to exactly one.

    Returns:
        ``body`` with trailing newlines replaced by a single ``\\n`` so the end
        marker always sits on its own line directly below the content.
    """
    return body.rstrip("\n") + "\n"


def _begin_line(comment_prefix: str) -> str:
    return f"{comment_prefix} {_BEGIN_BODY}"


def _end_line(comment_prefix: str, digest: str) -> str:
    return f"{comment_prefix} {_END_PREFIX}{digest}{_END_SUFFIX}"


def _end_re(comment_prefix: str) -> re.Pattern[str]:
    return re.compile(
        rf"^{re.escape(comment_prefix)} {re.escape(_END_PREFIX)}"
        rf"(?P<hash>[0-9a-f]{{64}}){re.escape(_END_SUFFIX)}$"
    )


def wrap(body: str, comment_prefix: str) -> str:
    """Wrap a freshly rendered body in begin/end markers with a body hash.

    Args:
        body: The cobo-rendered content (provenance header + templates).
        comment_prefix: The source's comment prefix used to form comment markers.

    Returns:
        The block: begin marker, normalized body, end marker (carrying the
        body's SHA-256), each on its own line. No surrounding user content.
    """
    normalized = _normalize(body)
    begin = _begin_line(comment_prefix)
    end = _end_line(comment_prefix, block_hash(normalized))
    return f"{begin}\n{normalized}{end}\n"


@dataclass(frozen=True, slots=True)
class ManagedFile:
    """A tracked file parsed into its cobo block and surrounding user content.

    Attributes:
        head: User content before the begin marker (usually empty).
        body: The current block body between the markers.
        tail: User content after the end marker (preserved across syncs).
        recorded_hash: The SHA-256 recorded in the end marker.
    """

    head: str
    body: str
    tail: str
    recorded_hash: str

    @property
    def tampered(self) -> bool:
        """Whether the block body no longer matches its recorded hash.

        Returns:
            True when the body was hand-edited since cobo last wrote it.
        """
        return block_hash(self.body) != self.recorded_hash


class BlockState(Enum):
    """The on-disk state of a tracked file's managed block (for ``check``)."""

    MATCH = "match"
    MODIFIED = "modified"
    MISSING = "missing"
    MALFORMED = "malformed"
    ABSENT = "absent"


def _locate(
    text: str, comment_prefix: str
) -> tuple[list[str], list[int], list[tuple[int, str]]]:
    """Find the begin/end marker lines in ``text``.

    Returns:
        The kept-ends line list, the indices of begin markers, and the
        (index, recorded-hash) pairs of end markers.
    """
    begin = _begin_line(comment_prefix)
    end_re = _end_re(comment_prefix)
    lines = text.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.rstrip() == begin]
    ends: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        match = end_re.match(line.rstrip())
        if match is not None:
            ends.append((i, match["hash"]))
    return lines, begins, ends


def _is_well_formed(begins: list[int], ends: list[tuple[int, str]]) -> bool:
    """Whether exactly one begin precedes exactly one end.

    Returns:
        True for a single, correctly ordered begin/end pair.
    """
    return len(begins) == 1 and len(ends) == 1 and begins[0] < ends[0][0]


def parse(text: str, comment_prefix: str) -> ManagedFile:
    """Split ``text`` into head, block body, and tail around the markers.

    Args:
        text: The full text of a tracked file.
        comment_prefix: The source's comment prefix.

    Returns:
        The parsed ManagedFile.

    Raises:
        ManagedBlockError: When the file has no markers, or its markers are
            duplicated, missing a partner, or out of order.
    """
    lines, begins, ends = _locate(text, comment_prefix)
    if not begins and not ends:
        msg = "no cobo managed-block markers found"
        raise ManagedBlockError(msg)
    if not _is_well_formed(begins, ends):
        msg = "malformed cobo markers (expected exactly one begin before one end)"
        raise ManagedBlockError(msg)
    begin_idx = begins[0]
    end_idx, recorded_hash = ends[0]
    return ManagedFile(
        head="".join(lines[:begin_idx]),
        body="".join(lines[begin_idx + 1 : end_idx]),
        tail="".join(lines[end_idx + 1 :]),
        recorded_hash=recorded_hash,
    )


def classify(text: str, comment_prefix: str) -> BlockState:
    """Classify a tracked file's managed block without raising.

    Args:
        text: The full text of a tracked file.
        comment_prefix: The source's comment prefix.

    Returns:
        MATCH when the block is intact, MODIFIED when its body was edited,
        MISSING when no markers are present, or MALFORMED for broken markers.
    """
    lines, begins, ends = _locate(text, comment_prefix)
    if not begins and not ends:
        return BlockState.MISSING
    if not _is_well_formed(begins, ends):
        return BlockState.MALFORMED
    begin_idx = begins[0]
    end_idx, recorded_hash = ends[0]
    body = "".join(lines[begin_idx + 1 : end_idx])
    if block_hash(body) != recorded_hash:
        return BlockState.MODIFIED
    return BlockState.MATCH


def weave(
    existing: str | None, new_body: str, comment_prefix: str, *, force: bool
) -> str:
    """Produce the file text for a sync: fresh block plus preserved user content.

    Args:
        existing: Current file text, or None when the output file is absent.
        new_body: The freshly rendered cobo content to place in the block.
        comment_prefix: The source's comment prefix.
        force: When True, overwrite a hand-edited block, and rebuild from
            scratch (discarding all prior content) when markers are unusable.

    Returns:
        The full text to write: the user's head, the regenerated block, and the
        user's tail. A brand-new or force-rebuilt file has empty head and tail.

    Raises:
        ManagedBlockError: When ``existing`` has no/malformed markers, or its
            block was hand-edited, and ``force`` is False — so ``sync`` refuses
            rather than discarding user content.
    """
    if existing is None:
        return wrap(new_body, comment_prefix)
    try:
        parsed = parse(existing, comment_prefix)
    except ManagedBlockError:
        if force:
            return wrap(new_body, comment_prefix)
        raise
    if parsed.tampered and not force:
        msg = (
            "the cobo managed block was edited locally (hash mismatch); re-run "
            "with --force to overwrite it, or move your edits below the end marker"
        )
        raise ManagedBlockError(msg)
    return f"{parsed.head}{wrap(new_body, comment_prefix)}{parsed.tail}"
