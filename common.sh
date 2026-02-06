#!/bin/bash
set -e

# === SQL Insight Engine - Common Deployment Logic ===

# 1. Load environment variables
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    set -a
    source .env
    set +a
fi

# 2. Check for required tools
check_tools() {
    if ! command -v kubectl &> /dev/null; then
        echo "❌ kubectl is not installed."
        exit 1
    fi
    if ! command -v helm &> /dev/null; then
        echo "❌ Helm is not installed."
        exit 1
    fi
    if ! command -v docker &> /dev/null; then
        echo "❌ Docker is not installed."
        exit 1
    fi
}

# 3. Check Cluster Connection
check_cluster() {
    echo "Using current Kubernetes context: $(kubectl config current-context)"
    if ! kubectl cluster-info &> /dev/null; then
        echo "❌ Kubernetes cluster is not reachable!"
        exit 1
    fi
    echo "✓ Kubernetes cluster is reachable"
}

# 4. Helper to import images into the local K8s cluster
import_image_to_k3s() {
    local IMAGE_NAME=$1
    if command -v k3s &> /dev/null; then
        echo "  - Importing $IMAGE_NAME into k3s..."
        docker save "$IMAGE_NAME" | sudo k3s ctr images import - > /dev/null
    elif command -v minikube &> /dev/null; then
        echo "  - Loading $IMAGE_NAME into minikube..."
        minikube image load "$IMAGE_NAME"
    else
        echo "  - WARNING: No k3s or minikube found, images may not be available in cluster"
    fi
}

check_tools
check_cluster
