#!/bin/bash
set -e

echo "=== SQL Insight Engine - Minikube Deployment ==="

# Load environment variables
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    set -a
    source .env
    set +a
    echo "DEBUG: GEMINI_API_KEY length=${#GEMINI_API_KEY}"
fi

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl is not installed. Please install it first:"
    echo "   https://kubernetes.io/docs/tasks/tools/"
    exit 1
fi

# Check if helm is installed
if ! command -v helm &> /dev/null; then
    echo "❌ Helm is not installed. Please install it first:"
    echo "   https://helm.sh/docs/intro/install/"
    exit 1
fi

# Check if minikube is installed
if ! command -v minikube &> /dev/null; then
    echo "❌ Minikube is not installed. Please install it first."
    exit 1
fi

# Check Minikube status
echo "Checking Minikube status..."
if ! minikube status | grep -q "Running"; then
    echo "Minikube is not running. Starting it..."
    minikube start --driver=docker
else
    echo "✓ Minikube is running"
fi

# Point Docker to Minikube
echo "Configuring Docker environment to use Minikube..."
eval $(minikube docker-env)
echo "✓ Docker environment configured"

# Build Docker images inside Minikube
echo "Building Docker images inside Minikube..."
docker compose build

echo "Building UI image..."
docker build -t sql-insight-engine-ui:latest ./apps/sql-insight-engine/ui

# Tag images
echo "Tagging images..."
docker tag sql-insight-engine-api:latest sql-insight-engine-api:latest
docker tag sql-insight-engine-mcp-database:latest sql-insight-engine-mcp-database:latest
docker tag sql-insight-engine-mcp-chroma:latest sql-insight-engine-mcp-chroma:latest
docker tag sql-insight-engine-mcp-registry:latest sql-insight-engine-mcp-registry:latest

# We don't need to import images because we built them inside Minikube!

# Pull external images
IMAGES="postgres:15 redis:7-alpine chromadb/chroma:latest grafana/grafana:latest prom/prometheus:latest"
for img in $IMAGES; do
    echo "Ensuring $img is present..."
    docker pull $img
done

# Deploy with Helm
echo "Deploying with Helm..."
helm upgrade --install sql-insight-engine ./helm/sql-insight-engine \
    --set secrets.geminiApiKey="${GEMINI_API_KEY}" \
    --set postgresql.env.user="${METADATA_DB_USER:-admin}" \
    --set postgresql.env.password="${METADATA_DB_PASSWORD:-password}" \
    --set postgresql.env.database="${METADATA_DB_NAME:-insight_engine}" \
    --set externalTestDb.env.user="${TEST_DB_USER:-admin}" \
    --set externalTestDb.env.password="${TEST_DB_PASSWORD:-password}" \
    --set externalTestDb.env.database="${TEST_DB_NAME:-external_test_db}" \
    --set rabbitmq.env.user="${RABBITMQ_USER:-guest}" \
    --set rabbitmq.env.password="${RABBITMQ_PASSWORD:-guest}" \
    --set minio.env.rootUser="${MINIO_ROOT_USER:-minioadmin}" \
    --set minio.env.rootPassword="${MINIO_ROOT_PASSWORD:-minioadmin123}" \
    --create-namespace \
    --namespace sql-insight-engine \
    --wait \
    --timeout 10m

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod --all -n sql-insight-engine --timeout=300s

echo ""
echo "📊 Service Status:"
kubectl get pods -n sql-insight-engine
echo ""
kubectl get services -n sql-insight-engine

echo ""
echo "Minikube Service URLS:"
minikube service list -n sql-insight-engine

echo ""
echo "💡 Useful Commands:"
echo "  View logs:       kubectl logs -f deployment/sql-insight-engine-api -n sql-insight-engine"
echo "  Get pods:        kubectl get pods -n sql-insight-engine"
echo "  Minikube dashboard: minikube dashboard"
echo ""
