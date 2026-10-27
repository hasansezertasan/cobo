# Managed blocks

## Managed-region markers protect hand-edits in cobo-managed files

**Id:** 12281582-c25c-4139-92b6-bf9874d9c479
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's development journal (`docs/JOURNAL.md`, 2026-07-22 managed-region entry); implementation in #55
**Verification:** corroborated
**Revisit when:** a second managed block per file is needed (format v2), or the marker format changes. The markers live in users' files, so the format is a contract.

`cobo sync` regenerates only the block between `cobo:begin` and `cobo:end sha256=<hash>` markers and preserves everything outside verbatim, as long as the existing markers parse. If they are missing, duplicated or malformed, or the block no longer matches its hash, `sync` refuses and `check` reports it as locally modified. `--force` overrides, but a rebuild over unusable markers starts from scratch and discards all previous content, including anything kept outside the old block. A plain `dump --out` stays marker-free; markers come from `dump --lock` and from `sync`, which also creates them when a tracked output is absent.

**Reason:** the lockfile tracks upstream input provenance, not output integrity. Before the markers, `sync` fully overwrote the output, so a hand-edited tail was silently destroyed whenever upstream drifted. Found while dogfooding cobo on its own `.gitignore`.

**Rejected alternatives:**
- A single end-marker: cannot detect tampering above the boundary.
- Echoing the provenance header in the footer: redundant, since the header already carries it. The hash alone covers delimiting and integrity.
- Multiple named blocks per file: out of scope for now. One file is one fragment is one block.
- Overwriting when markers are absent: refused because cobo cannot know which bytes are the user's. The journal calls this non-negotiable, since without it the feature would only relocate the clobber hazard.

## Lock discovery stops at the repository root

**Id:** 09eb9cbc-5502-43f6-a38f-d04caf0f4c0f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's development journal (`docs/JOURNAL.md`, 2026-07-22 post-review entry)
**Verification:** corroborated

`find_lock` walks up from the working directory only to the first directory with `.git` (as cargo and uv do), and `--lock-file` / `COBO_LOCK` override discovery.

**Reason:** a fragment's `path` is relative to the lockfile's directory and cannot contain `..`, so the lock must sit at or above its outputs.

**Rejected alternative:** probing candidate locations such as `.config/cobo.lock`; bounding the walk was judged better. Before this, the walk had no boundary and ran to the filesystem root.
