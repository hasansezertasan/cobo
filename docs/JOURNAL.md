# Development Journal

Chronological record of decisions, attempts (including failures), and outcomes for the cobo project.

---

## 2026-06-20 — Adopt release-please pipeline (follow olink/ocom)

### Context
Adopted the release pipeline from the sibling projects [olink](https://github.com/hasansezertasan/olink/pull/14) and [ocom](https://github.com/hasansezertasan/ocom), replacing the release-drafter + manual-publish (`cd.yml`) flow. cobo had no PyPI release and no git tags, so this was effectively first-time release setup — a clean moment to swap strategies.

### Decisions

- **release-drafter → release-please**: removed `.github/workflows/release-drafter.yml`, `.github/release-drafter.yml`, and `.github/workflows/cd.yml`; added `.github/workflows/release-please.yml` plus `release-please-config.json` and `.release-please-manifest.json`. Releases are now driven by conventional commits: release-please maintains a Release PR; merging it tags, builds, publishes to PyPI, and un-drafts the GitHub release in one automated path. No more manual "publish the draft" step.
- **Dropped hatch-vcs for a static, release-please-owned version**: `release-type: python` bumps `__version__` in `src/cobo/__init__.py`, and `extra-files: [{ type: generic, path: pyproject.toml }]` rewrites the `version = "x.y.z" # x-release-please-version` line. Removed `[tool.hatch.version]`, the `hatch-vcs` build requirement, the `_version.py` file hook, and the dead `_version.py` coverage `omit`. `src/cobo/globals.py` now reads `cobo.__version__` directly instead of `importlib.metadata.version("cobo")`, making the committed literal the single source of truth.
- **Seeded at `0.0.0` so the first *published* release is `0.1.0`**: `pyproject.toml`, `src/cobo/__init__.py`, and `.release-please-manifest.json` all start at `0.0.0`. release-please bumps `feat` → minor, so `0.0.0` + the existing `feat` history yields `0.1.0`. No `bump-minor-pre-major` flag needed.
- **Kept `check-pr-title.yml`**: it lints PR titles and is complementary to release-please (commit messages remain the release source of truth).

### Follow-ups (manual, outside the repo)
- Configure the PyPI Trusted Publisher for `cobo`: workflow `release-please.yml`, environment `publish`.
- Ensure a GitHub Environment named `publish` exists (the publish job references it).

---

## 2026-07-22 — Managed-region markers to protect user edits in cobo-managed files

### Context

Surfaced while trying to dogfood cobo on its own `.gitignore` (to get real
`cobo check`/`sync` coverage on a runner). The attempt exposed a design gap, not
a one-off snag.

**The lockfile tracks input provenance, not output integrity.** `cobo check`
reads only the *upstream* input-template blob SHAs (`gather_current_blobs` in
`src/cobo/commands/check.py` calls `blob_sha_for_path(clone_root, file.path)`,
where `clone_root` is the source clone) and compares them to `cobo.lock`. The
local output file is never read. `cobo sync` then regenerates purely from the
current upstream templates and does a **full overwrite** of the output
(`(lock_dir / frag.path).write_bytes(content)` in `src/cobo/commands/sync.py`).

That produces a silent lost-update hazard whenever a user hand-edits a managed
file. Two cases:

- **Case 1 — user edits the tail, upstream unchanged.** `check` compares
  upstream blobs to the lock → reports **"up to date"**; the local edit is
  invisible (cobo has no idea the file diverged from what it would generate).
  `sync` sees the fragment is not outdated → never re-renders → the edit
  survives, but only *incidentally* because nothing triggered a rewrite.
- **Case 2 — user edits the tail, and upstream drifts.** `check` sees an
  upstream blob ≠ the locked blob → reports **"outdated"**. `sync` re-renders
  from the current templates and full-overwrites the file → the custom tail
  (and any hand-edits to the template portion) are **silently destroyed** — no
  diff, no prompt, no `.orig` backup.

Concrete trigger: cobo's own `.gitignore` ends with a hand-authored section
(`src/**/_version.py`, `PyPI.md`, `mise.local.toml`) that a re-dump dropped.
This is why the file cannot be cleanly cobo-managed today.

### Decision

Add **managed-region markers**: cobo owns a delimited block; the user owns
everything outside it. `sync` regenerates only the managed block and preserves
the rest verbatim. **Implemented in this PR (#55)** rather than deferred — the
lost-update hazard is introduced by the same PR that adds `check`/`sync`, so it
is fixed alongside it.

This is a well-worn pattern, not a novel design: Ansible's `blockinfile`
(`# BEGIN ANSIBLE MANAGED BLOCK` … `# END ANSIBLE MANAGED BLOCK`), chezmoi, and
countless dotfile managers all delimit a tool-owned region with markers. We
borrow the prior art rather than design cold.

### Design decisions

- **BEGIN/END marker pair**, not a single end-marker. Since cobo always writes
  its provenance header at the top, the managed region is the file's prefix; but
  a pair is still preferred because it lets cobo detect tampering *above* the
  boundary, which a lone end-marker cannot.
- **Markers are comments in the target file's language**, built from each
  source's existing `comment_prefix` (see `src/cobo/config/defaults.py`), so the
  output stays valid. File layout:

  ```
  <provenance header>          ┐
  # >>> cobo:begin >>>         │
  <rendered templates>         ├─ cobo-owned (regenerated by sync)
  # <<< cobo:end sha256=… <<<  ┘  ← boundary, carries region hash
  src/**/_version.py           ┐
  PyPI.md                      ├─ user-owned (preserved verbatim)
  mise.local.toml              ┘
  ```

- **The END marker carries a hash of the managed region** (not a full echo of
  the header). This folds output-integrity detection into the marker itself:
  cobo can tell whether its own block was hand-edited. Duplicating the header's
  per-input provenance (filename, repo URL, per-input SHAs) into the footer was
  considered and rejected as redundant — the top header already carries it; the
  footer's only new job is delimiting + integrity, and the hash covers both.
- **Marker-missing / ambiguous is a hard stop, never a clobber.** If a
  `--lock` fragment expects markers but they are absent (old pre-marker dump,
  user deleted the line) or duplicated, `sync` **refuses and warns** instead of
  overwriting — because cobo cannot know which bytes are the user's. This is the
  minimal slice of output-integrity safety needed to make the feature safe, and
  is non-negotiable: without it the feature merely relocates the silent-clobber
  hazard rather than removing it.
- **`sync` flow:** read the existing output, locate the BEGIN/END pair,
  regenerate only the managed region, re-attach everything outside verbatim.
- **`check` is unchanged** in its drift model (still upstream-provenance based);
  it may additionally warn when the managed-region hash no longer matches.

### Locked contract (2026-07-22)

Wire format settled before implementation (the markers are permanent in users'
files, so the format is a contract):

- **Sentinels (angle-bracket style):**
  - Begin: `<comment_prefix> >>> cobo:begin >>>`
  - End: `<comment_prefix> <<< cobo:end sha256=<64-hex> <<<`
  where `<comment_prefix>` is the source's configured prefix (e.g. `#`).
- **Header inside the block.** The whole cobo-owned region — provenance header
  plus all rendered input templates — sits between the two markers. Rule:
  *everything between the markers is regenerated; everything outside is the
  user's and preserved verbatim.*
- **One block per file.** `fragment.path` is the output primary key, so one
  file = one fragment = one managed block. A second `cobo:begin` in the same
  file is corruption, not a second block (see refuse rule below). Multiple
  input templates render as multiple header+body sections *inside the single
  block*; multiple tracked files each get their own independent block/hash.
  (Named markers for multi-block-per-file are a possible format v2, explicitly
  out of scope now.)
- **Hash = full SHA-256 (64 hex)** of the exact managed-region bytes cobo
  writes between the marker lines. Compared by exact match (not resolved like a
  git ref), consistent with the PR's no-abbreviated-hash stance.
- **On local edit inside the block (hash mismatch):** `sync` **refuses + warns**
  and does not overwrite; `--force` opts into regenerating anyway; `check`
  reports it as a distinct `locally modified` status so it is visible before any
  sync. (This is the point where `check` gains awareness of the output file, not
  just upstream provenance.)
- **Markers emitted only with `--lock`.** A plain `--out` dump is not
  sync-managed and stays marker-free, as today.
- **Absent or duplicated markers on a tracked file:** `sync` refuses + warns
  (cannot tell which bytes are the user's), with a hint to re-dump or
  `cobo lock import`. Those two paths write markers for pre-marker files.

### Open questions (deferred to implementation)

- Exact byte boundary the hash covers (whether it includes the header's leading
  newline / the block's trailing newline) — will be fixed by hashing precisely
  what cobo writes, and pinned by a round-trip test.

### Implementation (built in this PR)

- New `src/cobo/sources/managed.py`: `wrap` (build block + hash), `parse`
  (split head/body/tail, raise on missing/malformed), `classify` (→ `BlockState`
  for `check`), `weave` (regenerate block, preserve user content, refuse on
  tamper/missing unless `force`). Hash covers the normalized body between the
  markers (trailing newlines collapsed to one), so round-trips are stable.
- `ManagedBlockError(UserError)` added to `errors.py`; a sync refusal becomes a
  per-fragment `FailedFragment` (exit 1) rather than a clobber.
- `dump --lock` now wraps output and preserves an existing managed file's tail
  on re-dump; `sync` gained `--force`; `check` reads each output file and reports
  `local_state` (match/modified/missing/malformed/absent), with a
  `locally_modified_count` that drives exit 1 and a `local_state` field in JSON.
- Tests: `tests/unit/test_managed.py` (wrap/parse/classify/weave) plus
  integration coverage for tail preservation, tamper refusal + `--force`, missing
  markers, re-dump preservation, and `check` reporting. managed.py / sync.py /
  check.py at 100%; suite 239 tests, 99% total.

---
