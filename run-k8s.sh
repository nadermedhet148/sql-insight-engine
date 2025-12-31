#!/bin/bash
set -e

echo "=== SQL Insight Engine - Kubernetes (Rancher Desktop) Deployment ==="

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

# Use current/default context
echo "Using current Kubernetes context..."
CURRENT_CONTEXT=$(kubectl config current-context)
echo "✓ Using context: $CURRENT_CONTEXT"

# Check if Kubernetes cluster is reachable
echo "Checking Kubernetes cluster connectivity..."
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Kubernetes cluster is not reachable!"
    echo ""
    echo "Please ensure Rancher Desktop is running:"
    echo "  1. Start Rancher Desktop application"
    echo "  2. Enable Kubernetes in Settings → Kubernetes"
    echo "  3. Wait for Kubernetes to be ready (green status)"
    echo "  4. Run this script again"
    echo ""
    exit 1
fi
echo "✓ Kubernetes cluster is reachable"

# Configure Docker environment to use Rancher Desktop's Docker daemon
echo "Configuring Docker environment..."
# Rancher Desktop uses the default Docker daemon, no special eval needed

# Build Docker images
echo "Building Docker images..."
docker compose build

# Tag images for Kubernetes
echo "Tagging images..."
docker tag sql-insight-engine-api:latest sql-insight-engine-api:latest
docker tag sql-insight-engine-mcp-postgres:latest sql-insight-engine-mcp-postgres:latest
docker tag sql-insight-engine-mcp-chroma:latest sql-insight-engine-mcp-chroma:latest
docker tag sql-insight-engine-mcp-registry:latest sql-insight-engine-mcp-registry:latest

# Import images into k3s/containerd to avoid ImagePullBackOff
echo "Importing images into k3s containerd..."
echo "  - Importing sql-insight-engine-api..."
docker save sql-insight-engine-api:latest | sudo k3s ctr images import -
echo "  - Importing sql-insight-engine-mcp-postgres..."
docker save sql-insight-engine-mcp-postgres:latest | sudo k3s ctr images import -
echo "  - Importing sql-insight-engine-mcp-chroma..."
docker save sql-insight-engine-mcp-chroma:latest | sudo k3s ctr images import -
echo "  - Importing sql-insight-engine-mcp-registry..."
docker save sql-insight-engine-mcp-registry:latest | sudo k3s ctr images import -
echo "✓ All images imported successfully"

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
echo "🌐 Access URLs:"
echo "  API:        http://localhost:30001"
echo "  Grafana:    http://localhost:30300 (admin/admin)"
echo "  Prometheus: http://localhost:30090"
echo "  Traefik:    http://localhost:30080"
echo ""
echo "💡 Useful Commands:"
echo "  View logs:       kubectl logs -f deployment/sql-insight-engine-api -n sql-insight-engine"
echo "  Get pods:        kubectl get pods -n sql-insight-engine"
echo "  Describe pod:    kubectl describe pod <pod-name> -n sql-insight-engine"
echo "  Port forward:    kubectl port-forward svc/sql-insight-engine-api 8001:8000 -n sql-insight-engine"
echo "  Delete deployment:  helm uninstall sql-insight-engine -n sql-insight-engine"
echo ""
