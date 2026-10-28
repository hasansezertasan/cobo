# Lockfile

## `cobo.lock` is the source of truth, with a blob SHA as the drift key

**Id:** cea28885-cfcc-4f08-96c0-590787b86bf9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** design spec (`docs/superpowers/specs/2026-06-23-fragment-updates-design.md`); maintainer interview, 2026-10-28; PR #55
**Verification:** corroborated
**Revisit when:** cobo stops using shallow (depth-1) clones, or a source without a lockfile-friendly layout is added

Each `--lock` dump records, per input file, its resolved repo-relative path, the full commit SHA (used for the header URL) and a blob SHA. `cobo check` compares recorded blob SHAs against the live upstream ones; the lockfile, not the output files' headers, says which files cobo tracks.

**Reason:** the lockfile handles one output built from several origins (`multi_dump`) and sources that carry no header at all, which a header scanner cannot see. The blob SHA (`git rev-parse HEAD:<path>`) is content-addressed, works on a shallow clone, and changes exactly when the file's content changes.

**Rejected alternatives:**
- Scraping provenance back out of file headers: blind to multi-origin outputs and headerless sources.
- Comparing commit history (`git log -- path`): cobo's clones are shallow, and the comparison would flag every file whenever the branch HEAD moves.
