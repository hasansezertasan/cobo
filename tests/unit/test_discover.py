"""Tests for boilerplate discovery (pure: no git, no network)."""

from typing import TYPE_CHECKING

import pytest

from cobo.config.schema import Source
from cobo.errors import UserError
from cobo.sources.discover import (
    find_boilerplate,
    list_boilerplates,
    search_boilerplates,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def make_fake_repo(tmp_path: Path, files: list[str]) -> Path:
    """Create a tmp dir with the given filenames.

    Returns:
        The tmp_path directory with files written.
    """
    for fname in files:
        (tmp_path / fname).write_text("contents\n", encoding="utf-8")
    return tmp_path


def gitignore_source() -> Source:
    """Build a gitignore-flavored Source for fixtures.

    Returns:
        A Source configured for gitignore files.
    """
    return Source(
        name="gitignore",
        url="https://example.com",
        extension=".gitignore",
        multi_dump=True,
    )


def test_list_returns_sorted_names_sans_extension(tmp_path: Path) -> None:
    """Boilerplate names are listed sorted, without the extension suffix."""
    repo = make_fake_repo(
        tmp_path, ["Python.gitignore", "Go.gitignore", "Node.gitignore"]
    )
    names = list_boilerplates(gitignore_source(), repo)
    assert names == ["Go", "Node", "Python"]


def test_list_skips_files_not_matching_extension(tmp_path: Path) -> None:
    """Files without the configured extension are skipped."""
    repo = make_fake_repo(tmp_path, ["Python.gitignore", "README.md"])
    names = list_boilerplates(gitignore_source(), repo)
    assert names == ["Python"]


def test_search_is_case_insensitive_substring(tmp_path: Path) -> None:
    """Search matches a case-insensitive substring of the name."""
    repo = make_fake_repo(
        tmp_path, ["Python.gitignore", "Pycharm.gitignore", "Go.gitignore"]
    )
    matches = search_boilerplates(gitignore_source(), repo, "py")
    assert sorted(matches) == ["Pycharm", "Python"]


def test_find_returns_path_with_case_insensitive_match(tmp_path: Path) -> None:
    """find_boilerplate resolves names case-insensitively."""
    repo = make_fake_repo(tmp_path, ["Python.gitignore"])
    found = find_boilerplate(gitignore_source(), repo, "python")
    assert found.name == "Python.gitignore"


def test_find_raises_user_error_when_missing(tmp_path: Path) -> None:
    """A missing boilerplate name raises UserError."""
    repo = make_fake_repo(tmp_path, ["Python.gitignore"])
    with pytest.raises(UserError, match="Nope"):
        find_boilerplate(gitignore_source(), repo, "Nope")


def test_subpath_restricts_discovery(tmp_path: Path) -> None:
    """Setting subpath restricts list/search/find to that subdirectory."""
    sub = tmp_path / "templates"
    sub.mkdir()
    (sub / "Inner.gitignore").write_text("x\n", encoding="utf-8")
    (tmp_path / "Outer.gitignore").write_text("y\n", encoding="utf-8")
    source = Source(
        name="x",
        url="u",
        extension=".gitignore",
        subpath="templates",
    )
    assert list_boilerplates(source, tmp_path) == ["Inner"]


@pytest.mark.parametrize("bad_name", ["", "../etc/passwd", "foo/bar", "foo\\bar", "."])
def test_find_rejects_unsafe_names(tmp_path: Path, bad_name: str) -> None:
    """Names containing separators or traversal segments are rejected."""
    repo = make_fake_repo(tmp_path, ["Python.gitignore"])
    with pytest.raises(UserError):
        find_boilerplate(gitignore_source(), repo, bad_name)


def test_list_dedups_same_basename_across_subdirs(tmp_path: Path) -> None:
    """A basename appearing under multiple dirs only surfaces once."""
    (tmp_path / "community").mkdir()
    (tmp_path / "Python.gitignore").write_text("a\n", encoding="utf-8")
    (tmp_path / "community" / "Python.gitignore").write_text("b\n", encoding="utf-8")
    names = list_boilerplates(gitignore_source(), tmp_path)
    assert names == ["Python"]


def test_scan_root_rejects_escaping_subpath(tmp_path: Path) -> None:
    """Defense-in-depth: discovery refuses a subpath that escapes clone_root.

    Schema validation already rejects ``..`` at config-load time, but the
    discover layer also enforces containment so a bypass cannot read outside
    the cache.
    """
    clone_root = tmp_path / "clone"
    clone_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "Secret.gitignore").write_text("leak\n", encoding="utf-8")
    source = Source.__new__(Source)
    for attr, value in {
        "name": "x",
        "url": "https://example.com",
        "extension": ".gitignore",
        "description": "",
        "branch": "main",
        "multi_dump": False,
        "inject_header": False,
        "comment_prefix": "#",
        "subpath": "../outside",
    }.items():
        object.__setattr__(source, attr, value)  # noqa: PLC2801
    with pytest.raises(UserError, match="escapes clone root"):
        list_boilerplates(source, clone_root)


def test_find_prefers_shallowest_path_on_collision(tmp_path: Path) -> None:
    """When a name lives at multiple depths, the shallowest wins."""
    (tmp_path / "community").mkdir()
    shallow = tmp_path / "Python.gitignore"
    shallow.write_text("shallow\n", encoding="utf-8")
    (tmp_path / "community" / "Python.gitignore").write_text("deep\n", encoding="utf-8")
    found = find_boilerplate(gitignore_source(), tmp_path, "python")
    assert found == shallow
