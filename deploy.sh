#!/bin/bash

set -e

### CONFIG ###########################################################

APP_DIR="/opt/voicer-platform"
ENV_PATH="/home/ubuntu/miniconda3/envs/voicer-env"
PYTHON_PATH="$ENV_PATH/bin/python"
PIP_PATH="$ENV_PATH/bin/pip"

# All services in the platform
ALL_SERVICES=(
    "voicer-main"
    "voicer-ar"
    "voicer-stats"
    "voicer-anno"
    "voicer-prev"
)

LAST_DEPLOY_FILE="$APP_DIR/.last_deploy_commit"

######################################################################

echo "🚀 Starting Voicer platform deployment..."
cd "$APP_DIR"

### 0. Process arguments ##############################################

FORCE=false
SERVICES=()

if [ "$#" -gt 0 ]; then
    if [ "$1" = "f" ]; then
        FORCE=true
        shift
    fi
    if [ "$#" -gt 0 ]; then
        SERVICES=("$@")
        echo "🧩 Services selected: ${SERVICES[*]}"
    fi
fi

if [ "${#SERVICES[@]}" -eq 0 ]; then
    SERVICES=("${ALL_SERVICES[@]}")
    echo "🧩 No services specified → deploying ALL: ${SERVICES[*]}"
fi

echo "🔧 Force mode: $FORCE"
echo

### 1. Detect previous commit ########################################

if git rev-parse HEAD >/dev/null 2>&1; then
    PREV_COMMIT="$(git rev-parse HEAD)"
else
    PREV_COMMIT=""
fi

echo "🔎 Previous commit: ${PREV_COMMIT:-<none>}"

### 2. Pull latest code ###############################################

echo "📥 Pulling latest code from GitHub..."
git fetch --all
git reset --hard origin/main

CURRENT_COMMIT="$(git rev-parse HEAD)"
echo "🧾 Current commit: $CURRENT_COMMIT"

### 3. Change detection ################################################

if [ "$FORCE" = false ]; then
    if [ -n "$PREV_COMMIT" ] && [ "$PREV_COMMIT" = "$CURRENT_COMMIT" ]; then
        echo "⚠️ No new commits AND not using force mode."
        echo "⏭️ Skipping deploy & restart."
        echo "$CURRENT_COMMIT" > "$LAST_DEPLOY_FILE"
        exit 0
    fi
    echo "🆕 Code changed → continuing deploy."
else
    echo "⚠️ FORCE MODE ENABLED → restarting selected services even without code changes."
fi

### 3.5 List changed files ############################################

if [ -n "$PREV_COMMIT" ] && [ "$PREV_COMMIT" != "$CURRENT_COMMIT" ]; then
    echo "📂 Files changed since last deploy:"
    CHANGED_FILES=$(git diff --name-only "$PREV_COMMIT" "$CURRENT_COMMIT" || true)
    echo "$CHANGED_FILES"
else
    echo "📂 Force mode or initial deploy → skipping diff."
    CHANGED_FILES=""
fi
echo

### 4. Install requirements only if changed ###########################

if echo "$CHANGED_FILES" | grep -q '^requirements.txt$'; then
    echo "📦 requirements.txt changed → installing dependencies..."
    "$PIP_PATH" install -r requirements.txt --upgrade
else
    echo "📦 requirements unchanged → skipping pip install."
fi

### 5. Reload systemd ##################################################

echo "🔄 Reloading systemd (daemon-reload)..."
sudo systemctl daemon-reload

### 6. Restart selected services ######################################

echo "🔁 Restarting services: ${SERVICES[*]}"

for svc in "${SERVICES[@]}"; do
    echo "   ↻ Restarting $svc..."
    sudo systemctl restart "$svc"
    sleep 1
done

### 7. Verify services #################################################

echo "🩺 Checking service statuses..."
for svc in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$svc"; then
        echo "   ✅ $svc is running"
    else
        echo "   ❌ $svc failed!"
        sudo systemctl status "$svc" --no-pager
        exit 1
    fi
done

### 8. Save deployment #################################################

echo "📘 Logging deployment..."
mkdir -p /home/ubuntu/.voicer
echo "$(date): Deployed commit $CURRENT_COMMIT [services: ${SERVICES[*]}]" >> /home/ubuntu/.voicer/deploy.log

echo "$CURRENT_COMMIT" > "$LAST_DEPLOY_FILE"

echo "🎉 Deployment finished successfully!"
