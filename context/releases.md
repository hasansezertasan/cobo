# Releases

## Version derived from the git tag (hatch-vcs), not a committed literal

**Id:** 54df0be4-87cc-4eb7-9b91-ceb430ee129d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's development journal (`docs/JOURNAL.md`, 2026-06-20 and 2026-06-23 entries); commit `2cb333b`
**Verification:** corroborated
**Revisit when:** the release tooling changes (release-please or hatch-vcs replaced), or tags stop being created before the build

The package version comes from the git tag at build time (hatch-vcs, generated `_version.py`); release-please owns only the tag and `CHANGELOG.md`. `pyproject.toml` carries `dynamic = ["version"]`.

**Reason:** a committed version literal is a second source of truth that can drift from the tag, and it forces release-please to rewrite files in lock-step. One authority (the tag) is also what the sibling projects settled on.

**Rejected alternative:** a static, release-please-owned version (`__version__` literal plus a `pyproject.toml` marker line). It was adopted three days earlier (2026-06-20) and reversed in #45 for the reason above.

**Consequence:** the build needs the tag to exist before the draft release is published, which is why `release-please-config.json` sets `force-tag-creation: true`.

## Release workflow split into single-responsibility jobs

**Id:** 98432e18-3bff-48c5-8d78-f88604833801
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's development journal (`docs/JOURNAL.md`, 2026-07-23 split entry)
**Verification:** corroborated
**Revisit when:** the release workflow is restructured, or the publishing mechanism changes

`.github/workflows/release.yml` is a chain of jobs: build (producer only) → `publish-pypi` → release un-draft and Docker publish in parallel → reconcile. Only `publish-pypi` holds `id-token: write` and the `publish` environment.

**Reason:** tighter permission scoping — OIDC and the publishing environment are reachable from a single job. Shape adopted from the sibling keycast project.

**Rejected alternative:** the earlier monolithic `publish` job in `release-please.yml`: no reason to reject it beyond the permission scoping is recorded.

## PyPI trusted publisher is keyed on the workflow filename

**Id:** 55070587-c06d-4b7a-b222-6a72267da446
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's development journal (`docs/JOURNAL.md`, 2026-07-23 follow-ups)
**Verification:** corroborated
**Revisit when:** the publishing authentication moves away from PyPI trusted publishing

PyPI's trusted-publisher identity is tied to the workflow *filename* (`release.yml`, environment `publish`). Renaming the workflow without updating PyPI leaves `uv publish --trusted-publishing always` unable to authenticate, and every release stalls as an unpublished draft. The PyPI-side setting is outside the repository, so the code cannot show it.
