#!/bin/bash
set -e

echo "=========================================="
echo "ChromaDB 3-Node Cluster Deployment"
echo "=========================================="

NAMESPACE="sql-insight-engine"

# Step 1: Create ChromaDB database in PostgreSQL (ignore if exists)
echo ""
echo "[1/5] Creating ChromaDB system database in PostgreSQL..."
kubectl exec sql-insight-engine-postgresql-0 -n $NAMESPACE -- \
  psql -U admin -d postgres -c "CREATE DATABASE chromadb_sysdb;" 2>/dev/null || echo "Database already exists (OK)"
echo "✓ PostgreSQL database ready"

# Step 2: Create MinIO bucket for ChromaDB (ignore if exists)
echo ""
echo "[2/5] Creating MinIO bucket for ChromaDB..."
kubectl exec sql-insight-engine-minio-0 -n $NAMESPACE -- sh -c \
  "mc alias set local http://localhost:9000 minioadmin minioadmin123 && mc mb local/chromadb-data" 2>/dev/null || echo "Bucket already exists (OK)"
echo "✓ MinIO bucket ready"

# Step 3: Build and import images
echo ""
echo "[3/5] Building and importing Docker images..."
cd /home/nader/projects/sql-insight-engine
docker compose build api mcp-chroma
docker save sql-insight-engine-api:latest sql-insight-engine-mcp-chroma:latest | sudo k3s ctr images import -
echo "✓ Images imported to k3s"

# Step 4: Delete old standalone ChromaDB if exists
echo ""
echo "[4/5] Cleaning up old ChromaDB deployment..."
kubectl delete statefulset sql-insight-engine-chromadb -n $NAMESPACE --ignore-not-found 2>/dev/null || true
kubectl delete pvc data-sql-insight-engine-chromadb-0 -n $NAMESPACE --ignore-not-found 2>/dev/null || true
echo "✓ Old ChromaDB removed"

# Step 5: Upgrade Helm chart with distributed mode (explicit values)
echo ""
echo "[5/5] Deploying ChromaDB 3-node cluster via Helm..."
helm upgrade sql-insight-engine ./helm/sql-insight-engine -n $NAMESPACE \
  --set chromadb.enabled=true \
  --set chromadb.mode=distributed \
  --set chromadb.replicaCount=3 \
  --set chromadb.image.repository=chromadb/chroma \
  --set chromadb.image.tag=0.5.23 \
  --set chromadb.service.port=8000 \
  --set chromadb.persistence.enabled=true \
  --set chromadb.persistence.size=5Gi \
  --set chromadb.sysdb.host=sql-insight-engine-postgresql \
  --set chromadb.sysdb.port=5432 \
  --set chromadb.sysdb.database=chromadb_sysdb \
  --set chromadb.sysdb.user=admin \
  --set chromadb.sysdb.password=password \
  --set chromadb.storage.endpoint=sql-insight-engine-minio:9000 \
  --set chromadb.storage.bucket=chromadb-data \
  --set chromadb.storage.accessKey=minioadmin \
  --set chromadb.storage.secretKey=minioadmin123 \
  --set chromadb.storage.useSSL=false \
  --set chromadb.resources.requests.memory=512Mi \
  --set chromadb.resources.requests.cpu=250m \
  --set chromadb.resources.limits.memory=1Gi \
  --set chromadb.resources.limits.cpu=500m \
  --reuse-values

# Wait for rollout
echo ""
echo "Waiting for ChromaDB pods to be ready..."
kubectl rollout status deployment/sql-insight-engine-chromadb-query -n $NAMESPACE --timeout=180s || true
kubectl rollout status statefulset/sql-insight-engine-chromadb-coordinator -n $NAMESPACE --timeout=180s || true

# Restart MCP Chroma to connect to new cluster
echo ""
echo "Restarting MCP Chroma and API to connect to new cluster..."
kubectl rollout restart deployment/sql-insight-engine-mcp-chroma -n $NAMESPACE
kubectl rollout restart deployment/sql-insight-engine-api -n $NAMESPACE

# Show status
echo ""
echo "=========================================="
echo "ChromaDB Cluster Status"
echo "=========================================="
kubectl get pods -n $NAMESPACE | grep -E "chromadb|mcp-chroma"

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "ChromaDB Cluster Components:"
echo "  - Coordinator (writes): sql-insight-engine-chromadb-coordinator-0"
echo "  - Query Nodes (reads):  sql-insight-engine-chromadb-query-xxx (3 replicas)"
echo ""
echo "MCP Chroma connects to: sql-insight-engine-chromadb:8000"
echo ""
