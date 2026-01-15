#!/bin/bash
set -e
source ./common.sh

echo "=== SQL Insight Engine - Observability Deployment ==="

NAMESPACE="sql-insight-engine"

# 1. Pull and Import Observability Images
echo "Processing observability images..."
OBS_IMAGES="prom/prometheus:latest grafana/grafana:latest grafana/loki:2.9.0 grafana/promtail:2.9.0 traefik:v2.10"
for img in $OBS_IMAGES; do
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

# 3. Deploy Observability via Helm
echo "Deploying Observability Stack..."
helm upgrade --install sql-insight-engine ./helm/sql-insight-engine \
    $REUSE_VALUES \
    --set prometheus.enabled=true \
    --set grafana.enabled=true \
    --set loki.enabled=true \
    --set promtail.enabled=true \
    --set traefik.enabled=true \
    --create-namespace \
    --namespace $NAMESPACE \
    --wait \
    --timeout 10m

echo ""
echo "=== Observability Deployment Complete ==="
echo ""
kubectl get pods -n $NAMESPACE -l "app.kubernetes.io/component in (prometheus,grafana,loki,promtail,traefik)"
