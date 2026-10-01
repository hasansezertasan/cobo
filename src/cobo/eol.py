r"""Line-ending policy for sealed managed blocks.

cobo normally seals a block's bytes verbatim, including any CRLF line endings
upstream ships. Consumers that enforce LF (git ``text eol=lf``) rewrite those
bytes, which then no longer match the sealed hash. Opting a dump into ``lf``
normalizes the block body *before* it is sealed and written, so the on-disk
bytes and the seal agree even after such a consumer processes the file.

``lf`` rewrites line terminators only (``\r\n`` -> ``\n``). Like git's
``text eol=lf`` and ``dos2unix``, it leaves a CR inside a line alone; unlike
them it drops a whole CR run before LF, not just one CR, so no CRLF survives.
A lone ``\r`` is content, not a line ending: in ``Icon[\r]`` it is a gitignore
char-class byte, and collapsing it to ``\n`` would split the pattern in two.
Tools that turn *every* CR into LF (Jinja, Prettier, editors applying
EditorConfig) will still rewrite such a byte, so a block that carries one must
not be rendered or reformatted by them.
"""

from __future__ import annotations

import re
from enum import StrEnum


class Eol(StrEnum):
    """The end-of-line policy a managed block was sealed with.

    A ``StrEnum`` so it doubles as the CLI ``--eol`` choice type and compares
    equal to the plain strings stored in ``cobo.lock``.
    """

    preserve = "preserve"
    lf = "lf"


# Plain-string aliases for the values stored in cobo.lock and passed around.
PRESERVE = Eol.preserve.value
LF = Eol.lf.value
VALID = frozenset(e.value for e in Eol)

# A line terminator: LF plus any CRs directly before it, or a CR run ending the
# text. Taking the whole run (not just one CR) keeps ``lf`` idempotent --
# ``\r\r\n`` must not leave a CRLF behind for an LF consumer to rewrite. A
# trailing CR counts because ``managed.wrap`` appends ``\n`` after the body,
# which would otherwise seal a CRLF. The ``(?<!\r)`` anchors each attempt at
# the start of a run; without it a long CR run not followed by LF is rescanned
# from every offset, which is quadratic.
_LINE_END = re.compile(r"(?<!\r)\r+(?:\n|\Z)")


def normalize_eol(text: str, eol: str) -> str:
    r"""Apply an end-of-line policy to ``text``.

    Args:
        text: The block body (provenance header + rendered templates).
        eol: ``"preserve"`` to leave bytes untouched, or ``"lf"`` to turn
            every CR run that ends a line (``\r\n``, ``\r\r\n``, or a
            trailing ``\r``) into ``\n``. A lone ``\r`` inside a line is kept
            (see module docstring).

    Returns:
        ``text`` unchanged for ``preserve``; the LF-normalized body for ``lf``.

    Raises:
        ValueError: When ``eol`` is not a recognized policy. Callers pass a
            validated value (a Typer-checked ``Eol`` or a ``Fragment``-validated
            string), so this fails loud on a programming error rather than
            silently shipping an un-normalized block.
    """
    if eol == Eol.lf:
        return _LINE_END.sub("\n", text)
    if eol == Eol.preserve:
        return text
    msg = f"unknown eol policy {eol!r}; expected one of {sorted(VALID)}"
    raise ValueError(msg)
