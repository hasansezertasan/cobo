r"""Line-ending policy for sealed managed blocks.

cobo normally seals a block's bytes verbatim, preserving upstream oddities such
as the macOS ``github/gitignore`` ``Icon\\r`` line. Consumers that enforce LF
(copier's Jinja renderer, git ``text=auto eol=lf``, EditorConfig) rewrite those
bytes, which then no longer match the sealed hash. Opting a dump into ``lf``
normalizes the block body *before* it is sealed and written, so the on-disk
bytes and the seal agree even after such a consumer processes the file.
"""

from __future__ import annotations

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


def normalize_eol(text: str, eol: str) -> str:
    r"""Apply an end-of-line policy to ``text``.

    Args:
        text: The block body (provenance header + rendered templates).
        eol: ``"preserve"`` to leave bytes untouched, or ``"lf"`` to collapse
            every ``\r\n`` and lone ``\r`` to ``\n``.

    Returns:
        ``text`` unchanged for ``preserve``; the LF-normalized body for ``lf``.
    """
    if eol == Eol.lf:
        return text.replace("\r\n", "\n").replace("\r", "\n")
    return text
