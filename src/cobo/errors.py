"""Error hierarchy for cobo."""

from __future__ import annotations


class CoboError(Exception):
    """Base class for every error raised by cobo."""


class UserError(CoboError):
    """Raised for user-facing errors (bad arguments, missing boilerplate, etc.)."""


class GitError(CoboError):
    """Raised when a git clone or pull fails."""


class FileAbsentError(GitError):
    """Raised when a tracked path cannot be resolved at the clone's HEAD.

    A narrow subclass of :class:`GitError` so callers can distinguish a file
    that is genuinely gone upstream (legitimate drift) from a broken clone or
    transient git failure (an infrastructure error that should surface, not be
    silently treated as a deletion).
    """


class ConfigError(CoboError):
    """Raised when configuration is malformed or missing required fields."""
