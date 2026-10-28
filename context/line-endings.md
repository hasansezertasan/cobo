# Line endings

## `--eol` seals upstream bytes exactly by default; `lf` rewrites line terminators only

**Id:** 88315d17-55c9-4d69-85b2-65b6feed7866
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** issues #120 and #124; PRs #121 and #226; maintainer interview, 2026-10-28
**Verification:** corroborated
**Revisit when:** the `--eol` option is removed or its default changes

cobo seals a managed block's bytes verbatim, including upstream CRs such as the macOS `Icon[\r]` line. Consumers that enforce LF (copier's Jinja renderer, git `eol=lf`, EditorConfig) rewrite those bytes, and the block then no longer matches its sealed hash, so `cobo check` reports it as locally modified permanently. `--eol lf` normalizes line terminators (`\r\n`, a CR run before LF, a trailing CR) before sealing so the seal survives such consumers. `preserve` stays the default and the choice is recorded on the lock fragment.

**Reason for `lf` keeping lone CRs:** in `Icon[\r]` the CR is a gitignore character-class byte, not a line ending. The first version turned every CR into LF, which split the pattern into `Icon[` and `]` and stopped the macOS icon file being ignored (#124, fixed in #226).

**Reason for `preserve` as the default:** the issue states it as non-breaking, so existing locks and seals stay byte-identical. Whether `lf` as the default was weighed is unknown.

**Rejected alternative:** none recorded for the default itself.

**See:** managed-blocks.md#a-sealed-block-is-never-rewritten-to-survive-a-renderer — 0c0e0cba-a41c-4aaf-aded-76fda373a076 — as of 2026-10-28
