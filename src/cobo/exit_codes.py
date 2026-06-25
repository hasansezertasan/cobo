"""The process exit-code contract shared across cobo CLI commands.

Centralizing the codes here keeps the documented contract (0 clean, 1 work
to do / failure, 2 unusable input) in one place, rather than re-deriving raw
``typer.Exit`` literals at each call site where a 1-vs-2 slip could creep in.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes returned by cobo commands.

    Attributes:
        OK: Success — nothing to do, or the operation completed cleanly.
        FAILURE: Updates are available, or an operation failed (e.g. a fragment
            could not be re-rendered, or a file could not be imported).
        USAGE: The input is unusable — no/malformed lockfile, an unsupported
            lockfile version, or a misused flag.
    """

    OK = 0
    FAILURE = 1
    USAGE = 2
