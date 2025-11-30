#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/voicer-platform"
VENV_DIR="$PROJECT_DIR/voicer-env"
SERVICE_VOICER_PREV="voicer-prev.service"
SERVICE_VOICER_API="voicer-api.service"   # example second service

cd "$PROJECT_DIR"

echo "=== Deploy starting in $PROJECT_DIR ==="

# -----------------------------
# 1. Remember previous commit
# -----------------------------
PREV_COMMIT_FILE=".last_deploy_commit"
PREV_COMMIT=""
if [ -f "$PREV_COMMIT_FILE" ]; then
  PREV_COMMIT="$(cat "$PREV_COMMIT_FILE")"
fi

# -----------------------------
# 2. Pull latest code
# -----------------------------
echo "-> Updating code (git pull)..."
git fetch --all
git pull --rebase

CURRENT_COMMIT="$(git rev-parse HEAD)"
echo "Previous commit: ${PREV_COMMIT:-<none>}"
echo "Current commit : $CURRENT_COMMIT"

# If no previous commit recorded, treat as "everything changed"
if [ -z "$PREV_COMMIT" ]; then
  echo "No previous deploy detected. Assuming all services need restart."
  CHANGED_FILES=$(git ls-files)  # everything
else
  CHANGED_FILES=$(git diff --name-only "$PREV_COMMIT" "$CURRENT_COMMIT")
fi

echo "Changed files since last deploy:"
echo "$CHANGED_FILES"
echo

# -----------------------------
# 3. Decide which services changed
# -----------------------------
NEED_RESTART_VOICER_PREV=false
NEED_RESTART_VOICER_API=false

# Adjust these path prefixes to match your actual project layout
if echo "$CHANGED_FILES" | grep -qE '^app/|^tts/|^voicer/|^requirements\.txt'; then
  NEED_RESTART_VOICER_PREV=true
fi

if echo "$CHANGED_FILES" | grep -qE '^api/|^backend/'; then
  NEED_RESTART_VOICER_API=true
fi

# If nothing changed (e.g. you re-ran deploy by accident)
if [ -z "$CHANGED_FILES" ]; then
  echo "No files changed since last deploy. Nothing to restart."
  # Still update the last deploy commit
  echo "$CURRENT_COMMIT" > "$PREV_COMMIT_FILE"
  exit 0
fi

# -----------------------------
# 4. Install dependencies if needed
# -----------------------------
if [ ! -d "$VENV_DIR" ]; then
  echo "-> Creating virtualenv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

echo "-> Installing dependencies..."
source "$VENV_DIR/bin/activate"
if echo "$CHANGED_FILES" | grep -q 'requirements.txt'; then
  echo "requirements.txt changed, running pip install -r requirements.txt"
  pip install -r requirements.txt
else
  echo "requirements.txt unchanged, skipping pip install."
fi

# -----------------------------
# 5. Reload systemd units
# -----------------------------
echo "-> Reloading systemd (daemon-reload)..."
sudo systemctl daemon-reload

# -----------------------------
# 6. Restart only affected services
# -----------------------------
if $NEED_RESTART_VOICER_PREV; then
  echo "-> Restarting $SERVICE_VOICER_PREV (code changed)..."
  sudo systemctl restart "$SERVICE_VOICER_PREV"
  sudo systemctl status "$SERVICE_VOICER_PREV" --no-pager -l || {
    echo "!! $SERVICE_VOICER_PREV failed to start. Check logs with:"
    echo "   journalctl -u $SERVICE_VOICER_PREV -n 50 --no-pager"
    exit 1
  }
else
  echo "-> Not restarting $SERVICE_VOICER_PREV (no relevant changes)."
fi

if $NEED_RESTART_VOICER_API; then
  echo "-> Restarting $SERVICE_VOICER_API (code changed)..."
  sudo systemctl restart "$SERVICE_VOICER_API"
  sudo systemctl status "$SERVICE_VOICER_API" --no-pager -l || {
    echo "!! $SERVICE_VOICER_API failed to start. Check logs with:"
    echo "   journalctl -u $SERVICE_VOICER_API -n 50 --no-pager"
    exit 1
  }
else
  echo "-> Not restarting $SERVICE_VOICER_API (no relevant changes)."
fi

# -----------------------------
# 7. Save current commit as last deploy
# -----------------------------
echo "$CURRENT_COMMIT" > "$PREV_COMMIT_FILE"

echo "✅ Deploy finished. Updated to commit $CURRENT_COMMIT."


