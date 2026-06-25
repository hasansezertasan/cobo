"""Unit tests for pure helpers in cobo.commands.check."""

import pytest

from cobo.commands.check import is_excluded, selected_fragments
from cobo.lock.schema import Fragment, LockedFile, Lockfile

pytestmark = pytest.mark.unit


def _frag(path: str) -> Fragment:
    return Fragment(
        path=path,
        source="gi",
        files=(
            LockedFile(name="P", path="P.gitignore", commit="a" * 40, blob="b" * 40),
        ),
    )


@pytest.mark.parametrize(
    ("path", "patterns", "expected"),
    [
        (".gitignore", [], False),
        (".gitignore", [".gitignore"], True),
        (".github/dependabot.yml", [".github/*"], True),
        ("docs/.gitignore", [".gitignore"], False),  # fnmatch is not recursive
        ("LICENSE", ["*.md", "LICENSE"], True),
    ],
)
def test_is_excluded(path: str, patterns: list[str], *, expected: bool) -> None:
    """is_excluded matches a path against any glob pattern."""
    assert is_excluded(path, patterns) is expected


def test_selected_fragments_drops_matches_preserving_order() -> None:
    """selected_fragments keeps non-excluded fragments in lockfile order."""
    lock = Lockfile(
        version=1,
        fragments=(_frag(".gitignore"), _frag(".github/ci.yml"), _frag("LICENSE")),
    )
    kept = selected_fragments(lock, [".github/*"])
    assert [f.path for f in kept] == [".gitignore", "LICENSE"]
