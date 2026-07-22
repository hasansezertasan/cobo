# Keeping fragments up to date

cobo can track the boilerplates it dumps and alert you — or automatically update
them — when the upstream template changes. The mechanism mirrors Dependabot and
Renovate: pin a version, detect drift, open a PR.

## Overview

When you dump a boilerplate with `--lock`, cobo writes (or updates) a `cobo.lock`
file. The lockfile records which source file was rendered and a content-addressed
blob SHA. Later, `cobo check` compares the stored blobs against the current
upstream blobs and reports any that have drifted. `cobo sync` re-renders and
re-pins the outdated fragments in one step, rewriting only the cobo-owned
[managed block](#editing-a-managed-file) so any edits you make around it survive.

---

## Recording a dump

Pass `--out <FILE>` to write to a file instead of stdout, and add `--lock` to
record the dump in `cobo.lock`:

```sh
cobo gitignore dump Python Node --out .gitignore --lock
```

cobo renders `.gitignore` from the `Python` and `Node` templates, writes it, and
creates or updates `cobo.lock`. The lockfile location is determined by walking up
from the current working directory for the nearest existing `cobo.lock`; if none
is found, `cobo.lock` is created in the current working directory (not necessarily
beside the `--out` file). Fragment output paths in the lockfile are stored relative
to the lockfile's directory.

> `--lock` requires `--out`. Using `--lock` without `--out` exits with code 2 and
> prints an error — there is no path to track when writing to stdout.

Run the same command again after `cobo gitignore update` to refresh the pin.

### Adopting pre-existing dumps

If you dumped boilerplates before adopting the lockfile (or generated them on
another machine), `cobo lock import` reconstructs lock entries from the
provenance headers already written into those files:

```sh
cobo lock import .gitignore .editorconfig
```

For each file, cobo reads its two-line provenance header(s) to recover the
source and boilerplate name(s), re-resolves them against the **current**
upstream HEAD, and records the entry — exactly as a fresh `dump --lock` would.
Because cobo uses shallow clones, it cannot resurrect the original pinned
commit, so import always adopts the current upstream state. If an imported file
is already stale, the very next `cobo check` reports it as outdated.

Requirements and behavior:

- The file must carry a cobo provenance header (its source must have
  `inject_header = true`). A file with no recognizable header is reported as a
  failure and skipped; the remaining files are still imported.
- All header lines within one file must reference the same source.
- An existing `update = false` hold-back on a re-imported fragment is preserved.
- Exit `0` when every file imported, `1` when any file failed, `2` when an
  existing `cobo.lock` is malformed (a single global error, not a per-file one).

---

## The cobo.lock format

`cobo.lock` is a TOML file, version-controlled alongside your project. It has one
`[[fragment]]` block per tracked output file.

### Example

```toml
version = 1

[[fragment]]
path = ".gitignore"
source = "gitignore"
update = true

  [[fragment.files]]
  name = "Python"
  path = "Python.gitignore"
  commit = "576334520435382d6522f349b9d270eda1e79a25"
  blob = "b3ec7d5a8e3c2f1d9e4a0b7c6f2e1d8a9b4c3e2f"

  [[fragment.files]]
  name = "Node"
  path = "Node.gitignore"
  commit = "576334520435382d6522f349b9d270eda1e79a25"
  blob = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"

[[fragment]]
path = "mise.toml"
source = "mise"
update = false

  [[fragment.files]]
  name = "python"
  path = "python.mise.toml"
  commit = "def56789ab12345678901234567890abcdef1234"
  blob = "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e"
```

### Field reference

| Field | Level | Description |
|---|---|---|
| `version` | top-level | Lockfile schema version. Currently always `1`. |
| `[[fragment]]` | per output file | One block per tracked file. |
| `path` | fragment | Output file path, relative to the lockfile's location. |
| `source` | fragment | The cobo source name (`gitignore`, `mise`, etc.). |
| `update` | fragment | `true` (default) — check/sync consider this fragment. `false` — held back; check and sync skip it. |
| `[[fragment.files]]` | per input file | One block per input boilerplate that contributed to the output (multi-dump may have several). |
| `name` | files | Boilerplate name as passed to `dump` (e.g. `"Python"`). |
| `path` | files | Repo-relative POSIX path inside the source clone (e.g. `"Python.gitignore"`). Used to build the provenance URL. |
| `commit` | files | Full hex SHA the file was rendered from (40 chars for SHA-1, 64 for SHA-256). Used for the provenance header URL. |
| `blob` | files | Blob SHA at that commit (`git rev-parse HEAD:<path>`). This is the **drift key**: it is content-addressed and works on cobo's shallow clones. When the blob changes, the file has changed. |

**`commit` vs `blob`:** `commit` is provenance — it identifies the exact upstream
state the file came from and appears in the header URL. `blob` is the drift key —
`cobo check` compares stored blob SHAs against current upstream blob SHAs; a
mismatch means the template content has changed. Storing the blob SHA (rather than
comparing commit history) is essential because cobo uses shallow clones, where `git
log` history is not available.

---

## Checking for updates

```sh
cobo check
```

Reads `cobo.lock`, refreshes each source clone, then compares stored blob SHAs
against the current upstream blob SHAs. Prints a Rich table with one row per
tracked fragment showing its status: **up to date**, **outdated**, **held**, or
**error**. The status also flags the on-disk file when its managed block was
hand-edited (**locally modified**) or its markers are missing/malformed (see
[Editing a managed file](#editing-a-managed-file)).

For machine-readable output (e.g. in CI scripts):

```sh
cobo check --json
```

### Excluding fragments

Skip specific fragments by output path with one or more `--exclude` glob
patterns (matched with `fnmatch` against each fragment's `path`):

```sh
cobo check --exclude '.github/*' --exclude LICENSE
```

Excluded fragments are not evaluated: they never appear in the table or JSON
and do not affect the exit code. The same `--exclude` flag is available on
`cobo sync`, where excluded fragments are left untouched in both the working
tree and `cobo.lock`.

Emits JSON to stdout:

```json
{
  "outdated_count": 1,
  "error_count": 0,
  "locally_modified_count": 0,
  "sync_blocked_count": 0,
  "fragments": [
    {
      "path": ".gitignore",
      "source": "gitignore",
      "held": false,
      "outdated": true,
      "error": null,
      "local_state": "match",
      "files": [
        {"name": "Python", "old_blob": "b3ec7d5...", "new_blob": "c4fd8e6..."}
      ]
    }
  ]
}
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All tracked fragments are up to date. |
| `1` | One or more fragments have updates available, or their on-disk block would **block `sync`** — edited locally, or with missing/broken markers (or, with `--strict`, one or more fragments errored). |
| `2` | No `cobo.lock` found or it is malformed. Run `cobo <source> dump --lock` first. |

> Fragments that cannot be evaluated (e.g. their `source` is not configured) are
> reported with an `error` status but are **not** counted as outdated — so by
> default `cobo check` can exit 0 while `error` entries are still present in the
> output. Always inspect the table (or `--json`) for `error` entries even on a
> clean exit.
>
> Pass `--strict` to make errored fragments cause a non-zero exit as well — use
> this when running `cobo check` as a CI gate where an unreachable source should
> fail the build rather than pass silently. The `--json` output always reports
> `error_count` regardless of `--strict`.

---

## Applying updates

```sh
cobo sync
```

Re-renders every outdated fragment from the current source clone, rewrites only
the fragment's **managed block** (see [Editing a managed file](#editing-a-managed-file)),
and advances its `commit` and `blob` entries in `cobo.lock`. Any content you
added outside the block is preserved. Held fragments (`update = false`) are
skipped. If one fragment fails (e.g. a source path has moved, or its block was
edited locally), the error is reported and sync continues with the rest.

To preview what would change without writing anything:

```sh
cobo sync --dry-run
```

If a fragment's managed block was hand-edited, `sync` refuses it rather than
discarding your edits. Overwrite such blocks (and rebuild files whose markers
are missing or malformed) with:

```sh
cobo sync --force
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All fragments were applied (or there was nothing to do). |
| `1` | One or more fragments **could not be evaluated or re-rendered** (e.g. an unknown or unreachable source, an unwritable output path, or a locally edited managed block — use `--force`). |
| `2` | No `cobo.lock` found. Run `cobo <source> dump --lock` first. |

> `cobo sync` does **not** exit 1 merely because updates existed — exit 1 means a
> re-render actually failed or was refused. A clean sync with changes applied
> exits 0.
>
> Unlike `cobo check` (which by default exits 0 even when `error` entries are
> present — use `cobo check --strict` to change that), `cobo sync` always treats
> un-evaluable fragments as failures so CI and the Action fail loudly.

After running `cobo sync`, commit both the updated output files and the updated
`cobo.lock`.

---

## Holding a fragment back

Set `update = false` on a fragment's `[[fragment]]` entry in `cobo.lock`:

```toml
[[fragment]]
path = "mise.toml"
source = "mise"
update = false
```

`cobo check` lists this fragment as **held** and never counts it as outdated.
`cobo sync` skips it entirely. To resume tracking, change `update` back to `true`
(or remove the field — it defaults to `true`).

---

## Editing a managed file

A tracked file (dumped with `--lock`) is split into a **cobo-owned block**,
delimited by marker comments, and free space around it. `cobo sync` regenerates
only the block; anything you write **outside** the markers is preserved verbatim.

```gitignore
# >>> cobo:begin >>>
# Generated by cobo (github.com/hasansezertasan/cobo)
# gitignore/Python@5763345 — https://raw.githubusercontent.com/…/Python.gitignore
__pycache__/
*.py[cod]
# <<< cobo:end sha256=… <<<
# --- everything below is yours; sync never touches it ---
src/**/_version.py
```

Rules:

- **Add your own rules below the `cobo:end` marker.** They survive every sync.
- **Don't edit inside the block.** The end marker carries a SHA-256 of the block;
  if you change the block, `cobo check` reports the fragment as **locally
  modified** and `cobo sync` **refuses** it (so your edit is never silently
  overwritten). Re-run with `cobo sync --force` to discard the in-block edit and
  regenerate, or move your change below the end marker.
- **Markers are comments in the file's own language** (built from the source's
  `comment_prefix`), so they never break the file.
- **One block per file.** A file with no markers, or with duplicated/garbled
  markers, is refused by `sync` until you re-dump it (`cobo <source> dump --out
  FILE --lock`) or pass `--force` (which rewrites the whole file, discarding any
  non-block content). Files dumped before markers existed fall into this case.

---

## Provenance header

When a source has `inject_header = true`, cobo prepends a two-line provenance
header to each dumped file:

```
# Generated by cobo (github.com/hasansezertasan/cobo)
# gitignore/Python@5763345 — https://raw.githubusercontent.com/github/gitignore/576334520435382d6522f349b9d270eda1e79a25/Python.gitignore
```

- **Line 1** is a fixed attribution.
- **Line 2** is `<source>/<name>@<short7>` followed by a raw URL built from the
  **full SHA** and the resolved repo-relative path. The short SHA
  (`@5763345`) is for human readability; the URL uses the full SHA to avoid
  ambiguity as the upstream repo grows. The URL is omitted for non-GitHub sources.

For `multi_dump`, one such two-line header precedes each input template's block.

---

## Automating with GitHub Actions

The `hasansezertasan/cobo` composite Action runs `cobo sync` and opens a pull
request when fragments drift. Add a consuming workflow to your repository:

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

The `actions/checkout` step must come before the cobo action. The workflow needs
`contents: write` (to push the update branch) and `pull-requests: write` (to open
the PR).

### Action inputs

| Input | Default | Description |
|---|---|---|
| `config` | _(empty)_ | Path to a cobo config TOML. Sets `COBO_CONFIG`. Optional. |
| `exclude` | _(empty)_ | Newline- or space-separated glob patterns; matching fragment paths are skipped by both `check` and `sync`. |
| `pr-title` | `"chore: update cobo fragments"` | Title for the opened pull request. |
| `pr-labels` | `"cobo"` | Comma-separated labels for the pull request. |
| `branch` | `"cobo/update-fragments"` | Branch the action pushes updates to. |
| `fail-on-sync-error` | `"false"` | When `"true"`, fail the run if any fragment failed to re-render. The PR for the fragments that did succeed is still opened first; the run fails afterward. The default isolates failures and stays green, surfacing them only in the PR body and the `sync_failed` output. |

The action uses `peter-evans/create-pull-request` under the hood, so no PR is
opened when there are no changes.

### Docker-based Action

A Docker variant lives at `hasansezertasan/cobo/docker@v1`. It runs the same
`check` + `sync` inside a container. Because a Docker action is a **single
container**, it cannot itself open a pull request; it runs the sync and exposes
outputs, leaving PR creation to your workflow:

```yaml
jobs:
  update:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - id: cobo
        uses: hasansezertasan/cobo/docker@v1
        with:
          exclude: |
            .github/*
            LICENSE
      - uses: peter-evans/create-pull-request@v7
        with:
          title: "chore: update cobo fragments"
          branch: cobo/update-fragments
          body: ${{ steps.cobo.outputs.summary }}
```

| Input | Default | Description |
|---|---|---|
| `config` | _(empty)_ | Path to a cobo config TOML. Sets `COBO_CONFIG`. Optional. |
| `exclude` | _(empty)_ | Newline- or space-separated glob patterns to skip. |

| Output | Description |
|---|---|
| `sync-failed` | `"true"` when any fragment failed to re-render, else `"false"`. |
| `summary` | A Markdown summary of the drift detected before sync (for the PR body). |

The composite Action (`hasansezertasan/cobo@v1`) remains the simplest choice
for the full drift-to-PR flow; reach for the Docker variant only when you want
to compose the steps yourself.

#### Prebuilt image

Every release publishes a prebuilt image to the GitHub Container Registry so you
can skip the per-run image build entirely (the fastest cold start). Tags track
the release: the full version (`1.2.3`), the major (`1`), and `latest`.

```
ghcr.io/hasansezertasan/cobo:1.2.3
ghcr.io/hasansezertasan/cobo:1
ghcr.io/hasansezertasan/cobo:latest
```

Reference it directly as a container step (it reads the same `INPUT_CONFIG` /
`INPUT_EXCLUDE` env vars the action passes, and writes `sync-failed` / `summary`
to `$GITHUB_OUTPUT`):

```yaml
- id: cobo
  uses: docker://ghcr.io/hasansezertasan/cobo:1
  env:
    INPUT_EXCLUDE: |
      .github/*
```

The bundled `docker/` action instead builds from its `Dockerfile` at the pinned
ref, which keeps the entrypoint and image in lockstep with the action version.

> [!NOTE]
> **First-release setup (one-time).** The first `publish-docker` run creates
> the GHCR package as **private** and **unlinked** from the repository. Until an
> owner adjusts it, `docker://ghcr.io/hasansezertasan/cobo:…` pulls require
> authentication. After the first release, in the package settings
> (**repo → Packages → cobo → Package settings**):
>
> - set the visibility to **public**, and
> - **link** the package to this repository (Manage Actions access) so it
>   inherits the repo's permissions.
>
> This is only needed once; later releases reuse the existing package.
