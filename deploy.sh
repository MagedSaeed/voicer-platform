#!/bin/bash

set -e

### CONFIG ###########################################################

APP_DIR="/opt/voicer-platform"
ENV_PATH="/home/ubuntu/miniconda3/envs/voicer-env"
PYTHON_PATH="$ENV_PATH/bin/python"
PIP_PATH="$ENV_PATH/bin/pip"

# All services in the platform
SERVICES=(
    "voicer-main"
    "voicer-ar"
    "voicer-stats"
    "voicer-anno"
    "voicer-prev"
)

######################################################################

echo "🚀 Starting Voicer platform deployment..."
cd $APP_DIR

### 1. Pull latest code ################################################

echo "📥 Pulling latest code from GitHub..."
git fetch --all
git reset --hard origin/main

### 2. Install dependencies ############################################

echo "📦 Updating Python dependencies..."
$PIP_PATH install -r requirements.txt --upgrade

### 3. Restart services ################################################

echo "🔄 Restarting services..."
for svc in "${SERVICES[@]}"; do
    echo "   ↻ Restarting $svc..."
    sudo systemctl restart $svc
    sleep 1
done

### 4. Verify services #################################################

echo "🩺 Checking service statuses..."
for svc in "${SERVICES[@]}"; do
    if systemctl is-active --quiet $svc; then
        echo "   ✅ $svc is running"
    else
        echo "   ❌ $svc FAILED to start!"
        sudo systemctl status $svc --no-pager
        exit 1
    fi
done

### 5. Log deployment ##################################################

echo "📘 Logging deployment timestamp..."
mkdir -p /home/ubuntu/.voicer
echo "$(date): Deployment completed successfully" >> /home/ubuntu/.voicer/deploy.log

echo "🎉 Deployment finished successfully!"
