#!/bin/bash
set -e

echo "=== SQL Insight Engine - Docker Swarm Deployment ==="

# Check if Docker Swarm is initialized
SWARM_STATUS=$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo "inactive")
if [ "$SWARM_STATUS" != "active" ]; then
    echo "Initializing Docker Swarm..."
    docker swarm init --advertise-addr 127.0.0.1 || true
fi

echo "Building images..."
docker compose build

echo "Tagging images for Swarm..."
docker tag sql-insight-engine-mcp-registry:latest sql-insight-engine-mcp-registry:latest
docker tag sql-insight-engine-mcp-postgres:latest sql-insight-engine-mcp-postgres:latest
docker tag sql-insight-engine-mcp-chroma:latest sql-insight-engine-mcp-chroma:latest
docker tag sql-insight-engine-api:latest sql-insight-engine-api:latest

echo "Deploying stack..."
docker stack deploy -c docker-stack.yml insight

echo "Waiting for infrastructure services to start..."
sleep 15

echo "=== Deployment initiated ==="
echo "Use 'docker service ls' to check service status"
echo "Use 'docker stack ps insight' to see running tasks"

