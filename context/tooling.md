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
**Revisit when:** ruff's preview rules stabilize or the pinned version catches up

prek installs a newer ruff than the pinned one, and with `preview = true` and `select = ["ALL"]` these two rules rewrite every `# noqa:` comment into the new syntax repo-wide. Opting them out works on both versions (the pinned one only warns "unknown selector").

**Rejected alternative:** chasing the ruff version, which the journal calls a treadmill (0.16 already adds RUF201).
