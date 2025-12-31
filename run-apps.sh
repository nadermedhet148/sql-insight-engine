#!/bin/bash
set -e
source ./common.sh

echo "=== SQL Insight Engine - Applications Deployment ==="

NAMESPACE="sql-insight-engine"

# 1. Build and Import Application Images
echo "Building Docker images..."
docker compose build
echo "Building UI image..."
docker build -t sql-insight-engine-ui:latest ./apps/sql-insight-engine/ui

echo "Tagging and Importing Application Images..."
APP_IMAGES="sql-insight-engine-api:latest sql-insight-engine-mcp-postgres:latest sql-insight-engine-mcp-chroma:latest sql-insight-engine-mcp-registry:latest sql-insight-engine-ui:latest"

# Explicit retagging
docker tag sql-insight-engine-api:latest sql-insight-engine-api:latest
docker tag sql-insight-engine-mcp-postgres:latest sql-insight-engine-mcp-postgres:latest
docker tag sql-insight-engine-mcp-chroma:latest sql-insight-engine-mcp-chroma:latest
docker tag sql-insight-engine-mcp-registry:latest sql-insight-engine-mcp-registry:latest

for img in $APP_IMAGES; do
    import_image_to_k3s "$img"
done

# 2. Check if release exists
REUSE_VALUES=""
if helm status sql-insight-engine -n $NAMESPACE >/dev/null 2>&1; then
    echo "Release exists, reusing existing values..."
    REUSE_VALUES="--reuse-values"
else
    echo "Release does not exist, creating new installation..."
fi

# 3. Deploy Applications via Helm
echo "Deploying Applications..."
helm upgrade --install sql-insight-engine ./helm/sql-insight-engine \
    $REUSE_VALUES \
    --set api.enabled=true \
    --set ui.enabled=true \
    --set mcpPostgres.enabled=true \
    --set mcpChroma.enabled=true \
    --set mcpRegistry.enabled=true \
    --set secrets.geminiApiKey="${GEMINI_API_KEY}" \
    --create-namespace \
    --namespace $NAMESPACE \
    --wait \
    --timeout 10m

echo ""
echo "=== Applications Deployment Complete ==="
echo ""
kubectl get pods -n $NAMESPACE -l "app.kubernetes.io/component in (api,ui,mcp-postgres,mcp-chroma,mcp-registry)"

echo ""
echo "🌐 Access URLs:"
echo "  UI:         http://localhost:8080 (Requires port-forward)"
echo "  API:        http://localhost:8005 (Requires port-forward)"
echo "  Port forward UI: kubectl port-forward svc/sql-insight-engine-ui 8080:80 -n $NAMESPACE &"
echo "  Port forward API: kubectl port-forward svc/sql-insight-engine-api 8005:8000 -n $NAMESPACE &"
echo "  Port forward Registry: kubectl port-forward svc/sql-insight-engine-mcp-registry 8010:8010 -n $NAMESPACE &"
