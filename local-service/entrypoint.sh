#!/usr/bin/env bash
set -euo pipefail

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

# Give cloudflared a moment to bind
sleep 2

# Start uvicorn in foreground
exec uvicorn main:app --host 0.0.0.0 --port 8000
