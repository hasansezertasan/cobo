#!/usr/bin/env bash
# Entrypoint for the cobo Docker action: capture drift, sync, emit outputs.
#
# A Docker action is a single container and cannot itself open a pull request,
# so this script runs check+sync and exposes `sync-failed` and `summary`
# outputs; the consuming workflow composes the PR step (see docs).
set -uo pipefail

export COBO_CONFIG="${INPUT_CONFIG:-}"

# Turn newline/space-separated exclude patterns into repeated --exclude flags.
read -ra patterns <<<"${INPUT_EXCLUDE:-}"
exclude=()
for pattern in "${patterns[@]}"; do
  exclude+=(--exclude "$pattern")
done

# Capture the drift that motivates the update *before* sync advances the lock.
cobo check --json "${exclude[@]}" >cobo-check.json || true

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
  cat cobo-check.json
  echo '```'
  echo "COBO_EOF"
} >>"$GITHUB_OUTPUT"

rm -f cobo-check.json
