# Scope

## cobo is a generic fetcher, and micoo was left untouched

**Id:** 70e41345-f980-474b-8d9f-b0ae8a58bc17
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer interview, 2026-10-28; `README.md`
**Verification:** corroborated

cobo is a generic boilerplate fetcher: mise cookbooks, gitignore templates and any source a user configures. It succeeds `micoo`, which only handled `mise.toml` files and is deprecated and no longer maintained.

**Reason:** a generic tool was the goal, and micoo had a defined purpose that its users relied on.

**Rejected alternative:** evolving micoo into the generic tool. Widening it would have risked breaking what it already did for its narrower purpose, so a new project took over and micoo was deprecated.
