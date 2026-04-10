#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  kill "$CLOUDFLARED_PID" 2>/dev/null || true
  wait "$CLOUDFLARED_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Start cloudflared tunnel in background
cloudflared tunnel --url http://localhost:8000 --no-autoupdate 2>&1 | \
  while IFS= read -r line; do
    echo "[cloudflared] $line"
    # Print the tunnel URL prominently when it appears
    if echo "$line" | grep -q 'https://.*trycloudflare.com'; then
      URL=$(echo "$line" | grep -oE 'https://[^ ]*trycloudflare.com[^ ]*')
      echo ""
      echo "=============================================="
      echo "  TUNNEL URL: $URL"
      echo "=============================================="
      echo ""
      echo "Update these with the URL above:"
      echo "  1. GitHub Actions variable: LOCAL_SERVICE_URL"
      echo "  2. Slack App > Event Subscriptions > Request URL:"
      echo "     ${URL}/slack/events"
      echo ""
    fi
  done &
CLOUDFLARED_PID=$!

# Start uvicorn in foreground
exec uvicorn main:app --host 0.0.0.0 --port 8000
