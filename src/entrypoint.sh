#!/bin/bash
set -e

# Start Docker daemon in background
dockerd &

# Wait for Docker daemon to be ready
while ! docker info >/dev/null 2>&1; do
  echo "Waiting for Docker daemon to be ready in maestro..."
  sleep 1
done

# Run maestro orchestration using venv python3 (with correct deps)
exec /venv/bin/python3 -u main.py