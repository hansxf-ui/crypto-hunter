#!/usr/bin/env bash
# Crypto Hunter hourly scan wrapper.
# Runs the scanner, then pushes data/ to GitHub ONLY when the scan reports
# CHANGED. Always exits 0 so a failing scan never spams cron error mail.
#
# NOTE: the GitHub repo hansxf-ui/crypto-hunter is created in Task 7.
# Until then this script scans and skips the push with a clear message.
set -euo pipefail

REPO="/home/hatch/workspace/crypto-hunter"
GH_PUSH="/home/hatch/workspace/skills/github/bin/gh-push"
GH_API="/home/hatch/workspace/skills/github/bin/gh-api"
GH_REPO="hansxf-ui/crypto-hunter"
export https_proxy="http://hatch-egress-proxy:3128"
export http_proxy="http://hatch-egress-proxy:3128"

log() { echo "crypto-hunter: $*"; }

# Optional secrets: /home/hatch/.config/crypto-hunter/env (0600) may export
# CRYPTORANK_API_KEY. Sourced only if it exists; never committed to the repo.
ENV_FILE="/home/hatch/.config/crypto-hunter/env"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

cd "$REPO"

if ! OUTPUT="$(python3 scan/hunter.py 2>&1)"; then
  log "hunter failed - skipping push"
  echo "$OUTPUT"
  exit 0
fi
echo "$OUTPUT"

# gh-push does not respect .gitignore: drop bytecode before any push.
find "$REPO" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# Defensive: no repo yet (created in Task 7) -> scan only, no push.
if ! "$GH_API" GET "/repos/${GH_REPO}" >/dev/null 2>&1; then
  log "repo ${GH_REPO} not reachable yet - skipping push"
  exit 0
fi

# Whole-line match: "UNCHANGED" contains "CHANGED" as a substring.
if echo "$OUTPUT" | grep -qx "CHANGED"; then
  log "changes detected - pushing data/"
  if "$GH_PUSH" "$GH_REPO" "$REPO/data" --branch main --prefix data \
      --message "crypto-hunter: hourly scan $(date -u +%Y-%m-%dT%H:%MZ)"; then
    log "push ok"
  else
    log "push failed - will retry next hour"
  fi
else
  log "no changes - skipping push"
fi
exit 0
