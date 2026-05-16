"""Tests for the error hierarchy."""

import pytest

from cobo.errors import CoboError, ConfigError, GitError, UserError

pytestmark = pytest.mark.unit


def test_user_error_is_cobo_error() -> None:
    """UserError inherits from CoboError so callers can catch the base class."""
    assert issubclass(UserError, CoboError)


def test_git_error_is_cobo_error() -> None:
    """GitError inherits from CoboError."""
    assert issubclass(GitError, CoboError)


def test_config_error_is_cobo_error() -> None:
    """ConfigError inherits from CoboError."""
    assert issubclass(ConfigError, CoboError)


def test_errors_carry_message() -> None:
    """Each error type preserves its message via the standard exception API."""
    err = UserError("missing name")
    with pytest.raises(UserError, match="missing name"):
        raise err
