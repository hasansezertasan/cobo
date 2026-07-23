#!/usr/bin/env bash
# Entrypoint for the cobo Docker action: capture drift, sync, emit outputs.
#
# A Docker action is a single container and cannot itself open a pull request,
# so this script runs check+sync and exposes `sync-failed` and `summary`
# outputs; the consuming workflow composes the PR step (see docs). A sync
# failure does not abort this script (a partial update still opens a PR) — it is
# reported via the `sync-failed` output, which the caller should gate on.
set -uo pipefail

export COBO_CONFIG="${INPUT_CONFIG:-}"

# Turn newline/space-separated exclude patterns into repeated --exclude flags.
read -ra patterns <<<"${INPUT_EXCLUDE:-}"
exclude=()
# `${arr[@]+"${arr[@]}"}` expands to nothing on an empty array, avoiding an
# `unbound variable` abort under `set -u` on bash < 4.4 (the default exclude is
# empty, and the slim base image may not ship a recent bash).
for pattern in "${patterns[@]+"${patterns[@]}"}"; do
  exclude+=(--exclude "$pattern")
done

# Capture the drift that motivates the update *before* sync advances the lock.
# Write to a temp file OUTSIDE the workspace so a repo file named
# `cobo-check.json` is never clobbered.
report="$(mktemp "${RUNNER_TEMP:-/tmp}/cobo-check.XXXXXX.json")"
# `check` exits 1 on drift (expected) so that is tolerated, but exit >=2 means a
# real config error (no/invalid lockfile) — surface it instead of emitting an
# empty drift block.
check_rc=0
cobo check --json "${exclude[@]}" >"$report" || check_rc=$?
if [ "$check_rc" -ge 2 ]; then
  cat "$report" >&2 || true
  exit "$check_rc"
fi

if cobo sync "${exclude[@]}"; then
  sync_failed=false
else
  sync_failed=true
fi

echo "sync-failed=$sync_failed" >>"$GITHUB_OUTPUT"

{
  echo "summary<<COBO_EOF"
  echo "Automated cobo fragment update."
  echo
  if [ "$sync_failed" = "true" ]; then
    echo "> [!WARNING]"
    echo "> Some fragments failed to re-render. See the workflow log."
    echo
  fi
  echo "Drift detected before sync:"
  echo '```json'
  if [ -f "$report" ]; then
    cat "$report"
  else
    echo '(no drift report produced)'
  fi
  echo '```'
  echo "COBO_EOF"
} >>"$GITHUB_OUTPUT"

rm -f "$report"
