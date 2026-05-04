#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=".venv"
APP="greek.py"
PID_FILE="bot.pid"
LOG_FILE="bot.log"

if [[ ! -f "$APP" ]]; then
  echo "Error: $APP not found"
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

echo "Installing/updating dependencies..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install \
  aiogram \
  aiosqlite \
  aiohttp \
  html2text \
  python-dotenv

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"

  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Bot is already running with PID $OLD_PID"
    exit 0
  else
    echo "Removing stale PID file"
    rm -f "$PID_FILE"
  fi
fi

echo "Starting bot in background..."

nohup "$VENV_DIR/bin/python" "$APP" >> "$LOG_FILE" 2>&1 &
BOT_PID=$!

echo "$BOT_PID" > "$PID_FILE"

echo "Bot started with PID $BOT_PID"
echo "Logs: $LOG_FILE"
echo "Stop with: ./stop.sh"
