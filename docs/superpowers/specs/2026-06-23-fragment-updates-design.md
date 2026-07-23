# Design: Keep dumped fragments up to date (lockfile + update Action)

- **Issue:** [#48](https://github.com/hasansezertasan/cobo/issues/48)
- **Status:** Approved design, pending implementation plan
- **Date:** 2026-06-23

## Problem

`cobo <source> dump <name>` is fire-and-forget. Once a `.gitignore` or `mise.toml`
is written into a repo, it silently drifts from its upstream origin. Users have no
way to learn that, e.g., `github/gitignore@Python` changed months ago. Boilerplates
rot exactly like un-pinned dependencies, and the fix is the same pattern Dependabot
and Renovate use: **pin → detect drift → propose update via PR.**

This design extends cobo from a one-shot copier into a tool that keeps dumped
fragments current, with a GitHub Action that opens one grouped (configurable) PR
when an origin moves ahead of the pinned commit.

## Decisions (agreed during brainstorming)

1. **Lockfile (`cobo.lock`) is the source of truth** — not header-scraping. It
   handles `multi_dump` (one output, several origins) and headerless sources that a
   header scanner can't see.
2. **Per-source-file tracking with content-addressed detection** — each input file
   records its resolved repo-relative path, the `commit` (full SHA, used for the
   header/URL provenance), and a `blob` SHA used as the **drift key**. cobo's clones
   are shallow (`depth=1`), so commit-history comparison (`git log -- path`) is not
   available — it would flag every file whenever the branch HEAD moves. The blob SHA
   (`git rev-parse HEAD:<path>`) is content-addressed, works on a shallow clone, and
   changes iff the file content changes. Storing the resolved path also fixes the
   broken-URL bug (real path, not just `path.name`).
3. **Adoption:** `dump --lock` is the primary way entries are created. A
   `cobo lock import` (seed from existing headers) is a *deferred, later-phase*
   convenience, not part of v1.
4. **Hold-back via lock pin:** a fragment carries `update = false` to be skipped by
   `check`/`sync`. Portable, version-controlled, honored locally and in CI.
5. **Revised header:** two lines (attribution + corrected provenance/URL), down from
   today's five. The lock carries the authoritative machine-readable data.
6. **Grouped, configurable PRs:** one PR by construction; hold-back is the lock pin,
   so no Action-level exclude input is needed in v1.
7. **Architecture:** Python core (testable) + thin composite GitHub Action. Mirrors
   the Dependabot/Renovate engine-plus-runner split. `cobo sync` is equally useful
   locally.

## Lockfile format

`cobo.lock` lives at the repo root (next to where dumps are run), TOML,
version-controlled. One `[[fragment]]` per output file.

```toml
version = 1

[[fragment]]
path = ".gitignore"            # output file, relative to lock location
source = "gitignore"
update = true                  # false = held back by user

  [[fragment.files]]
  name   = "Python"            # the dumped name
  path   = "Python.gitignore"  # resolved repo-relative path (fixes URL bug)
  commit = "abc1234..."        # full SHA the file was rendered from (provenance)
  blob   = "b3ec7d5..."        # blob SHA at that commit (drift key)

  [[fragment.files]]
  name   = "Node"
  path   = "Node.gitignore"
  commit = "abc1234..."
  blob   = "1a2b3c4..."

[[fragment]]
path = "mise.toml"
source = "mise"
update = false                 # pinned; check/sync skip it

  [[fragment.files]]
  name   = "python"
  path   = "python.mise.toml"
  commit = "def5678..."
  blob   = "9f8e7d6..."
```

## Module layout

New code as small, single-purpose units under `src/cobo/`, matching existing
config style (frozen dataclasses, `slots`).

| Module | Responsibility |
|---|---|
| `lock/schema.py` | `Lockfile`, `Fragment`, `LockedFile` dataclasses (incl. `blob`) |
| `lock/io.py` | Find-upward, parse, serialize, **atomic** write of `cobo.lock` |
| `lock/diff.py` | Pure drift logic: lock entries + current blob SHAs → `Outdated[]`. No git, no FS. |
| `sources/repo.py` *(extend)* | `blob_sha_for_path(clone, repo_path)` — `git rev-parse HEAD:<path>` |
| `sources/render.py` *(revise)* | Two-line header + correct URL from resolved repo path |
| `commands/check.py`, `commands/sync.py` | Thin CLI handlers wiring the above |

`lock/diff.py` is deliberately pure so drift logic is trivially unit-testable; git
I/O is pushed to the edges in `repo.py`.

## Command behavior

### `cobo <source> dump <name>... --lock --out <path>`

Renders as today, and additionally resolves each name to its repo-relative path, the
clone's current commit, and the file's blob SHA (`git rev-parse HEAD:<path>`), then
upserts a `[[fragment]]` keyed by the **output path**. Writing the lock requires a known output path, so `--lock` mandates `--out`;
`--lock` with a stdout dump errors with a clear message. Re-dumping the same output
path overwrites its entry (idempotent). New entries default `update = true`.

### `cobo check` — read-only drift report (CI gate)

1. Load `cobo.lock` (error if absent).
2. For each fragment with `update = true`, refresh its source clone, then for each
   `LockedFile` call `repo.blob_sha_for_path(clone, file.path)`.
3. `lock/diff` compares each file's stored `blob` vs the current blob SHA →
   `Outdated[]` (a fragment is outdated if any of its files' blobs differ).
4. Render a Rich table; `--json` emits machine-readable output for the Action. The
   count of outdated fragments is reported in the output/JSON, not the exit code.
5. **Exit code: `0` clean, `1` updates available, `2` usage/config error.** Pinned
   fragments are listed as "held" and never counted as outdated.

### `cobo sync` — apply updates

1. Run `check`'s detection.
2. For each outdated file: re-render from the current clone, rewrite the output file
   (preserving multi_dump concatenation order from the lock), advance that file's
   `commit` and `blob` in the lock.
3. `--dry-run` reports without writing; default writes files and `cobo.lock`.
4. Honors `update = false`. Per-fragment isolation: one source failing skips that
   fragment and continues, with a non-zero summary.

## Data flow (CI)

```
cobo.lock --> check --> Outdated[] --> sync --> edited files + updated cobo.lock
                                                       |
                                          git diff --> create-pull-request --> grouped PR
```

## Revised header

Two lines, replacing today's five-line block. Two fixes over the current header:

1. The URL is reconstructed from the **resolved repo-relative path**, fixing the
   nested-directory 404 bug (`Global/macOS.gitignore` was being truncated to
   `macOS.gitignore`).
2. The URL uses the **full 40-char SHA**, not the short one. Abbreviated SHAs are
   resolved to the minimum-unique prefix at request time and can become ambiguous
   (and start 404ing) as the repo grows. The short SHA stays only as the
   human-readable `@` token. The lockfile already stores the full SHA.

```
# Generated by cobo (github.com/hasansezertasan/cobo)
# gitignore/Python@5763345 — https://raw.githubusercontent.com/github/gitignore/576334520435382d6522f349b9d270eda1e79a25/Python.gitignore
<file body>
```

For `multi_dump`, one provenance line precedes each input's block.

## GitHub Action (`action.yml`, composite)

```yaml
inputs:
  config:    { default: "" }      # COBO_CONFIG path, optional
  pr-title:  { default: "chore: update cobo fragments" }
  pr-labels: { default: "cobo" }
runs:
  using: composite
  steps:
    - uses: astral-sh/setup-uv@v6
    - run: uvx cobo sync           # writes files + cobo.lock
      shell: bash
    - uses: peter-evans/create-pull-request@v7
      with:
        title: ${{ inputs.pr-title }}
        labels: ${{ inputs.pr-labels }}
        branch: cobo/update-fragments
        body: <generated from `cobo check --json`>
```

The PR body is built from `cobo check --json` (a table of `path · old→new`).
Grouping is "one PR" by construction; per-fragment hold-back is the `update=false`
lock pin, so v1 needs no Action-level exclude input.

## Error handling

Extends the existing `CoboError` / `UserError` / `GitError` / `ConfigError`
hierarchy.

| Situation | Behavior |
|---|---|
| `cobo.lock` missing on `check`/`sync` | `UserError` with guidance; exit 2 |
| `--lock` without `--out` | `UserError`: lock writing needs a known output path |
| Lock entry references a name/path no longer in source | Per-fragment stderr warning, marked `error`, skipped — not fatal |
| Source clone/fetch fails (network) | `GitError` caught per-fragment; skipped; summary exit non-zero |
| Malformed `cobo.lock` (bad TOML / unknown `version`) | `ConfigError` naming the offending key; never silently overwrite |
| Interrupted write | Atomic temp-file + rename; `cobo.lock` never left half-written |

Exit-code contract is explicit and collision-free: **0** clean, **1** updates
available (`check`), **2** usage/config error. The outdated *count* lives in the
report/JSON, not the exit code. No silent failures.

## Testing

Mirrors existing `tests/{unit,integration,e2e,smoke}` layout.

- **unit** — `lock/diff.py` (pure: stored-blob-vs-current-blob → expected
  `Outdated[]`, including multi_dump partial drift, all-pinned, empty lock);
  `lock/io.py`
  round-trip (serialize→parse identity, atomic write, find-upward); revised
  `render.py` header (two-line format; URL uses the full SHA and the resolved
  repo-relative path, including a nested `Global/` path that exposed the old bug).
- **integration** — against a real temp git repo as a fake source: `dump --lock`
  writes a correct entry; advancing the fake source HEAD makes `check` report drift
  and `sync` re-render + re-pin; `update = false` is respected.
- **e2e** — full CLI: `dump --lock` → mutate source → `check` exit code → `sync` →
  second `check` is clean.
- **Action** — not unit-tested in this repo's CI; documented manual validation plus
  a `workflow_dispatch` smoke run in a sandbox repo.

## Documentation (DDD — written before implementation)

- README section on keeping fragments up to date.
- `docs/` page: lockfile format, `check`/`sync` commands, Action usage.
- Revised header documented.

## Out of scope (v1)

- `cobo lock import` (header-seeded adoption) — deferred to a later phase.
- Docker container Action — revisit only if CI dependency drift becomes a problem.
- Action-level exclude input, per-source/per-fragment PR grouping — lock pin covers
  the hold-back need for now.

## Suggested phasing

1. **Lockfile + header revision** — `lock/{schema,io,diff}`, `repo` per-file lookup,
   revised `render.py`, `dump --lock --out`.
2. **Commands** — `cobo check` and `cobo sync` with the exit-code contract.
3. **Action + docs** — composite `action.yml`, README/docs, sandbox smoke run.
