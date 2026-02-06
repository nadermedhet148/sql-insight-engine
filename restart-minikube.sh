#!/bin/bash
set -e

echo "=== SQL Insight Engine - Minikube Restart ==="
echo "This script restarts minikube without rebuilding images or redeploying."
echo "Use run-minikube.sh for a full setup (build + deploy)."
echo ""

NAMESPACE="sql-insight-engine"

# Check if minikube is installed
if ! command -v minikube &> /dev/null; then
    echo "Minikube is not installed. Please install it first."
    exit 1
fi

# Start minikube if not running
echo "Checking Minikube status..."
if ! minikube status | grep -q "Running"; then
    echo "Starting Minikube..."
    minikube start --driver=docker
else
    echo "Minikube is already running"
fi

# Wait for pods to be ready
echo ""
echo "Waiting for pods to come up..."
kubectl wait --for=condition=ready pod --all -n $NAMESPACE --timeout=300s 2>/dev/null || {
    echo ""
    echo "Some pods are not ready yet. Current status:"
    kubectl get pods -n $NAMESPACE
    echo ""
    echo "You can monitor with: kubectl get pods -n $NAMESPACE -w"
    exit 0
}

echo ""
echo "All pods are ready:"
kubectl get pods -n $NAMESPACE
echo ""
kubectl get services -n $NAMESPACE

echo ""
echo "Access URLs:"
echo "  UI:       kubectl port-forward svc/sql-insight-engine-ui 8080:80 -n $NAMESPACE &"
echo "  API:      kubectl port-forward svc/sql-insight-engine-api 8005:8000 -n $NAMESPACE &"
echo "  Registry: kubectl port-forward svc/sql-insight-engine-mcp-registry 8010:8010 -n $NAMESPACE &"
