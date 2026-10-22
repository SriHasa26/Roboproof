#!/bin/sh
# Poll the FAST model with a tiny chat call until it answers (or give up). Prints status and timing only, never the key.
# Usage: scripts/wait_for_fast_model.sh [attempts] [seconds_between]
ROOT=$(dirname "$0")/..
KEY=$(grep -E '^NEBIUS_API_KEY=' "$ROOT/.env" | head -1 | cut -d= -f2-)
MODEL=$(grep -E '^NEBIUS_MODEL_FAST=' "$ROOT/.env" | head -1 | cut -d= -f2-)
N=${1:-10}; GAP=${2:-60}; i=1
while [ "$i" -le "$N" ]; do
  OUT=$(curl -s -o /dev/null -w "HTTP %{http_code} first_byte=%{time_starttransfer}s total=%{time_total}s" --max-time 40 -X POST https://api.tokenfactory.nebius.com/v1/chat/completions \
    -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":20}")
  echo "$(date +%H:%M:%S) attempt $i/$N fast model: $OUT"
  case "$OUT" in "HTTP 200"*) echo "FAST MODEL RECOVERED"; exit 0;; esac
  i=$((i+1)); [ "$i" -le "$N" ] && sleep "$GAP"
done
echo "FAST MODEL STILL DOWN after $N attempts"; exit 1
