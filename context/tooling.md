# Tooling

## Pytest basetemp must stay outside the repository

**Id:** 82dad4df-3ed6-4444-8ded-ef7b7187469e
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's development journal (`docs/JOURNAL.md`, 2026-07-23 dogfood entry); comment in `pyproject.toml` (tox config)
**Verification:** corroborated

tox does not pin pytest's `--basetemp` under the repo. With the committed `cobo.lock` at the repo root, a `tmp_path` inside the repo made `find_lock` discover it, and the "no lockfile found" tests failed under tox while passing under bare `pytest`. A comment on `env_run_base` warns against re-pinning it.

## prek's trailing-whitespace hook skips `.gitignore`

**Id:** 4d6c7e28-d1cb-4b9d-b129-312c7b037870
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's development journal (`docs/JOURNAL.md`, 2026-07-23 dogfood entry); comment in `prek.toml`
**Verification:** corroborated
**Revisit when:** the upstream templates lose their trailing spaces, or `.gitignore` stops being cobo-managed

The `.gitignore` managed block must stay byte-identical to the upstream templates, which carry trailing spaces. Stripping them would flip `cobo check` to MODIFIED on the first commit.

## Ruff preview rules RUF105 and RUF106 are opted out

**Id:** 95b3360e-9e06-4b61-81b1-41543abf7714
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's development journal (`docs/JOURNAL.md`, 2026-07-22 post-review entry); comment in `pyproject.toml`
**Verification:** corroborated
**Revisit when:** RUF105 and RUF106 stabilize, or the project decides to adopt the `# ruff:ignore[...]` syntax

With `preview = true` and `select = ["ALL"]`, these two preview rules rewrite every `# noqa: CODE` comment into the newer `# ruff:ignore[rule-name]` syntax repo-wide. They stay opted out in `pyproject.toml` until that syntax stabilizes, rather than churning every suppression across the codebase.

**History:** when this was introduced (2026-07-22) the prek ruff hook ran a newer version than the pinned one, and the opt-out was also what kept both versions consistent. The pin has since moved to a ruff that knows these rules, so that compatibility reason no longer applies; the preview-churn reason above is the current one.

**Rejected alternative:** chasing the ruff version, which the journal calls a treadmill.
