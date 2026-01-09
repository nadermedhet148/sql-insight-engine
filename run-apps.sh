#!/bin/bash
set -e
source ./common.sh

echo "=== SQL Insight Engine - Applications Deployment ==="

NAMESPACE="sql-insight-engine"

# 0. Clean up old images
echo "Cleaning up old images..."
IMAGES_TO_CLEAN="sql-insight-engine-api:latest sql-insight-engine-mcp-postgres:latest sql-insight-engine-mcp-chroma:latest sql-insight-engine-mcp-registry:latest sql-insight-engine-ui:latest"
for img in $IMAGES_TO_CLEAN; do
   echo "Removing $img..."
   docker rmi -f $img || true
done

# 1. Build and Import Application Images
echo "Building Docker images..."
docker compose build
echo "Building UI image..."
docker build -t sql-insight-engine-ui:latest ./apps/sql-insight-engine/ui

# Tag images with timestamp to force K8s update
TAG=$(date +%s)
echo "Tagging images with version: $TAG"

docker tag sql-insight-engine-api:latest sql-insight-engine-api:$TAG
docker tag sql-insight-engine-mcp-postgres:latest sql-insight-engine-mcp-postgres:$TAG
docker tag sql-insight-engine-mcp-chroma:latest sql-insight-engine-mcp-chroma:$TAG
docker tag sql-insight-engine-mcp-registry:latest sql-insight-engine-mcp-registry:$TAG
docker tag sql-insight-engine-ui:latest sql-insight-engine-ui:$TAG

echo "Importing images into K3s..."
APP_IMAGES="sql-insight-engine-api:$TAG sql-insight-engine-mcp-postgres:$TAG sql-insight-engine-mcp-chroma:$TAG sql-insight-engine-mcp-registry:$TAG sql-insight-engine-ui:$TAG"

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
    --set api.replicaCount=6 \
    --set api.image.tag=$TAG \
    --set ui.enabled=true \
    --set ui.image.tag=$TAG \
    --set mcpPostgres.enabled=true \
    --set mcpPostgres.replicaCount=6 \
    --set mcpPostgres.image.tag=$TAG \
    --set mcpChroma.enabled=true \
    --set mcpChroma.replicaCount=6 \
    --set mcpChroma.image.tag=$TAG \
    --set mcpRegistry.enabled=true \
    --set mcpRegistry.image.tag=$TAG \
    --set secrets.geminiApiKey="${GEMINI_API_KEY}" \
    --set api.env.MOCK_GEMINI="fasle" \
    --create-namespace \
    --namespace $NAMESPACE

echo "Restarting deployments to pick up new images..."
# Rollout might not be strictly necessary with new tags, but good for safety
kubectl rollout restart deployment sql-insight-engine-api -n $NAMESPACE
kubectl rollout restart deployment sql-insight-engine-mcp-postgres -n $NAMESPACE
kubectl rollout restart deployment sql-insight-engine-mcp-chroma -n $NAMESPACE
kubectl rollout restart deployment sql-insight-engine-mcp-registry -n $NAMESPACE
kubectl rollout restart deployment sql-insight-engine-ui -n $NAMESPACE

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
