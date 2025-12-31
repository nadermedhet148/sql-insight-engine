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
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    set -a
    source .env
    set +a
    echo "DEBUG: METADATA_DB_USER=$METADATA_DB_USER"
    echo "DEBUG: METADATA_DB_NAME=$METADATA_DB_NAME"
fi
docker stack deploy -c docker-stack.yml insight

echo "Waiting for infrastructure services to start..."
sleep 15

echo "=== Deployment initiated ==="
echo ""
echo "Service Status:"
echo "  docker service ls"
echo ""
echo "Running Tasks:"
echo "  docker stack ps insight"
echo ""
echo "Observability Stack:"
echo "  Grafana:    http://localhost:4000 (admin/admin)"
echo "  Prometheus: http://localhost:9090"
echo "  Loki:       http://localhost:3100"
echo ""
