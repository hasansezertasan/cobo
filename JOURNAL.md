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
