# Paths

## Single `~/.cobo` root instead of platformdirs

**Id:** 97a368ec-e0ec-4760-a7b8-ec8bea9248f2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's development journal (`docs/JOURNAL.md`, 2026-08-13 entry); commit `a24715d` (#150)
**Verification:** corroborated
**Revisit when:** a 1.0 release or a request for XDG-conformant locations

Config (`config.toml`) and cached clones (`sources/<name>`) live under one `~/.cobo/` folder; the `platformdirs` runtime dependency is gone. The public `paths.py` API is unchanged.

**Reason:** the simpler single-root model of the sibling ocom project.

**Rejected alternatives:**
- Porting ocom's unresolvable-`HOME` fallback machinery (`None` plus temp dir): YAGNI, cobo has no startup file-logging that must degrade gracefully. If `HOME` cannot be resolved, `Path.home()` raises, as before.
- A `~/.config/cobo` → `~/.cobo` migration shim: skipped because the project is pre-1.0. Users are told through a `BREAKING CHANGE:` commit footer in `CHANGELOG.md`; cached clones re-fetch on next use.
