#!/bin/bash
set -euo pipefail

# Logging setup
exec 1> >(tee -a /var/log/gh-runner-maestro/entrypoint.log)
exec 2> >(tee -a /var/log/gh-runner-maestro/entrypoint.log >&2)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting gh-runner-maestro..."

# Create log directory if it doesn't exist
mkdir -p /var/log/gh-runner-maestro
chmod 755 /var/log/gh-runner-maestro

# Function to cleanup on exit
cleanup() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Received shutdown signal, cleaning up..."
    pkill -TERM -f "python3.*main.py" || true
    sleep 2
    pkill -KILL -f "python3.*main.py" || true
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Check if we're running as root (needed for Docker socket access)
# Ensure we are running as root
if [ -z "${DOCKER_HOST:-}" ] && [ ! -S "/var/run/docker.sock" ]; then
    echo "Docker socket not found, starting internal Docker daemon..."
    # Use cgroupfs cgroup driver and vfs storage driver for DIND
    dockerd --host=unix:///var/run/docker.sock --storage-driver=vfs --exec-opt native.cgroupdriver=cgroupfs > /proc/1/fd/1 2>&1 &
fi

# Check if Docker is available
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking Docker socket availability..."
MAX_RETRIES=10
RETRY_COUNT=0

while ! docker info >/dev/null 2>&1; do
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Docker socket not available after $MAX_RETRIES attempts"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Docker info output:"
        docker info 2>&1 || true
        exit 1
    fi
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for Docker socket... ($((RETRY_COUNT + 1))/$MAX_RETRIES)"
    sleep 2
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Docker socket is available"

# Health check function
health_check() {
    if ! docker info >/dev/null 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Docker health check failed"
        return 1
    fi
    return 0
}

# Run health check before starting
if ! health_check; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Docker health check failed"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting maestro orchestration..."
exec /venv/bin/python3 -u main.py