#!/usr/bin/env bash
set -euo pipefail

PID_FILE="bot.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Bot is not running: $PID_FILE not found"
  exit 0
fi

PID="$(cat "$PID_FILE")"

if ! kill -0 "$PID" 2>/dev/null; then
  echo "Bot process $PID is not running"
  rm -f "$PID_FILE"
  exit 0
fi

echo "Stopping bot with PID $PID..."

kill "$PID"

for i in {1..10}; do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "Bot stopped"
    rm -f "$PID_FILE"
    exit 0
  fi

  sleep 1
done

echo "Bot did not stop gracefully, killing..."
kill -9 "$PID" 2>/dev/null || true
rm -f "$PID_FILE"

echo "Bot killed"
