"""Error hierarchy for cobo."""

from __future__ import annotations


class CoboError(Exception):
    """Base class for every error raised by cobo."""


class UserError(CoboError):
    """Raised for user-facing errors (bad arguments, missing boilerplate, etc.)."""


class GitError(CoboError):
    """Raised when a git clone or pull fails."""


class ConfigError(CoboError):
    """Raised when configuration is malformed or missing required fields."""
