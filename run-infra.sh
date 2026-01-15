#!/bin/bash
set -e
source ./common.sh

echo "=== SQL Insight Engine - Infrastructure Deployment ==="

NAMESPACE="sql-insight-engine"

# 1. Pull and Import Infrastructure Images
echo "Processing infrastructure images..."
INFRA_IMAGES="postgres:15 redis:7-alpine chromadb/chroma:0.5.23 rabbitmq:3-management minio/minio:latest"
for img in $INFRA_IMAGES; do
    echo "Processing $img..."
    if ! docker image inspect $img > /dev/null 2>&1; then
        docker pull $img
    fi
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

# 3. Deploy Infrastructure via Helm
echo "Deploying Infrastructure..."
# Since defaults in values.yaml are now false, we only enable infra.
# If upgrading, --reuse-values keeps other components enabled.
helm upgrade --install sql-insight-engine ./helm/sql-insight-engine \
    $REUSE_VALUES \
    --set global.imagePullPolicy=IfNotPresent \
    --set postgresql.enabled=true \
    --set externalTestDb.enabled=true \
    --set redis.enabled=true \
    --set rabbitmq.enabled=true \
    --set minio.enabled=true \
    --set chromadb.enabled=true \
    --create-namespace \
    --namespace $NAMESPACE \
    --wait \
    --timeout 10m

echo ""
echo "=== Infrastructure Deployment Complete ==="
echo "You can now run ./run-apps.sh or ./run-observability.sh"
echo ""
kubectl get pods -n $NAMESPACE
