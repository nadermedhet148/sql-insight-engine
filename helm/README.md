# SQL Insight Engine - Kubernetes Deployment

This directory contains Helm charts for deploying the SQL Insight Engine on Kubernetes using Minikube.

## Prerequisites

- **Minikube**: v1.30.0 or later
- **kubectl**: v1.27.0 or later
- **Helm**: v3.12.0 or later
- **Docker**: For building images

## Quick Start

1. **Install prerequisites** (if not already installed):

   ```bash
   # Install Minikube
   curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
   sudo install minikube-linux-amd64 /usr/local/bin/minikube

   # Install kubectl
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
   sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

   # Install Helm
   curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   ```

2. **Set up environment variables**:

   ```bash
   cp .env.example .env
   # Edit .env and add your GEMINI_API_KEY
   ```

3. **Deploy the application**:
   ```bash
   ./run-k8s.sh
   ```

## Architecture

The Helm chart deploys the following components:

### Application Services

- **API** (1 replica): Main FastAPI application
- **MCP Database** (3 replicas): Database MCP service (Multi-dialect)
- **MCP Chroma** (3 replicas): ChromaDB MCP service
- **MCP Registry** (2 replicas): Service registry

### Infrastructure Services

- **PostgreSQL**: Metadata database (StatefulSet)
- **External Test DB**: Test database (StatefulSet)
- **Redis**: Caching and session storage
- **RabbitMQ**: Message queue for saga pattern
- **ChromaDB**: Vector database
- **MinIO**: Object storage

### Observability Stack

- **Prometheus**: Metrics collection
- **Grafana**: Metrics visualization
- **Loki**: Log aggregation
- **Promtail**: Log shipping
- **Traefik**: Reverse proxy and load balancer

## Configuration

### Values File

Edit `helm/sql-insight-engine/values.yaml` to customize:

```yaml
api:
  replicaCount: 1 # Scale API instances
  resources:
    requests:
      memory: "512Mi"
      cpu: "250m"
```

### Secrets

The Gemini API key is stored as a Kubernetes Secret. You can update it:

```bash
kubectl create secret generic sql-insight-engine-secrets \
  --from-literal=gemini-api-key=YOUR_KEY \
  -n sql-insight-engine \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Accessing Services

After deployment, services are accessible via NodePort:

- **API**: `http://$(minikube ip):30001`
- **Grafana**: `http://$(minikube ip):30300`
- **Prometheus**: `http://$(minikube ip):30090`
- **Traefik Dashboard**: `http://$(minikube ip):30808`

### Port Forwarding

For local development, use port forwarding:

```bash
# API
kubectl port-forward svc/sql-insight-engine-api 8001:8000 -n sql-insight-engine

# Grafana
kubectl port-forward svc/sql-insight-engine-grafana 3000:3000 -n sql-insight-engine

# RabbitMQ Management
kubectl port-forward svc/sql-insight-engine-rabbitmq 15672:15672 -n sql-insight-engine
```

## Monitoring

### View Logs

```bash
# API logs
kubectl logs -f deployment/sql-insight-engine-api -n sql-insight-engine

# MCP Database logs
kubectl logs -f deployment/sql-insight-engine-mcp-database -n sql-insight-engine

# All pods
kubectl logs -f -l app.kubernetes.io/instance=sql-insight-engine -n sql-insight-engine
```

### Check Pod Status

```bash
kubectl get pods -n sql-insight-engine
kubectl describe pod <pod-name> -n sql-insight-engine
```

### Minikube Dashboard

```bash
minikube dashboard
```

## Scaling

Scale deployments:

```bash
# Scale API
kubectl scale deployment sql-insight-engine-api --replicas=3 -n sql-insight-engine

# Or via Helm
helm upgrade sql-insight-engine ./helm/sql-insight-engine \
  --set api.replicaCount=3 \
  -n sql-insight-engine
```

## Troubleshooting

### Pods not starting

```bash
# Check events
kubectl get events -n sql-insight-engine --sort-by='.lastTimestamp'

# Describe pod
kubectl describe pod <pod-name> -n sql-insight-engine

# Check logs
kubectl logs <pod-name> -n sql-insight-engine
```

### Image pull errors

Ensure you're using Minikube's Docker daemon:

```bash
eval $(minikube docker-env)
docker compose build
```

### Database connection issues

Check if PostgreSQL is ready:

```bash
kubectl exec -it sql-insight-engine-postgresql-0 -n sql-insight-engine -- pg_isready -U admin
```

## Cleanup

```bash
# Uninstall the Helm release
helm uninstall sql-insight-engine -n sql-insight-engine

# Delete the namespace
kubectl delete namespace sql-insight-engine

# Stop Minikube
minikube stop

# Delete Minikube cluster
minikube delete
```

## Differences from Docker Swarm

| Feature         | Docker Swarm           | Kubernetes                          |
| --------------- | ---------------------- | ----------------------------------- |
| Orchestration   | Simpler, less features | More complex, feature-rich          |
| Scaling         | Manual or basic        | Advanced autoscaling                |
| Health Checks   | Basic                  | Liveness, Readiness, Startup probes |
| Storage         | Volumes                | PersistentVolumes, StatefulSets     |
| Networking      | Overlay networks       | Services, Ingress, NetworkPolicies  |
| Configuration   | Environment variables  | ConfigMaps, Secrets                 |
| Rolling Updates | Basic                  | Advanced with rollback              |
| Resource Limits | Basic                  | Requests and Limits                 |

## Production Considerations

For production deployment:

1. **Use a managed Kubernetes service** (GKE, EKS, AKS)
2. **Enable RBAC** and security policies
3. **Use Ingress** instead of NodePort
4. **Set up persistent storage** with appropriate storage classes
5. **Configure resource requests and limits**
6. **Enable horizontal pod autoscaling**
7. **Set up monitoring and alerting**
8. **Use external databases** for production data
9. **Implement backup strategies**
10. **Use secrets management** (e.g., HashiCorp Vault)

## Support

For issues or questions, please check the main project README or open an issue on GitHub.
