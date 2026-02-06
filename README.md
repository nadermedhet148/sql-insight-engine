# 🔍 SQL Insight Engine

**An Autonomous AI Agent that acts as a Data Analyst—combining Vector-Based Knowledge Retrieval with Database Querying.**

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Database](https://img.shields.io/badge/PostgreSQL-15-blue)
![Vector DB](https://img.shields.io/badge/VectorDB-Chroma-purple)
![License](https://img.shields.io/badge/License-MIT-green)

## 📖 Overview

Most "Text-to-SQL" tools fail because they don't understand business context. If you ask for "churned users," a standard LLM guesses the logic.

**SQL Insight Engine** solves this by using an **Agentic SQL Analyst** workflow. Unlike static tools, it:

1.  **Discovers Context**: Proactively searches the **Knowledge Base** (ChromaDB) for business logic (e.g., "Churn = Inactive > 30 days") using MCP search tools only when needed.
2.  **Schema Validation**: Verifies available tables in real-time before attempting to generate queries.
3.  **Agentic Generation**: Uses a tool-calling loop to describe tables and confirm business rules before writing PostgreSQL.
4.  **Self-Correction**: Automatically detects hallucinations and syntax errors, attempting to fix them in-flight.
5.  **Executive Reporting**: Synthesizes results into a human-readable summary.

## 🏗️ Architecture

The system uses a **Saga Pattern** with RabbitMQ to manage long-running agentic loops. It combines a state-managed asynchronous execution flow with **MCP (Model Context Protocol)** tools that allow the LLM to dynamically interact with both the database and the knowledge base.

### System Flow

```mermaid
graph TD
    User([User Question]) --> API[FastAPI Entrypoint]
    API --> Store[(Redis State Store)]
    API --> RMQ[(RabbitMQ)]

    subgraph Saga_Workers [Saga Workers]
        RMQ --> G[Step 1: Merged Check & Generator]
        G --> E[Step 2: Query Executor]
        E --> F[Step 3: Result Formatter]
    end

    G -.->|Update State| Store
    E -.->|Update State| Store
    F -.->|Set Complete| Store

    subgraph Agentic_Intelligence [Agentic Intelligence]
        G <--> Gemini{Google Gemini}
        E <--> Gemini
        F <--> Gemini
        Gemini <--> MCP_DB[Database MCP Tool]
        Gemini <--> MCP_KB[Knowledge Base MCP Tool]
    end

    API -.->|Poll Status| Store
    Store -.->|Final Insight| User
```

---

## 🔧 MCP Registry & Service Discovery

The system uses a **centralized MCP Registry** for dynamic service discovery. All MCP services (PostgreSQL tools, ChromaDB tools) register themselves with the registry on startup.

### MCP Registry Features

- **Redis-backed storage**: Service registrations persist across restarts
- **Health monitoring**: Background task checks service health every 30 seconds
- **Automatic cleanup**: Stale services (not seen for 1 hour) are removed
- **Status tracking**: Each service has a health status (`healthy`, `unhealthy`, `error`)

### Architecture

```mermaid
graph LR
    subgraph MCP_Services
        P1[mcp-database:8001]
        P2[mcp-database:8001]
        P3[mcp-database:8001]
        C1[mcp-chroma:8002]
        C2[mcp-chroma:8002]
        C3[mcp-chroma:8002]
    end

    subgraph Registry_Layer
        R1[mcp-registry:8010]
        R2[mcp-registry:8010]
        Redis[(Redis)]
    end

    P1 & P2 & P3 --> R1
    C1 & C2 & C3 --> R1
    R1 & R2 --> Redis

    API[API Server] --> R1
    API --> R2
```

### Registry Endpoints

| Endpoint    | Method | Description                   |
| ----------- | ------ | ----------------------------- |
| `/register` | POST   | Register an MCP server        |
| `/servers`  | GET    | List all healthy servers      |
| `/health`   | GET    | Check registry + Redis health |

---

## 🏢 Infrastructure Setup

### Services Overview

| Service            | Port       | Description                        |
| ------------------ | ---------- | ---------------------------------- |
| `api`              | 8001       | Main FastAPI application           |
| `mcp-registry`     | 8010       | Service discovery registry         |
| `mcp-database`     | 8011       | Database MCP tools (Multi-dialect) |
| `mcp-chroma`       | 8012       | ChromaDB MCP tools                 |
| `metadata_store`   | 5432       | Internal metadata PostgreSQL       |
| `external_test_db` | 5433       | External test database             |
| `rabbitmq`         | 5672/15672 | Message queue                      |
| `redis`            | 6379       | State store & registry storage     |
| `chromadb`         | 8000       | Vector database                    |
| `minio`            | 9000/9001  | Object storage                     |

### Docker Networks

- **`sql-insight-engine_insight_network`**: Bridge network for docker-compose
- **`insight_insight_network`**: Overlay network for Docker Swarm

---

## 🚀 Getting Started

### Prerequisites

- Docker & Docker Compose
- Kubernetes cluster (Minikube or Rancher Desktop with k3s)
- Helm 3
- kubectl
- Python 3.11+ (for local development)
- Google Gemini API Key ([get one here](https://aistudio.google.com/apikey))

### Environment Variables

Create a `.env` file in the project root:

```bash
# Gemini (required)
GEMINI_API_KEY=your_api_key

# Metadata Database
METADATA_DB_USER=admin
METADATA_DB_PASSWORD=password
METADATA_DB_NAME=insight_engine

# Test Database
TEST_DB_USER=admin
TEST_DB_PASSWORD=password
TEST_DB_NAME=external_test_db

# RabbitMQ
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

# MinIO
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin123
```

---

## 🏃 How to Run

The project uses Helm to deploy on Kubernetes. There are deployment scripts for different environments and stages.

### Deployment Scripts

| Script | What it does |
| --- | --- |
| `run-minikube.sh` | **Full deploy from scratch** on Minikube (builds images, pulls infra, deploys everything) |
| `run-k8s.sh` | **Full deploy from scratch** on Rancher Desktop / k3s |
| `run-infra.sh` | Deploy **infrastructure only** (PostgreSQL, Redis, RabbitMQ, ChromaDB, MinIO) |
| `run-apps.sh` | Rebuild and deploy **application services only** (API, MCP services, UI) — no infra restart |
| `run-observability.sh` | Deploy **observability stack** (Prometheus, Grafana, Loki, Promtail) |
| `restart-minikube.sh` | Restart Minikube and wait for existing pods — no rebuild |

### Option 1: Full Deployment (Minikube)

First-time setup that builds everything and deploys the entire stack:

```bash
# 1. Make sure your .env file is configured (see above)

# 2. Start minikube if not running
minikube start --driver=docker

# 3. Run the full deployment
./run-minikube.sh
```

This will:
1. Start Minikube if not already running
2. Build all Docker images inside Minikube's Docker daemon
3. Pull infrastructure images (PostgreSQL, Redis, RabbitMQ, ChromaDB, MinIO)
4. Deploy everything via Helm
5. Wait for all pods to be ready

### Option 2: Full Deployment (Rancher Desktop / k3s)

```bash
./run-k8s.sh
```

Same as above but uses k3s containerd for image import instead of minikube.

### Option 3: Staged Deployment

Deploy infrastructure and applications separately. Useful when you only want to redeploy app code without restarting databases:

```bash
# Step 1: Deploy infrastructure (databases, queues, storage)
./run-infra.sh

# Step 2: Deploy application services (API, MCP servers, UI)
./run-apps.sh

# Step 3 (optional): Deploy observability (Prometheus, Grafana)
./run-observability.sh
```

### Option 4: Docker Compose (Local Development)

Run the entire stack locally without Kubernetes:

```bash
docker compose up --build
```

### Post-Deployment Setup

After the first deployment, seed the test database:

```bash
# From inside the API pod
kubectl exec -it deploy/sql-insight-engine-api -n sql-insight-engine -c api -- \
    python scripts/setup_test_data.py
```

This creates a test user, configures the database connection, and seeds:
- 100 users
- 1,000 products
- 10,000 orders

### Redeploy After Code Changes

If you modify application code (Python files), use `run-apps.sh` to rebuild and redeploy only the application services without touching infrastructure:

```bash
./run-apps.sh
```

This rebuilds Docker images, imports them into the cluster, runs `helm upgrade`, and restarts the app deployments.

---

## 🗄️ Database Configuration

### Connecting to External Databases

When configuring a user's database connection:

| Context              | Host                                      | Port   |
| -------------------- | ----------------------------------------- | ------ |
| From inside Docker   | `external_test_db`                        | `5432` |
| From inside K8s      | `sql-insight-engine-external-test-db`     | `5432` |
| From host machine    | `localhost`                               | `5433` |

### Database Migrations

We use **Alembic** to manage database schema changes for the Metadata Database.

```bash
# Set your database URL (if different from default)
export DATABASE_URL=postgresql://admin:password@localhost:5432/insight_engine

# Upgrade to the latest version
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "describe your changes"

# View history
alembic history --verbose
```

---

## 🧪 Using the System

1. Port-forward the UI and API (see below)
2. Open the UI at `http://localhost:8080`
3. Create a user and configure database connection
4. Ask questions like: *"What are my top 5 customers by total order amount?"*

---

## ☸️ Managing Deployments (Helm)

### Apply Configuration Changes

If you modify `values.yaml` (e.g., scaling replicas), apply changes without rebuilding images:

```bash
helm upgrade sql-insight-engine ./helm/sql-insight-engine \
    --namespace sql-insight-engine \
    --reuse-values
```

### Restart App Services (No Rebuild)

```bash
kubectl rollout restart deployment/sql-insight-engine-api \
    deployment/sql-insight-engine-mcp-database \
    deployment/sql-insight-engine-mcp-chroma \
    deployment/sql-insight-engine-mcp-registry \
    -n sql-insight-engine
```

### Delete Everything

```bash
helm uninstall sql-insight-engine -n sql-insight-engine
```

---

## 📋 Helpful Commands

### Check Logs

```bash
# API Logs
kubectl logs -n sql-insight-engine -l app.kubernetes.io/component=api --tail=100 -f

# MCP Database Logs
kubectl logs -n sql-insight-engine -l app.kubernetes.io/component=mcp-database --tail=100 -f

# MCP Chroma Logs
kubectl logs -n sql-insight-engine -l app.kubernetes.io/component=mcp-chroma --tail=100 -f

# MCP Registry Logs
kubectl logs -n sql-insight-engine -l app.kubernetes.io/component=mcp-registry --tail=100 -f
```

### Check Pod Status

```bash
kubectl get pods -n sql-insight-engine
```

### Port Forwarding

```bash
# UI (http://localhost:8080)
kubectl port-forward svc/sql-insight-engine-ui 8080:80 -n sql-insight-engine &

# API (http://localhost:8000)
kubectl port-forward svc/sql-insight-engine-api 8000:8000 -n sql-insight-engine &

# MCP Registry (http://localhost:8010)
kubectl port-forward svc/sql-insight-engine-mcp-registry 8010:8010 -n sql-insight-engine &

# RabbitMQ Dashboard (http://localhost:15672) - guest/guest
kubectl port-forward svc/sql-insight-engine-rabbitmq 15672:15672 -n sql-insight-engine &

# Grafana (http://localhost:3000) - admin/admin
kubectl port-forward svc/sql-insight-engine-grafana 3000:3000 -n sql-insight-engine &

# Prometheus (http://localhost:9090)
kubectl port-forward svc/sql-insight-engine-prometheus 9090:9090 -n sql-insight-engine &
```
