# Fragment Update Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let cobo keep dumped boilerplates up to date — record each dump in a `cobo.lock`, detect when an origin's file content has changed, and (via a GitHub Action) open one grouped PR that re-renders the drifted fragments.

**Architecture:** A `cobo.lock` TOML file is the source of truth. Each output file is a `[[fragment]]` whose `[[fragment.files]]` record a resolved repo-relative path, the source `commit` (provenance for the header URL), and a `blob` SHA used as the content-addressed drift key (works on cobo's shallow `depth=1` clones). New pure modules (`lock/schema`, `lock/io`, `lock/diff`) hold data + logic; git I/O stays at the edges in `sources/repo`. Thin command orchestrators (`commands/check`, `commands/sync`, `commands/record`) wire them to the Typer CLI. A composite GitHub Action runs `cobo sync` and hands the diff to `peter-evans/create-pull-request`.

**Tech Stack:** Python 3.14, Typer 0.26, GitPython 3.1, Rich 15, stdlib `tomllib` (read) + hand-rolled TOML writer (write), pytest (markers: unit/integration/e2e/smoke), ruff (ALL), strict mypy/pyright/ty/pyrefly.

**Spec:** `docs/superpowers/specs/2026-06-23-fragment-updates-design.md` · **Issue:** [#48](https://github.com/hasansezertasan/cobo/issues/48)

**Conventions every file must follow** (verified against existing code):
- Start modules with `"""One-line docstring."""` then `from __future__ import annotations`.
- Google-style docstrings with `Returns:`/`Raises:` sections (enforced by ruff pydocstyle).
- Dataclasses are `@dataclass(frozen=True, slots=True)`; collections are `tuple[...]` (hashable, slots-friendly).
- Tests start with a module docstring and set `pytestmark = pytest.mark.<marker>`.
- Coverage gate is **95%** (`fail_under = 95`) — every branch needs a test.
- Run a single test: `uv run pytest <path>::<test> -p no:randomly -n0 -v`. Run a marker: `uv run pytest -m unit -n0 -q`.
- Lint/type gate before each commit: `uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright`.

---

## File Structure

**Create:**
- `src/cobo/lock/__init__.py` — package marker (empty).
- `src/cobo/lock/schema.py` — `LockedFile`, `Fragment`, `Lockfile` frozen dataclasses.
- `src/cobo/lock/io.py` — `LOCK_FILENAME`, `find_lock`, `read_lock`, `write_lock` (atomic), `upsert_fragment`, `empty_lock`.
- `src/cobo/lock/diff.py` — `FileDrift`, `compute_fragment_drift` (pure: no git, no FS).
- `src/cobo/commands/__init__.py` — package marker (empty).
- `src/cobo/commands/check.py` — `FragmentReport`, `CheckResult`, `run_check`, `gather_current_blobs`.
- `src/cobo/commands/sync.py` — `SyncResult`, `run_sync`.
- `src/cobo/commands/record.py` — `record_dump` (assemble + persist a Fragment for `dump --lock`).
- `action.yml` — composite GitHub Action.
- `docs/fragment-updates.md` — user-facing docs (lockfile format, commands, Action).
- Tests: `tests/unit/test_lock_schema.py`, `tests/unit/test_lock_io.py`, `tests/unit/test_lock_diff.py`, `tests/integration/test_blob_sha.py`, `tests/integration/test_check_sync.py`, `tests/e2e/test_check_cli.py`.

**Modify:**
- `src/cobo/sources/repo.py` — add `blob_sha_for_path`.
- `src/cobo/sources/render.py` — two-line header, full-SHA URL, repo-relative path.
- `src/cobo/source_commands.py` — `dump` gains `--lock` / `--out`.
- `src/cobo/globals.py` — register `check` and `sync` global commands.
- `tests/unit/test_render.py` — update to the new header format.
- `README.md` — add a "Keeping fragments up to date" section.

---

# Phase 1 — Lockfile + header revision

## Task 1: Lockfile dataclasses (`lock/schema.py`)

**Files:**
- Create: `src/cobo/lock/__init__.py`
- Create: `src/cobo/lock/schema.py`
- Test: `tests/unit/test_lock_schema.py`

- [ ] **Step 1: Create the package marker**

Create `src/cobo/lock/__init__.py` with exactly:

```python
"""Lockfile model, I/O, and drift logic for tracking dumped fragments."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_lock_schema.py`:

```python
"""Tests for the lockfile dataclasses."""

import pytest

from cobo.lock.schema import Fragment, Lockfile, LockedFile

pytestmark = pytest.mark.unit


def _file() -> LockedFile:
    return LockedFile(
        name="Python", path="Python.gitignore", commit="a" * 40, blob="b" * 40
    )


def test_locked_file_is_frozen() -> None:
    """LockedFile instances are immutable."""
    locked = _file()
    with pytest.raises((AttributeError, TypeError)):
        locked.name = "Other"  # type: ignore[misc]


def test_fragment_defaults_to_update_true() -> None:
    """A Fragment created without `update` defaults to True."""
    frag = Fragment(path=".gitignore", source="gitignore", files=(_file(),))
    assert frag.update is True


def test_fragment_can_be_pinned() -> None:
    """update=False marks a held-back fragment."""
    frag = Fragment(
        path="mise.toml", source="mise", files=(_file(),), update=False
    )
    assert frag.update is False


def test_lockfile_holds_version_and_fragments() -> None:
    """Lockfile carries a schema version and a tuple of fragments."""
    frag = Fragment(path=".gitignore", source="gitignore", files=(_file(),))
    lock = Lockfile(version=1, fragments=(frag,))
    assert lock.version == 1
    assert lock.fragments[0].files[0].blob == "b" * 40
```

- [ ] **Step 3: Run it; expect failure**

Run: `uv run pytest tests/unit/test_lock_schema.py -p no:randomly -n0 -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobo.lock.schema'`.

- [ ] **Step 4: Implement `lock/schema.py`**

```python
"""Frozen dataclasses describing the cobo.lock contents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LockedFile:
    """One input file that contributed to a dumped fragment.

    Attributes:
        name: The boilerplate name as dumped (e.g. "Python").
        path: Repo-relative POSIX path inside the source clone.
        commit: Full SHA the file was rendered from (provenance/header URL).
        blob: Blob SHA at that commit; the content-addressed drift key.
    """

    name: str
    path: str
    commit: str
    blob: str


@dataclass(frozen=True, slots=True)
class Fragment:
    """One output file produced by cobo, tracked for updates.

    Attributes:
        path: Output path, relative to the lockfile's directory.
        source: Name of the source the inputs came from.
        files: The input files concatenated into this output, in order.
        update: When False, check/sync skip this fragment (held back).
    """

    path: str
    source: str
    files: tuple[LockedFile, ...]
    update: bool = True


@dataclass(frozen=True, slots=True)
class Lockfile:
    """The whole cobo.lock document.

    Attributes:
        version: Lockfile schema version (currently 1).
        fragments: Tracked output files.
    """

    version: int
    fragments: tuple[Fragment, ...] = field(default_factory=tuple)
```

- [ ] **Step 5: Run it; expect pass**

Run: `uv run pytest tests/unit/test_lock_schema.py -p no:randomly -n0 -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/lock/__init__.py src/cobo/lock/schema.py tests/unit/test_lock_schema.py
git commit -m "feat(lock): add lockfile dataclasses (#48)"
```

---

## Task 2: Lockfile read/write (`lock/io.py`)

**Files:**
- Create: `src/cobo/lock/io.py`
- Test: `tests/unit/test_lock_io.py`

Reading uses stdlib `tomllib` (already used in `config/loader.py`). Writing is a small hand-rolled serializer (the project ships no TOML writer and prefers stdlib). Writes are atomic (temp file + `os.replace`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_lock_io.py`:

```python
"""Tests for reading and writing cobo.lock."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cobo.errors import ConfigError
from cobo.lock.io import (
    LOCK_FILENAME,
    empty_lock,
    find_lock,
    read_lock,
    upsert_fragment,
    write_lock,
)
from cobo.lock.schema import Fragment, Lockfile, LockedFile

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _frag(path: str = ".gitignore", *, update: bool = True) -> Fragment:
    return Fragment(
        path=path,
        source="gitignore",
        update=update,
        files=(
            LockedFile(
                name="Python", path="Python.gitignore", commit="a" * 40, blob="b" * 40
            ),
        ),
    )


def test_write_then_read_roundtrips(tmp_path: Path) -> None:
    """A written lockfile parses back to an equal Lockfile."""
    lock = Lockfile(version=1, fragments=(_frag(), _frag("mise.toml", update=False)))
    target = tmp_path / LOCK_FILENAME
    write_lock(target, lock)
    assert read_lock(target) == lock


def test_write_is_atomic_no_temp_left_behind(tmp_path: Path) -> None:
    """Writing leaves only cobo.lock (no stray temp files)."""
    target = tmp_path / LOCK_FILENAME
    write_lock(target, Lockfile(version=1, fragments=(_frag(),)))
    assert [p.name for p in tmp_path.iterdir()] == [LOCK_FILENAME]


def test_find_lock_walks_upward(tmp_path: Path) -> None:
    """find_lock locates cobo.lock in a parent directory."""
    (tmp_path / LOCK_FILENAME).write_text("version = 1\n", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_lock(nested) == tmp_path / LOCK_FILENAME


def test_find_lock_returns_none_when_absent(tmp_path: Path) -> None:
    """find_lock returns None when no lockfile exists above start."""
    assert find_lock(tmp_path) is None


def test_read_rejects_unknown_version(tmp_path: Path) -> None:
    """An unsupported version raises ConfigError, never silent acceptance."""
    target = tmp_path / LOCK_FILENAME
    target.write_text("version = 99\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        read_lock(target)


def test_read_rejects_malformed_toml(tmp_path: Path) -> None:
    """Malformed TOML raises ConfigError."""
    target = tmp_path / LOCK_FILENAME
    target.write_text("version = = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        read_lock(target)


def test_upsert_replaces_existing_path(tmp_path: Path) -> None:
    """upsert_fragment replaces a fragment with the same output path."""
    lock = empty_lock()
    lock = upsert_fragment(lock, _frag())
    replacement = Fragment(
        path=".gitignore",
        source="gitignore",
        files=(
            LockedFile(name="Node", path="Node.gitignore", commit="c" * 40, blob="d" * 40),
        ),
    )
    lock = upsert_fragment(lock, replacement)
    assert len(lock.fragments) == 1
    assert lock.fragments[0].files[0].name == "Node"


def test_upsert_appends_new_path() -> None:
    """upsert_fragment appends when the output path is new."""
    lock = upsert_fragment(empty_lock(), _frag())
    lock = upsert_fragment(lock, _frag("mise.toml"))
    assert {f.path for f in lock.fragments} == {".gitignore", "mise.toml"}


def test_string_values_are_escaped(tmp_path: Path) -> None:
    """Paths containing quotes/backslashes round-trip safely."""
    frag = Fragment(
        path='weird".gitignore',
        source="gitignore",
        files=(
            LockedFile(
                name="A\\B", path="dir/A.gitignore", commit="a" * 40, blob="b" * 40
            ),
        ),
    )
    target = tmp_path / LOCK_FILENAME
    write_lock(target, Lockfile(version=1, fragments=(frag,)))
    assert read_lock(target).fragments[0].path == 'weird".gitignore'
```

- [ ] **Step 2: Run it; expect failure**

Run: `uv run pytest tests/unit/test_lock_io.py -p no:randomly -n0 -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobo.lock.io'`.

- [ ] **Step 3: Implement `lock/io.py`**

```python
"""Read, write, locate, and update the cobo.lock file."""

from __future__ import annotations

import os
import tomllib
from typing import TYPE_CHECKING, Any

from cobo.errors import ConfigError
from cobo.lock.schema import Fragment, Lockfile, LockedFile

if TYPE_CHECKING:
    from pathlib import Path

LOCK_FILENAME = "cobo.lock"
_SUPPORTED_VERSION = 1


def empty_lock() -> Lockfile:
    """Return a fresh, empty lockfile at the current schema version.

    Returns:
        A Lockfile with version 1 and no fragments.
    """
    return Lockfile(version=_SUPPORTED_VERSION, fragments=())


def find_lock(start: Path) -> Path | None:
    """Search ``start`` and its ancestors for a cobo.lock file.

    Returns:
        The path to the nearest cobo.lock at or above ``start``, or None.
    """
    for directory in (start, *start.parents):
        candidate = directory / LOCK_FILENAME
        if candidate.is_file():
            return candidate
    return None


def read_lock(path: Path) -> Lockfile:
    """Parse a cobo.lock file into a Lockfile.

    Returns:
        The parsed Lockfile.

    Raises:
        ConfigError: When the TOML is malformed or the version unsupported.
    """
    try:
        with path.open("rb") as fh:
            data: dict[str, Any] = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        msg = f"Malformed lockfile {path}: {exc}"
        raise ConfigError(msg) from exc

    version = data.get("version")
    if version != _SUPPORTED_VERSION:
        msg = f"Unsupported lockfile version {version!r} in {path} (expected 1)"
        raise ConfigError(msg)

    fragments = tuple(_parse_fragment(raw, path) for raw in data.get("fragment", []))
    return Lockfile(version=_SUPPORTED_VERSION, fragments=fragments)


def _parse_fragment(raw: dict[str, Any], path: Path) -> Fragment:
    """Build a Fragment from a raw TOML table.

    Returns:
        The parsed Fragment.

    Raises:
        ConfigError: When a required key is missing.
    """
    try:
        files = tuple(
            LockedFile(
                name=f["name"], path=f["path"], commit=f["commit"], blob=f["blob"]
            )
            for f in raw["files"]
        )
        return Fragment(
            path=raw["path"],
            source=raw["source"],
            files=files,
            update=raw.get("update", True),
        )
    except KeyError as exc:
        msg = f"Lockfile {path}: fragment missing required key {exc}"
        raise ConfigError(msg) from exc


def upsert_fragment(lock: Lockfile, fragment: Fragment) -> Lockfile:
    """Return a new Lockfile with ``fragment`` added or replaced by output path.

    Returns:
        A new Lockfile; the matching fragment (same ``path``) is replaced,
        otherwise ``fragment`` is appended.
    """
    kept = tuple(f for f in lock.fragments if f.path != fragment.path)
    return Lockfile(version=lock.version, fragments=(*kept, fragment))


def write_lock(path: Path, lock: Lockfile) -> None:
    """Atomically serialize ``lock`` to ``path``.

    The document is written to a sibling temp file and renamed, so a crash
    mid-write never leaves a half-written cobo.lock.
    """
    text = _serialize(lock)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _serialize(lock: Lockfile) -> str:
    """Render a Lockfile as TOML text.

    Returns:
        TOML matching the format ``read_lock`` parses.
    """
    lines = [f"version = {lock.version}", ""]
    for frag in lock.fragments:
        lines.append("[[fragment]]")
        lines.append(f"path = {_q(frag.path)}")
        lines.append(f"source = {_q(frag.source)}")
        lines.append(f"update = {str(frag.update).lower()}")
        for file in frag.files:
            lines.append("")
            lines.append("  [[fragment.files]]")
            lines.append(f"  name = {_q(file.name)}")
            lines.append(f"  path = {_q(file.path)}")
            lines.append(f"  commit = {_q(file.commit)}")
            lines.append(f"  blob = {_q(file.blob)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _q(value: str) -> str:
    """Quote and escape a string as a TOML basic string.

    Returns:
        ``value`` wrapped in double quotes with backslash, quote, newline,
        and tab escaped.
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'
```

- [ ] **Step 4: Run it; expect pass**

Run: `uv run pytest tests/unit/test_lock_io.py -p no:randomly -n0 -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/lock/io.py tests/unit/test_lock_io.py
git commit -m "feat(lock): read/write/find cobo.lock with atomic writes (#48)"
```

---

## Task 3: Pure drift logic (`lock/diff.py`)

**Files:**
- Create: `src/cobo/lock/diff.py`
- Test: `tests/unit/test_lock_diff.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_lock_diff.py`:

```python
"""Tests for the pure drift computation."""

import pytest

from cobo.lock.diff import compute_fragment_drift
from cobo.lock.schema import Fragment, LockedFile

pytestmark = pytest.mark.unit


def _frag() -> Fragment:
    return Fragment(
        path=".gitignore",
        source="gitignore",
        files=(
            LockedFile(name="Python", path="Python.gitignore", commit="c1", blob="p1"),
            LockedFile(name="Node", path="Node.gitignore", commit="c1", blob="n1"),
        ),
    )


def test_no_drift_when_blobs_match() -> None:
    """Matching current blobs produce no drift."""
    drifts = compute_fragment_drift(
        _frag(), {"Python.gitignore": "p1", "Node.gitignore": "n1"}
    )
    assert drifts == ()


def test_detects_single_changed_file() -> None:
    """Only the file whose blob changed is reported."""
    drifts = compute_fragment_drift(
        _frag(), {"Python.gitignore": "p1", "Node.gitignore": "n2"}
    )
    assert len(drifts) == 1
    assert drifts[0].name == "Node"
    assert drifts[0].old_blob == "n1"
    assert drifts[0].new_blob == "n2"


def test_missing_current_blob_is_drift_with_none() -> None:
    """A vanished file (None current blob) counts as drift."""
    drifts = compute_fragment_drift(
        _frag(), {"Python.gitignore": "p1", "Node.gitignore": None}
    )
    assert len(drifts) == 1
    assert drifts[0].new_blob is None
```

- [ ] **Step 2: Run it; expect failure**

Run: `uv run pytest tests/unit/test_lock_diff.py -p no:randomly -n0 -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobo.lock.diff'`.

- [ ] **Step 3: Implement `lock/diff.py`**

```python
"""Pure drift computation: stored blobs vs current blobs. No git, no FS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from cobo.lock.schema import Fragment


@dataclass(frozen=True, slots=True)
class FileDrift:
    """A single input file whose content moved since it was locked.

    Attributes:
        name: The boilerplate name.
        path: Repo-relative path of the file.
        old_blob: Blob SHA recorded in the lock.
        new_blob: Current blob SHA, or None when the file is gone/unresolved.
    """

    name: str
    path: str
    old_blob: str
    new_blob: str | None


def compute_fragment_drift(
    fragment: Fragment, current_blobs: Mapping[str, str | None]
) -> tuple[FileDrift, ...]:
    """Compare a fragment's locked blobs against current blobs.

    Args:
        fragment: The locked fragment.
        current_blobs: Map of repo-relative path -> current blob SHA (or None
            when the file could not be resolved in the refreshed clone).

    Returns:
        One FileDrift per file whose current blob differs from the locked blob.
    """
    drifts: list[FileDrift] = []
    for file in fragment.files:
        current = current_blobs.get(file.path)
        if current != file.blob:
            drifts.append(
                FileDrift(
                    name=file.name,
                    path=file.path,
                    old_blob=file.blob,
                    new_blob=current,
                )
            )
    return tuple(drifts)
```

- [ ] **Step 4: Run it; expect pass**

Run: `uv run pytest tests/unit/test_lock_diff.py -p no:randomly -n0 -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/lock/diff.py tests/unit/test_lock_diff.py
git commit -m "feat(lock): pure blob-based drift computation (#48)"
```

---

## Task 4: Blob lookup on the clone (`sources/repo.py`)

**Files:**
- Modify: `src/cobo/sources/repo.py`
- Test: `tests/integration/test_blob_sha.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_blob_sha.py`:

```python
"""Tests for blob_sha_for_path against a real local clone."""

from __future__ import annotations

import subprocess  # noqa: S404
from typing import TYPE_CHECKING

import pytest

from cobo.config.schema import Source
from cobo.errors import GitError
from cobo.sources.repo import blob_sha_for_path, clone_or_pull

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],  # noqa: S607
        check=True,
    )


def _make_bare_repo(tmp_path: Path) -> Path:
    upstream = tmp_path / "upstream.git"
    seed = tmp_path / "seed"
    (seed / "Global").mkdir(parents=True)
    (seed / "Python.gitignore").write_text("*.pyc\n", encoding="utf-8")
    (seed / "Global" / "macOS.gitignore").write_text("Icon\r\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)  # noqa: S603, S607
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "seed")
    subprocess.run(  # noqa: S603
        ["git", "init", "-q", "--bare", "-b", "main", str(upstream)],  # noqa: S607
        check=True,
    )
    _git(seed, "remote", "add", "origin", str(upstream))
    _git(seed, "push", "-q", "origin", "main")
    return upstream


def test_blob_sha_matches_git_rev_parse(tmp_path: Path) -> None:
    """blob_sha_for_path equals `git rev-parse HEAD:<path>`."""
    upstream = _make_bare_repo(tmp_path)
    clone = tmp_path / "clone"
    clone_or_pull(
        Source(name="x", url=str(upstream), extension=".gitignore", branch="main"),
        clone,
    )
    got = blob_sha_for_path(clone, "Python.gitignore")
    expected = subprocess.run(  # noqa: S603
        ["git", "-C", str(clone), "rev-parse", "HEAD:Python.gitignore"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert got == expected


def test_blob_sha_resolves_nested_path(tmp_path: Path) -> None:
    """Nested paths (the old URL-bug case) resolve correctly."""
    upstream = _make_bare_repo(tmp_path)
    clone = tmp_path / "clone"
    clone_or_pull(
        Source(name="x", url=str(upstream), extension=".gitignore", branch="main"),
        clone,
    )
    assert blob_sha_for_path(clone, "Global/macOS.gitignore")


def test_blob_sha_missing_path_raises_git_error(tmp_path: Path) -> None:
    """A path absent from HEAD raises GitError."""
    upstream = _make_bare_repo(tmp_path)
    clone = tmp_path / "clone"
    clone_or_pull(
        Source(name="x", url=str(upstream), extension=".gitignore", branch="main"),
        clone,
    )
    with pytest.raises(GitError):
        blob_sha_for_path(clone, "Nope.gitignore")
```

- [ ] **Step 2: Run it; expect failure**

Run: `uv run pytest tests/integration/test_blob_sha.py -p no:randomly -n0 -v`
Expected: FAIL — `ImportError: cannot import name 'blob_sha_for_path'`.

- [ ] **Step 3: Implement — append to `src/cobo/sources/repo.py`**

Add this function at the end of the file (the `GitCommandError`, `InvalidGitRepositoryError`, `NoSuchPathError`, `Repo`, and `GitError` imports already exist at the top):

```python
def blob_sha_for_path(clone_root: Path, repo_path: str) -> str:
    """Return the blob SHA of ``repo_path`` at the clone's HEAD.

    Uses ``git rev-parse HEAD:<path>``, which works on a shallow (depth-1)
    clone and is content-addressed: the SHA changes iff the file content
    changes. This is the drift key for fragment updates.

    Args:
        clone_root: Path to an existing source clone.
        repo_path: Repo-relative POSIX path of the file at HEAD.

    Returns:
        The 40-character blob SHA.

    Raises:
        GitError: When the clone is invalid or the path is absent at HEAD.
    """
    try:
        repo = Repo(clone_root)
        return repo.git.rev_parse(f"HEAD:{repo_path}")
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError) as exc:
        msg = f"could not resolve blob for '{repo_path}' in {clone_root}: {exc}"
        raise GitError(msg) from exc
```

- [ ] **Step 4: Run it; expect pass**

Run: `uv run pytest tests/integration/test_blob_sha.py -p no:randomly -n0 -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/sources/repo.py tests/integration/test_blob_sha.py
git commit -m "feat(repo): add blob_sha_for_path for drift detection (#48)"
```

---

## Task 5: Revise the provenance header (`sources/render.py`)

**Files:**
- Modify: `src/cobo/sources/render.py`
- Test: `tests/unit/test_render.py` (replace header-specific tests)

The new header is two lines; the URL uses the **full** SHA and the **repo-relative path** (fixing the nested-dir 404 and abbreviated-SHA fragility). `build_header`'s second parameter changes from `boilerplate_filename` to `repo_rel_path`.

- [ ] **Step 1: Replace the body of `src/cobo/sources/render.py`**

```python
"""Render boilerplates for stdout: dump and provenance header."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cobo.sources.discover import find_boilerplate

if TYPE_CHECKING:
    from pathlib import Path

    from cobo.config.schema import Source

_SHORT_SHA_LEN = 7
_COBO_HOST = "github.com/hasansezertasan/cobo"


def dump(source: Source, clone_root: Path, names: list[str], commit_sha: str) -> str:
    """Render one or more boilerplates from a source to a single string.

    Args:
        source: Resolved source.
        clone_root: Path to the source's clone on disk.
        names: One or more boilerplate names to render.
        commit_sha: Full SHA of the clone's HEAD (used in headers).

    Returns:
        Concatenated content with optional headers. A single blank line
        separates chunks; no trailing blank line is appended after the last.
    """
    chunks: list[str] = []
    for name in names:
        path = find_boilerplate(source, clone_root, name)
        repo_rel = path.relative_to(clone_root).as_posix()
        chunks.append(_render_one(source, path, repo_rel, commit_sha))
    if len(chunks) == 1:
        return chunks[0]
    stripped = [c.rstrip("\n") for c in chunks]
    return "\n\n".join(stripped) + "\n"


def _render_one(
    source: Source, path: Path, repo_rel_path: str, commit_sha: str
) -> str:
    """Render a single boilerplate file (optionally with header).

    Returns:
        File content, optionally prefixed with a provenance header.
    """
    # Decode bytes directly rather than ``read_text`` to avoid universal-newline
    # translation, which would collapse embedded ``\r`` bytes (e.g. the macOS
    # gitignore ``Icon[\r]`` character-class trick) to ``\n`` and corrupt them.
    content = path.read_bytes().decode("utf-8")
    if not source.inject_header:
        return content
    header = build_header(
        source=source, repo_rel_path=repo_rel_path, commit_sha=commit_sha
    )
    return f"{header}\n{content}"


def build_header(source: Source, repo_rel_path: str, commit_sha: str) -> str:
    """Construct the two-line provenance header for a boilerplate.

    Line one is a fixed attribution. Line two is ``source/name@short`` followed
    by the raw URL, built from the FULL SHA and the resolved repo-relative path
    so it never 404s on nested files or abbreviated-SHA ambiguity. The URL is
    omitted for non-GitHub sources.

    Returns:
        A two-line (or, for non-GitHub sources, attribution + token) header.
    """
    short = commit_sha[:_SHORT_SHA_LEN]
    name = _stem(repo_rel_path, source.extension)
    raw_url = _raw_url(source.url, commit_sha, repo_rel_path)
    cp = source.comment_prefix
    attribution = f"{cp} Generated by cobo ({_COBO_HOST})"
    token = f"{source.name}/{name}@{short}"
    provenance = f"{cp} {token} — {raw_url}" if raw_url is not None else f"{cp} {token}"
    return f"{attribution}\n{provenance}"


def _stem(repo_rel_path: str, extension: str) -> str:
    """Return the boilerplate name (basename minus extension).

    Returns:
        The final path segment with ``extension`` removed when present.
    """
    basename = repo_rel_path.rsplit("/", 1)[-1]
    if extension and basename.endswith(extension):
        return basename[: -len(extension)]
    return basename


_GITHUB_HTTPS_PREFIX = "https://github.com/"
_GITHUB_SSH_PREFIX = "git@github.com:"


def _raw_url(url: str, sha: str, repo_rel_path: str) -> str | None:
    """Build a raw.githubusercontent URL for a file at a given SHA.

    Recognizes both HTTPS (``https://github.com/owner/repo``) and SSH
    (``git@github.com:owner/repo.git``) forms. The full SHA and the resolved
    repo-relative path are used verbatim.

    Returns:
        Raw GitHub URL, or None when the source URL is not a GitHub URL.
    """
    repo_path = _github_repo_path(url)
    if repo_path is None:
        return None
    return f"https://raw.githubusercontent.com/{repo_path}/{sha}/{repo_rel_path}"


def _github_repo_path(url: str) -> str | None:
    """Extract ``owner/repo`` from a GitHub HTTPS or SSH URL.

    Returns:
        ``owner/repo`` with any ``.git`` suffix stripped, or None when ``url``
        is not a recognized GitHub URL.
    """
    if url.startswith(_GITHUB_HTTPS_PREFIX):
        body = url[len(_GITHUB_HTTPS_PREFIX) :]
    elif url.startswith(_GITHUB_SSH_PREFIX):
        body = url[len(_GITHUB_SSH_PREFIX) :]
    else:
        return None
    return body.removesuffix(".git").rstrip("/")
```

Note: `__version__` is no longer used here — its import is removed. If ruff `RUF001` flags the `—` em dash, replace the two `—` occurrences with ` - ` (hyphen) and update the assertions in Step 2 to match.

- [ ] **Step 2: Replace the header tests in `tests/unit/test_render.py`**

Delete the existing tests named `test_raw_url_for_ssh_form_github_url`, `test_dump_with_header_prepends_provenance_lines`, `test_build_header_uses_short_sha_and_raw_url`, `test_header_strips_git_suffix_from_url`, and `test_header_omits_url_for_non_github_source`. Replace them with:

```python
def test_build_header_is_two_lines_with_full_sha_url() -> None:
    """Header: attribution line + `source/name@short — full-SHA url`."""
    header = build_header(
        source=mise_source(),
        repo_rel_path="python.mise.toml",
        commit_sha="0123456789abcdef0123456789abcdef01234567",
    )
    lines = header.splitlines()
    assert len(lines) == 2
    assert lines[0] == "# Generated by cobo (github.com/hasansezertasan/cobo)"
    assert lines[1].startswith("# mise/python@0123456 — ")
    assert lines[1].endswith(
        "raw.githubusercontent.com/hasansezertasan/mise-cookbooks/"
        "0123456789abcdef0123456789abcdef01234567/python.mise.toml"
    )


def test_header_uses_full_sha_not_short_in_url() -> None:
    """The URL embeds the full 40-char SHA, not the 7-char token."""
    full = "a" * 40
    header = build_header(
        source=mise_source(), repo_rel_path="python.mise.toml", commit_sha=full
    )
    assert f"/{full}/" in header


def test_header_url_preserves_nested_path() -> None:
    """A nested repo path is preserved in the URL (the old 404 bug)."""
    source = Source(
        name="gitignore",
        url="https://github.com/github/gitignore",
        extension=".gitignore",
        inject_header=True,
    )
    header = build_header(
        source=source, repo_rel_path="Global/macOS.gitignore", commit_sha="b" * 40
    )
    assert header.endswith("/Global/macOS.gitignore")
    assert "gitignore/macOS@" in header  # name is the stem, not the dir


def test_header_handles_ssh_url_form() -> None:
    """SSH-form GitHub URLs still build a raw URL."""
    source = Source(
        name="mise",
        url="git@github.com:hasansezertasan/mise-cookbooks.git",
        extension=".mise.toml",
        inject_header=True,
    )
    header = build_header(
        source=source, repo_rel_path="python.mise.toml", commit_sha="c" * 40
    )
    assert "raw.githubusercontent.com/hasansezertasan/mise-cookbooks" in header
    assert ".git/" not in header


def test_header_omits_url_for_non_github_source() -> None:
    """Non-GitHub sources get only the attribution + token (no URL, no dash)."""
    source = Source(
        name="custom",
        url="https://gitlab.example.com/team/templates",
        extension=".tpl",
        inject_header=True,
    )
    header = build_header(
        source=source, repo_rel_path="x.tpl", commit_sha="d" * 40
    )
    assert "gitlab.example.com" not in header
    assert "—" not in header
    assert header.splitlines()[1] == "# custom/x@dddddddd"[: len("# custom/x@") + 7]
```

The unchanged `dump`-content tests (`test_single_dump_no_header_emits_raw_content`, the multi-dump ones, and `test_dump_preserves_embedded_carriage_returns`) still pass because `dump`'s signature is unchanged.

- [ ] **Step 3: Run the render tests; expect pass**

Run: `uv run pytest tests/unit/test_render.py -p no:randomly -n0 -v`
Expected: PASS. If the em-dash assertions fail due to a ruff/encoding fix, apply the hyphen fallback noted in Step 1 and re-run.

- [ ] **Step 4: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/sources/render.py tests/unit/test_render.py
git commit -m "feat(render): two-line header with full-SHA, path-correct URL (#48)"
```

---

## Task 6: `dump --lock --out` records fragments (`commands/record.py`, `source_commands.py`)

**Files:**
- Create: `src/cobo/commands/__init__.py`
- Create: `src/cobo/commands/record.py`
- Modify: `src/cobo/source_commands.py`
- Test: `tests/integration/test_check_sync.py` (record portion)

- [ ] **Step 1: Create the package marker**

Create `src/cobo/commands/__init__.py`:

```python
"""Command orchestrators wiring lock/sources logic to the Typer CLI."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_check_sync.py` with the shared helpers and the first test (later tasks append to this file):

```python
"""Integration tests for record/check/sync against local clones."""

from __future__ import annotations

import subprocess  # noqa: S404
from typing import TYPE_CHECKING

import pytest

from cobo.commands.record import record_dump
from cobo.config.schema import Source
from cobo.lock.io import read_lock
from cobo.sources.repo import clone_or_pull, current_commit_sha

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],  # noqa: S607
        check=True,
    )


def make_source(tmp_path: Path, files: dict[str, str]) -> tuple[Source, Path]:
    """Create a bare upstream repo and return (Source, clone_path).

    Returns:
        A Source pointing at the bare repo and the path to clone into.
    """
    upstream = tmp_path / "upstream.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    for name, content in files.items():
        target = seed / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)  # noqa: S603, S607
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "seed")
    subprocess.run(  # noqa: S603
        ["git", "init", "-q", "--bare", "-b", "main", str(upstream)],  # noqa: S607
        check=True,
    )
    _git(seed, "remote", "add", "origin", str(upstream))
    _git(seed, "push", "-q", "origin", "main")
    source = Source(
        name="gi", url=str(upstream), extension=".gitignore", branch="main",
        multi_dump=True,
    )
    return source, tmp_path / "clone"


def advance_source(tmp_path: Path, name: str, content: str) -> None:
    """Commit a new version of ``name`` to the upstream and push."""
    seed = tmp_path / "seed"
    (seed / name).write_text(content, encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "update")
    _git(seed, "push", "-q", "origin", "main")


def test_record_dump_writes_lock_entry(tmp_path: Path) -> None:
    """record_dump persists a fragment with per-file path/commit/blob."""
    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    out = tmp_path / ".gitignore"
    lock_path = tmp_path / "cobo.lock"
    record_dump(
        source=source,
        clone_root=clone,
        names=["Python"],
        out_path=out,
        lock_path=lock_path,
        commit_sha=current_commit_sha(clone),
    )
    lock = read_lock(lock_path)
    assert len(lock.fragments) == 1
    frag = lock.fragments[0]
    assert frag.path == ".gitignore"
    assert frag.source == "gi"
    assert frag.files[0].name == "Python"
    assert frag.files[0].path == "Python.gitignore"
    assert len(frag.files[0].blob) == 40
```

- [ ] **Step 3: Run it; expect failure**

Run: `uv run pytest tests/integration/test_check_sync.py -p no:randomly -n0 -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobo.commands.record'`.

- [ ] **Step 4: Implement `src/cobo/commands/record.py`**

```python
"""Assemble and persist a lockfile fragment for `dump --lock`."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from cobo.lock.io import find_lock, read_lock, upsert_fragment, write_lock
from cobo.lock.schema import Fragment, LockedFile
from cobo.sources.discover import find_boilerplate
from cobo.sources.repo import blob_sha_for_path

if TYPE_CHECKING:
    from pathlib import Path

    from cobo.config.schema import Source


def record_dump(
    *,
    source: Source,
    clone_root: Path,
    names: list[str],
    out_path: Path,
    lock_path: Path,
    commit_sha: str,
) -> None:
    """Upsert a fragment for a just-written dump into the lockfile.

    The fragment's output ``path`` is stored relative to the lockfile's
    directory so the lock is portable across checkouts.

    Args:
        source: The source dumped from.
        clone_root: The source clone the files were rendered from.
        names: Boilerplate names included in the output, in order.
        out_path: The file the dump was written to.
        lock_path: Where the lockfile lives (created if absent).
        commit_sha: Full HEAD SHA of the clone at render time.
    """
    files: list[LockedFile] = []
    for name in names:
        path = find_boilerplate(source, clone_root, name)
        repo_rel = path.relative_to(clone_root).as_posix()
        files.append(
            LockedFile(
                name=name,
                path=repo_rel,
                commit=commit_sha,
                blob=blob_sha_for_path(clone_root, repo_rel),
            )
        )
    rel_out = os.path.relpath(out_path.resolve(), lock_path.parent.resolve())
    fragment = Fragment(
        path=rel_out.replace(os.sep, "/"),
        source=source.name,
        files=tuple(files),
    )
    existing = read_lock(lock_path) if lock_path.exists() else None
    base = existing if existing is not None else _empty()
    write_lock(lock_path, upsert_fragment(base, fragment))


def _empty() -> object:
    """Return a fresh empty lockfile.

    Returns:
        An empty Lockfile (imported lazily to keep this module thin).
    """
    from cobo.lock.io import empty_lock

    return empty_lock()


def resolve_lock_path(start: Path) -> Path:
    """Return the lockfile path to write: an existing one upward, else here.

    Returns:
        The nearest existing cobo.lock above ``start``, or ``start/cobo.lock``.
    """
    from cobo.lock.io import LOCK_FILENAME

    found = find_lock(start)
    return found if found is not None else start / LOCK_FILENAME
```

Note: `_empty` returns `object` to avoid a forward type issue; replace its annotation with `-> Lockfile` and add `from cobo.lock.schema import Lockfile` under `TYPE_CHECKING` plus a top-level `from cobo.lock.io import empty_lock` if the strict type-checkers prefer it. Simplest strict-clean version: import `empty_lock` and `LOCK_FILENAME` at the top and inline them (drop the two helper functions). Do whichever the type-checkers accept; the test only exercises `record_dump`.

- [ ] **Step 5: Wire `--lock` / `--out` into the dump command**

In `src/cobo/source_commands.py`, replace the entire `_register_dump` function with:

```python
def _register_dump(
    sub: typer.Typer,
    source: Source,
    clone_root_provider: CloneRootProvider,
) -> None:
    @sub.command("dump")
    def dump_cmd(
        names: list[str] = typer.Argument(..., help="Boilerplate name(s) to dump."),  # noqa: B008
        out: Path | None = typer.Option(  # noqa: B008
            None, "--out", help="Write output to this file instead of stdout."
        ),
        lock: bool = typer.Option(
            False, "--lock", help="Record this dump in cobo.lock (requires --out)."
        ),
    ) -> None:
        """Dump boilerplate(s) to stdout or a file, optionally recording in the lock.

        Raises:
            Exit: Code 1 if a name is not found or multi-dump is rejected;
                code 2 if --lock is used without --out.
        """
        target = clone_root_provider(source)
        if not target.exists():
            _missing(source)
        _enforce_multi_dump(source, names)
        if lock and out is None:
            typer.echo("--lock requires --out (a file path to track).", err=True)
            raise typer.Exit(2)
        commit_sha = current_commit_sha(target)
        try:
            content = render_dump(source, target, names, commit_sha)
        except UserError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        if out is None:
            typer.echo(content, nl=False)
            return
        out.write_bytes(content.encode("utf-8"))
        if lock:
            record_dump(
                source=source,
                clone_root=target,
                names=names,
                out_path=out,
                lock_path=resolve_lock_path(Path.cwd()),
                commit_sha=commit_sha,
            )
```

Add the imports near the top of `source_commands.py` (it already imports `Path`, `current_commit_sha`, `render_dump as render_dump`... verify `render_dump` is imported as `render_dump`):

```python
from cobo.commands.record import record_dump, resolve_lock_path
```

- [ ] **Step 6: Run the record test; expect pass**

Run: `uv run pytest tests/integration/test_check_sync.py::test_record_dump_writes_lock_entry -p no:randomly -n0 -v`
Expected: PASS.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/commands/__init__.py src/cobo/commands/record.py src/cobo/source_commands.py tests/integration/test_check_sync.py
git commit -m "feat(dump): --lock/--out records fragments in cobo.lock (#48)"
```

---

# Phase 2 — check / sync commands

## Task 7: Drift report core (`commands/check.py`)

**Files:**
- Create: `src/cobo/commands/check.py`
- Test: append to `tests/integration/test_check_sync.py`

- [ ] **Step 1: Append the failing test**

Add to `tests/integration/test_check_sync.py`:

```python
def _provider_factory(clone: Path):
    def provider(_source: Source) -> Path:
        return clone

    return provider


def _record(tmp_path: Path, source: Source, clone: Path, names: list[str]) -> Path:
    out = tmp_path / ".gitignore"
    lock_path = tmp_path / "cobo.lock"
    record_dump(
        source=source,
        clone_root=clone,
        names=names,
        out_path=out,
        lock_path=lock_path,
        commit_sha=current_commit_sha(clone),
    )
    return lock_path


def test_check_reports_no_drift_when_unchanged(tmp_path: Path) -> None:
    """A freshly recorded fragment shows no drift."""
    from cobo.commands.check import run_check

    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    result = run_check(
        read_lock(lock_path), {source.name: source}, _provider_factory(clone)
    )
    assert result.outdated_count == 0


def test_check_detects_drift_after_upstream_change(tmp_path: Path) -> None:
    """Advancing the upstream file makes the fragment outdated."""
    from cobo.commands.check import run_check

    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    result = run_check(
        read_lock(lock_path), {source.name: source}, _provider_factory(clone)
    )
    assert result.outdated_count == 1


def test_check_skips_held_fragment(tmp_path: Path) -> None:
    """update=False fragments are reported as held, never outdated."""
    from cobo.commands.check import run_check
    from cobo.lock.io import write_lock
    from cobo.lock.schema import Lockfile
    from dataclasses import replace

    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    lock = read_lock(lock_path)
    held = replace(lock.fragments[0], update=False)
    write_lock(lock_path, Lockfile(version=1, fragments=(held,)))
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    result = run_check(
        read_lock(lock_path), {source.name: source}, _provider_factory(clone)
    )
    assert result.outdated_count == 0
    assert result.reports[0].held is True
```

- [ ] **Step 2: Run; expect failure**

Run: `uv run pytest tests/integration/test_check_sync.py -k check -p no:randomly -n0 -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobo.commands.check'`.

- [ ] **Step 3: Implement `src/cobo/commands/check.py`**

```python
"""Drift detection across all tracked fragments (the `cobo check` core)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cobo.errors import GitError
from cobo.lock.diff import compute_fragment_drift
from cobo.sources.repo import blob_sha_for_path, clone_or_pull

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from cobo.config.schema import Source
    from cobo.lock.diff import FileDrift
    from cobo.lock.schema import Fragment, Lockfile

CloneRootProvider = Callable[[Source], Path]


@dataclass(frozen=True, slots=True)
class FragmentReport:
    """Per-fragment outcome of a check.

    Attributes:
        path: Output path of the fragment.
        source: Source name.
        held: True when update=False (skipped).
        drifts: Files whose content changed (empty when clean or held).
        error: Non-None when the fragment could not be evaluated.
    """

    path: str
    source: str
    held: bool
    drifts: tuple[FileDrift, ...]
    error: str | None = None

    @property
    def outdated(self) -> bool:
        """Whether this fragment needs an update.

        Returns:
            True when not held, not errored, and at least one file drifted.
        """
        return not self.held and self.error is None and bool(self.drifts)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Aggregate result of checking every fragment.

    Attributes:
        reports: One report per fragment, in lockfile order.
    """

    reports: tuple[FragmentReport, ...]

    @property
    def outdated_count(self) -> int:
        """Number of fragments that need updating.

        Returns:
            Count of reports whose ``outdated`` is True.
        """
        return sum(1 for r in self.reports if r.outdated)


def gather_current_blobs(
    fragment: Fragment, source: Source, clone_root: Path, *, refresh: bool
) -> dict[str, str | None]:
    """Resolve the current blob SHA for each of a fragment's files.

    Args:
        fragment: The fragment whose files to resolve.
        source: The source to (optionally) refresh.
        clone_root: The source clone path.
        refresh: When True, clone/pull before reading blobs.

    Returns:
        Map of repo-relative path -> current blob SHA, or None when a file
        could not be resolved (e.g. it was deleted upstream).
    """
    if refresh:
        clone_or_pull(source, clone_root)
    blobs: dict[str, str | None] = {}
    for file in fragment.files:
        try:
            blobs[file.path] = blob_sha_for_path(clone_root, file.path)
        except GitError:
            blobs[file.path] = None
    return blobs


def run_check(
    lock: Lockfile,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    *,
    refresh: bool = True,
) -> CheckResult:
    """Check every fragment for drift.

    Args:
        lock: The parsed lockfile.
        sources: Resolved sources keyed by name.
        clone_root_provider: Maps a Source to its clone path.
        refresh: When True, refresh each source clone before reading blobs.

    Returns:
        A CheckResult with one report per fragment.
    """
    reports: list[FragmentReport] = []
    for frag in lock.fragments:
        reports.append(_check_fragment(frag, sources, clone_root_provider, refresh))
    return CheckResult(tuple(reports))


def _check_fragment(
    frag: Fragment,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    refresh: bool,
) -> FragmentReport:
    """Evaluate one fragment.

    Returns:
        Its FragmentReport (held, errored, clean, or drifted).
    """
    source = sources.get(frag.source)
    if source is None:
        return FragmentReport(
            path=frag.path,
            source=frag.source,
            held=False,
            drifts=(),
            error=f"unknown source '{frag.source}'",
        )
    if not frag.update:
        return FragmentReport(path=frag.path, source=frag.source, held=True, drifts=())
    try:
        blobs = gather_current_blobs(
            frag, source, clone_root_provider(source), refresh=refresh
        )
    except GitError as exc:
        return FragmentReport(
            path=frag.path, source=frag.source, held=False, drifts=(), error=str(exc)
        )
    return FragmentReport(
        path=frag.path,
        source=frag.source,
        held=False,
        drifts=compute_fragment_drift(frag, blobs),
    )
```

- [ ] **Step 4: Run; expect pass**

Run: `uv run pytest tests/integration/test_check_sync.py -k check -p no:randomly -n0 -v`
Expected: PASS (3 check tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/commands/check.py tests/integration/test_check_sync.py
git commit -m "feat(check): drift report core over the lockfile (#48)"
```

---

## Task 8: Wire `cobo check` CLI (`globals.py`)

**Files:**
- Modify: `src/cobo/globals.py`
- Test: `tests/e2e/test_check_cli.py`

`check` and `sync` are global commands. They resolve the lockfile from `cwd`, use `config.sources`, and a clone-root provider built from `source_clone_root`.

- [ ] **Step 1: Write the failing e2e test**

Create `tests/e2e/test_check_cli.py`:

```python
"""End-to-end tests for `cobo check` CLI surface (no network)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cobo.cli import app

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e

runner = CliRunner()

_LOCK_UNKNOWN_SOURCE = """\
version = 1

[[fragment]]
path = ".gitignore"
source = "does-not-exist"
update = true

  [[fragment.files]]
  name = "Python"
  path = "Python.gitignore"
  commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  blob = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
"""


def test_check_missing_lock_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No lockfile -> usage error, exit code 2."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 2, result.output


def test_check_unknown_source_reports_and_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown-source fragment is reported but is not 'outdated' (exit 0)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cobo.lock").write_text(_LOCK_UNKNOWN_SOURCE, encoding="utf-8")
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "does-not-exist" in result.output


def test_check_json_emits_machine_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json prints parseable JSON with a fragments array."""
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "cobo.lock").write_text(_LOCK_UNKNOWN_SOURCE, encoding="utf-8")
    result = runner.invoke(app, ["check", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["outdated_count"] == 0
    assert payload["fragments"][0]["path"] == ".gitignore"
```

- [ ] **Step 2: Run; expect failure**

Run: `uv run pytest tests/e2e/test_check_cli.py -p no:randomly -n0 -v`
Expected: FAIL — no `check` command registered (`exit_code == 2` from Typer "no such command", but JSON/report assertions fail).

- [ ] **Step 3: Register `check` in `globals.py`**

Add these imports to `src/cobo/globals.py` (it already imports `typer`, `Console`, `Table`, `source_clone_root`):

```python
import json
from pathlib import Path

from cobo.commands.check import CheckResult, run_check
from cobo.lock.io import find_lock, read_lock
```

Add the call inside `attach_globals` (after `_register_config_path(...)`):

```python
    _register_check(app, config=config)
```

Add the command + helpers at the end of the module:

```python
def _clone_root_provider(source: object) -> Path:
    """Map a source to its cache clone path.

    Returns:
        The clone root directory for the source.
    """
    return source_clone_root(source.name)  # type: ignore[attr-defined]


def _register_check(app: typer.Typer, *, config: CoboConfig) -> None:
    @app.command()
    def check(
        json_output: bool = typer.Option(
            False, "--json", help="Emit machine-readable JSON."
        ),
    ) -> None:
        """Report fragments whose origin has drifted from the lockfile.

        Raises:
            Exit: Code 2 when no cobo.lock is found; code 1 when updates are
                available; code 0 when everything is up to date.
        """
        lock_path = find_lock(Path.cwd())
        if lock_path is None:
            typer.echo("No cobo.lock found. Run `cobo <source> dump --lock`.", err=True)
            raise typer.Exit(2)
        result = run_check(read_lock(lock_path), config.sources, _clone_root_provider)
        if json_output:
            typer.echo(json.dumps(_result_to_dict(result)))
        else:
            _print_check_table(result)
        raise typer.Exit(1 if result.outdated_count else 0)


def _result_to_dict(result: CheckResult) -> dict[str, object]:
    """Convert a CheckResult to a JSON-serializable dict.

    Returns:
        A dict with ``outdated_count`` and a ``fragments`` array.
    """
    return {
        "outdated_count": result.outdated_count,
        "fragments": [
            {
                "path": r.path,
                "source": r.source,
                "held": r.held,
                "outdated": r.outdated,
                "error": r.error,
                "files": [
                    {"name": d.name, "old_blob": d.old_blob, "new_blob": d.new_blob}
                    for d in r.drifts
                ],
            }
            for r in result.reports
        ],
    }


def _print_check_table(result: CheckResult) -> None:
    """Print a Rich table summarizing the check result."""
    table = Table("Fragment", "Source", "Status")
    for r in result.reports:
        if r.error is not None:
            status = f"error: {r.error}"
        elif r.held:
            status = "held"
        elif r.outdated:
            status = f"outdated ({len(r.drifts)} file(s))"
        else:
            status = "up to date"
        table.add_row(r.path, r.source, status)
    _console.print(table)
    _console.print(f"{result.outdated_count} fragment(s) need updating.")
```

Note: `_clone_root_provider` uses `source.name`; the `type: ignore` avoids importing `Source` purely for typing. If pyright/mypy/ty/pyrefly reject the ignore, import `Source` under `TYPE_CHECKING` and annotate the parameter as `Source` instead, dropping the ignore.

- [ ] **Step 4: Run; expect pass**

Run: `uv run pytest tests/e2e/test_check_cli.py -p no:randomly -n0 -v`
Expected: PASS (3 tests). Note `test_check_unknown_source_reports_and_exits_0` does not touch the network because unknown sources short-circuit before any clone.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/globals.py tests/e2e/test_check_cli.py
git commit -m "feat(cli): add `cobo check` with --json and exit-code contract (#48)"
```

---

## Task 9: Sync core (`commands/sync.py`)

**Files:**
- Create: `src/cobo/commands/sync.py`
- Test: append to `tests/integration/test_check_sync.py`

- [ ] **Step 1: Append the failing test**

Add to `tests/integration/test_check_sync.py`:

```python
def test_sync_rewrites_file_and_advances_lock(tmp_path: Path) -> None:
    """sync re-renders the drifted file and updates its blob in the lock."""
    from cobo.commands.sync import run_sync

    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    old_blob = read_lock(lock_path).fragments[0].files[0].blob
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")

    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert result.changed == (".gitignore",)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "*.pyc\n*.pyo\n"
    assert read_lock(lock_path).fragments[0].files[0].blob != old_blob


def test_sync_dry_run_writes_nothing(tmp_path: Path) -> None:
    """dry_run reports changes but does not touch files or the lock."""
    from cobo.commands.sync import run_sync

    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    out = tmp_path / ".gitignore"
    out.write_text("*.pyc\n", encoding="utf-8")
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")

    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
        dry_run=True,
    )
    assert result.changed == (".gitignore",)
    assert out.read_text(encoding="utf-8") == "*.pyc\n"  # unchanged


def test_sync_skips_held_fragment(tmp_path: Path) -> None:
    """A held fragment is never rewritten."""
    from dataclasses import replace

    from cobo.commands.sync import run_sync
    from cobo.lock.io import write_lock
    from cobo.lock.schema import Lockfile

    source, clone = make_source(tmp_path, {"Python.gitignore": "*.pyc\n"})
    clone_or_pull(source, clone)
    lock_path = _record(tmp_path, source, clone, ["Python"])
    lock = read_lock(lock_path)
    write_lock(
        lock_path,
        Lockfile(version=1, fragments=(replace(lock.fragments[0], update=False),)),
    )
    advance_source(tmp_path, "Python.gitignore", "*.pyc\n*.pyo\n")
    result = run_sync(
        read_lock(lock_path),
        {source.name: source},
        _provider_factory(clone),
        lock_dir=tmp_path,
        lock_path=lock_path,
    )
    assert result.changed == ()
```

- [ ] **Step 2: Run; expect failure**

Run: `uv run pytest tests/integration/test_check_sync.py -k sync -p no:randomly -n0 -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cobo.commands.sync'`.

- [ ] **Step 3: Implement `src/cobo/commands/sync.py`**

```python
"""Apply fragment updates in place and advance the lockfile (`cobo sync`)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from cobo.commands.check import run_check
from cobo.errors import CoboError
from cobo.lock.io import write_lock
from cobo.lock.schema import Fragment, LockedFile, Lockfile
from cobo.sources.render import dump as render_dump
from cobo.sources.repo import blob_sha_for_path, current_commit_sha

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from cobo.commands.check import CheckResult, CloneRootProvider
    from cobo.config.schema import Source


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Outcome of a sync run.

    Attributes:
        changed: Output paths that were (or, in dry-run, would be) rewritten.
        failed: Output paths that errored during re-render.
        check: The underlying CheckResult that drove the sync.
    """

    changed: tuple[str, ...]
    failed: tuple[str, ...]
    check: CheckResult


def run_sync(
    lock: Lockfile,
    sources: Mapping[str, Source],
    clone_root_provider: CloneRootProvider,
    *,
    lock_dir: Path,
    lock_path: Path,
    dry_run: bool = False,
    refresh: bool = True,
) -> SyncResult:
    """Re-render outdated fragments and advance the lockfile.

    Args:
        lock: The parsed lockfile.
        sources: Resolved sources keyed by name.
        clone_root_provider: Maps a Source to its clone path.
        lock_dir: Directory the fragment output paths are relative to.
        lock_path: Where to write the updated lockfile.
        dry_run: When True, compute changes but write nothing.
        refresh: Forwarded to the underlying check (refresh clones).

    Returns:
        A SyncResult describing changed/failed fragments.
    """
    result = run_check(lock, sources, clone_root_provider, refresh=refresh)
    changed: list[str] = []
    failed: list[str] = []
    new_fragments: list[Fragment] = []
    for frag, report in zip(lock.fragments, result.reports, strict=True):
        if not report.outdated:
            new_fragments.append(frag)
            continue
        try:
            rebuilt = _rerender(frag, sources[frag.source], clone_root_provider, lock_dir, dry_run=dry_run)
        except CoboError:
            failed.append(frag.path)
            new_fragments.append(frag)
            continue
        changed.append(frag.path)
        new_fragments.append(rebuilt)
    if changed and not dry_run:
        write_lock(lock_path, Lockfile(version=lock.version, fragments=tuple(new_fragments)))
    return SyncResult(changed=tuple(changed), failed=tuple(failed), check=result)


def _rerender(
    frag: Fragment,
    source: Source,
    clone_root_provider: CloneRootProvider,
    lock_dir: Path,
    *,
    dry_run: bool,
) -> Fragment:
    """Re-render one fragment's output and return its advanced lock entry.

    Returns:
        The fragment with each file's commit/blob refreshed to the clone HEAD.

    Raises:
        CoboError: When rendering or blob resolution fails.
    """
    clone_root = clone_root_provider(source)
    commit = current_commit_sha(clone_root)
    names = [f.name for f in frag.files]
    content = render_dump(source, clone_root, names, commit)
    if not dry_run:
        (lock_dir / frag.path).write_bytes(content.encode("utf-8"))
    new_files = tuple(
        LockedFile(
            name=f.name,
            path=f.path,
            commit=commit,
            blob=blob_sha_for_path(clone_root, f.path),
        )
        for f in frag.files
    )
    return replace(frag, files=new_files)
```

- [ ] **Step 4: Run; expect pass**

Run: `uv run pytest tests/integration/test_check_sync.py -k sync -p no:randomly -n0 -v`
Expected: PASS (3 sync tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/commands/sync.py tests/integration/test_check_sync.py
git commit -m "feat(sync): re-render outdated fragments and advance the lock (#48)"
```

---

## Task 10: Wire `cobo sync` CLI (`globals.py`)

**Files:**
- Modify: `src/cobo/globals.py`
- Test: append to `tests/e2e/test_check_cli.py`

- [ ] **Step 1: Append the failing e2e test**

Add to `tests/e2e/test_check_cli.py`:

```python
def test_sync_missing_lock_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cobo sync` with no lockfile exits 2."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 2, result.output


def test_sync_dry_run_unknown_source_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cobo sync --dry-run` over an unknown-source lock changes nothing (exit 0)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cobo.lock").write_text(_LOCK_UNKNOWN_SOURCE, encoding="utf-8")
    result = runner.invoke(app, ["sync", "--dry-run"])
    assert result.exit_code == 0, result.output
```

- [ ] **Step 2: Run; expect failure**

Run: `uv run pytest tests/e2e/test_check_cli.py -k sync -p no:randomly -n0 -v`
Expected: FAIL — no `sync` command (`exit_code` from Typer differs / assertion fails).

- [ ] **Step 3: Register `sync` in `globals.py`**

Add the import:

```python
from cobo.commands.sync import run_sync
```

Add the call inside `attach_globals` (after `_register_check(...)`):

```python
    _register_sync(app, config=config)
```

Add the command at the end of the module:

```python
def _register_sync(app: typer.Typer, *, config: CoboConfig) -> None:
    @app.command()
    def sync(
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Show what would change without writing."
        ),
    ) -> None:
        """Re-render outdated fragments and open them for commit.

        Raises:
            Exit: Code 2 when no cobo.lock is found; code 1 when any fragment
                failed to re-render; code 0 otherwise.
        """
        lock_path = find_lock(Path.cwd())
        if lock_path is None:
            typer.echo("No cobo.lock found. Run `cobo <source> dump --lock`.", err=True)
            raise typer.Exit(2)
        result = run_sync(
            read_lock(lock_path),
            config.sources,
            _clone_root_provider,
            lock_dir=lock_path.parent,
            lock_path=lock_path,
            dry_run=dry_run,
        )
        for path in result.changed:
            typer.echo(f"updated: {path}")
        for path in result.failed:
            typer.echo(f"failed: {path}", err=True)
        if not result.changed and not result.failed:
            typer.echo("All fragments up to date.")
        raise typer.Exit(1 if result.failed else 0)
```

- [ ] **Step 4: Run; expect pass**

Run: `uv run pytest tests/e2e/test_check_cli.py -p no:randomly -n0 -v`
Expected: PASS (all check + sync e2e tests).

- [ ] **Step 5: Full suite + coverage gate**

Run: `uv run pytest -n0 -q`
Expected: PASS, coverage ≥ 95%. If any new module is below the line, add a targeted test (e.g. a `gather_current_blobs(..., refresh=False)` case, or a sync `failed` case where a recorded file is deleted upstream).

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run mypy && uv run pyright
git add src/cobo/globals.py tests/e2e/test_check_cli.py
git commit -m "feat(cli): add `cobo sync` with --dry-run (#48)"
```

---

# Phase 3 — GitHub Action + docs

## Task 11: Composite Action (`action.yml`)

**Files:**
- Create: `action.yml`

- [ ] **Step 1: Write `action.yml`**

```yaml
name: cobo update fragments
description: Re-render drifted cobo fragments and open a pull request.
branding:
  icon: refresh-cw
  color: blue
inputs:
  config:
    description: Path to a cobo config TOML (sets COBO_CONFIG). Optional.
    required: false
    default: ""
  pr-title:
    description: Title for the opened pull request.
    required: false
    default: "chore: update cobo fragments"
  pr-labels:
    description: Comma-separated labels for the pull request.
    required: false
    default: cobo
  branch:
    description: Branch the action pushes updates to.
    required: false
    default: cobo/update-fragments
runs:
  using: composite
  steps:
    - name: Install uv
      uses: astral-sh/setup-uv@v6
    - name: Sync fragments
      shell: bash
      env:
        COBO_CONFIG: ${{ inputs.config }}
      run: |
        uvx cobo sync
        uvx cobo check --json > cobo-check.json || true
    - name: Build PR body
      id: body
      shell: bash
      run: |
        {
          echo "body<<EOF"
          echo "Automated cobo fragment update."
          echo
          echo '```json'
          cat cobo-check.json
          echo '```'
          echo "EOF"
        } >> "$GITHUB_OUTPUT"
        rm -f cobo-check.json
    - name: Create pull request
      uses: peter-evans/create-pull-request@v7
      with:
        title: ${{ inputs.pr-title }}
        labels: ${{ inputs.pr-labels }}
        branch: ${{ inputs.branch }}
        body: ${{ steps.body.outputs.body }}
        commit-message: ${{ inputs.pr-title }}
```

- [ ] **Step 2: Lint the Action**

Run: `uv run actionlint action.yml` (actionlint is in the lint dependency group). If `actionlint` is not directly invocable, run the style env: `uv run tox -e style` and confirm no Action errors. Also run `uv run yamlfmt -conf .github/yamlfmt.yml action.yml`.
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add action.yml
git commit -m "feat(action): composite action to sync fragments and open a PR (#48)"
```

---

## Task 12: Documentation

**Files:**
- Create: `docs/fragment-updates.md`
- Modify: `README.md`

- [ ] **Step 1: Write `docs/fragment-updates.md`**

Document, with copy-paste examples: (a) recording a dump with `cobo gitignore dump Python Node --out .gitignore --lock`; (b) the `cobo.lock` format including `commit` vs `blob` and `update = false` to hold a fragment back; (c) `cobo check` (exit codes 0/1/2, `--json` shape) and `cobo sync` (`--dry-run`); (d) the revised two-line header; (e) a ready-to-paste workflow:

````markdown
```yaml
# .github/workflows/cobo.yml
name: cobo
on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:
permissions:
  contents: write
  pull-requests: write
jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hasansezertasan/cobo@v1
        with:
          pr-title: "chore: update cobo fragments"
```
````

- [ ] **Step 2: Add a README section**

Add a "Keeping fragments up to date" section to `README.md` summarizing `--lock`, `check`, `sync`, and linking to `docs/fragment-updates.md`.

- [ ] **Step 3: Lint docs and commit**

Run: `uv run typos --diff` and fix any flagged typos.

```bash
git add docs/fragment-updates.md README.md
git commit -m "docs: document fragment updates, lockfile, and the Action (#48)"
```

---

## Task 13: Final verification

- [ ] **Step 1: Run the whole suite by marker**

```bash
uv run pytest -m unit -n0 -q
uv run pytest -m integration -n0 -q
uv run pytest -m e2e -n0 -q
```
Expected: all PASS.

- [ ] **Step 2: Full style + coverage via tox**

Run: `uv run tox -e style` then `uv run pytest -n0 -q`.
Expected: linters clean, coverage ≥ 95%.

- [ ] **Step 3: Manual smoke (optional, network)**

In a scratch dir with a real source configured:
```bash
cd /tmp && rm -rf cobo-smoke && mkdir cobo-smoke && cd cobo-smoke
uvx --from /Users/hasansezertasan/.superset/worktrees/cobo/feat/glib-yew cobo gitignore update
uvx --from /Users/hasansezertasan/.superset/worktrees/cobo/feat/glib-yew cobo gitignore dump Python --out .gitignore --lock
cat cobo.lock          # one fragment, one file with commit+blob
uvx --from /Users/hasansezertasan/.superset/worktrees/cobo/feat/glib-yew cobo check   # exit 0 (up to date)
```
Expected: lockfile written; `check` reports up to date.

- [ ] **Step 4: Update issue #48**

```bash
gh issue comment 48 --body "Implemented across lockfile + check/sync + composite Action. Deferred to a later phase: \`cobo lock import\` (header-seeded adoption)."
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Lockfile format + `blob` drift key → Tasks 1, 2, 3. ✅
- `blob_sha_for_path` on shallow clones → Task 4. ✅
- Two-line header, full-SHA URL, nested-path fix → Task 5. ✅
- `dump --lock --out` → Task 6. ✅
- `cobo check` (exit 0/1/2, `--json`, held) → Tasks 7, 8. ✅
- `cobo sync` (`--dry-run`, per-fragment isolation, advance lock) → Tasks 9, 10. ✅
- Composite Action → Task 11. ✅
- Docs (README + page) → Task 12. ✅
- `update = false` hold-back honored in check and sync → Tasks 7, 9 tests. ✅
- Error handling (missing lock → 2; `--lock` without `--out` → 2; unknown source non-fatal; missing blob → None; atomic write) → Tasks 2, 6, 7, 8. ✅
- Out of scope: `lock import`, Docker action, Action-level exclude → noted, deferred (Task 13 comment). ✅

**Type consistency:** `LockedFile(name, path, commit, blob)`, `Fragment(path, source, files, update)`, `Lockfile(version, fragments)`, `FileDrift(name, path, old_blob, new_blob)`, `FragmentReport(path, source, held, drifts, error)`, `CheckResult(reports)`, `SyncResult(changed, failed, check)` are used consistently across Tasks 1–10. `run_check(lock, sources, clone_root_provider, *, refresh)` and `run_sync(lock, sources, clone_root_provider, *, lock_dir, lock_path, dry_run, refresh)` signatures match their call sites in `globals.py`.

**Known follow-ups flagged inline (not placeholders):** the `record.py` `_empty`/`resolve_lock_path` lazy imports and the `globals.py` `_clone_root_provider` `type: ignore` each carry an explicit "if the type-checkers reject X, do Y" instruction, because the exact strict-checker behavior (4 checkers) can't be predicted without running them.
```
