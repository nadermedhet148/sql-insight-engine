#!/bin/bash
set -e

echo "=== Rebuilding and restarting API ==="

echo "Building API image..."
docker compose build api

echo "Restarting API container..."
docker compose up -d api

echo "=== API rebuild complete ==="
echo "View logs with: docker logs -f api"
