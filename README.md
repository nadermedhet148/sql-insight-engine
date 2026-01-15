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

### Requirements

- Docker & Docker Compose
- Python 3.11+ (for local development)
- Google Gemini API Key

### Environment Variables

Create a `.env` file in the project root:

```bash
# Gemini
GEMINI_API_KEY=your_api_key

# Metadata Database
METADATA_DB_USER=admin
METADATA_DB_PASSWORD=password
METADATA_DB_NAME=insight_engine

# Test Database
TEST_DB_USER=test_user
TEST_DB_PASSWORD=test_password
TEST_DB_NAME=external_test_db

# RabbitMQ
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

# MinIO
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
```

---

## 🏃 How to Run

### Option 1: Docker Compose (Development)

The easiest way to run the entire stack:

```bash
# Start all services
docker compose up --build

# Or start in detached mode
docker compose up -d --build
```

### Option 2: Docker Swarm (Production/Scaling)

For running with replicas and load balancing:

```bash
# Run the deployment script
./run.sh
```

This will:

1. Initialize Docker Swarm if not already active
2. Build all images
3. Deploy the stack with Traefik load balancer
4. Create replicas: 3x mcp-database, 3x mcp-chroma, 2x mcp-registry

### Useful Commands

```bash
# Rebuild and restart API only
./rebuild_api.sh

# Check service status (Swarm)
docker service ls

# View API logs
docker logs -f api

# Check MCP registry
curl http://localhost:8010/servers

# Setup test data
python apps/sql-insight-engine/scripts/setup_test_data.py
```

---

## 🗄️ Database Configuration

### Connecting to External Databases

When configuring a user's database connection:

| Context              | Host                   | Port   |
| -------------------- | ---------------------- | ------ |
| From inside Docker   | `external_test_db`     | `5432` |
| From host machine    | `localhost`            | `5433` |
| From Docker via host | `host.docker.internal` | `5433` |

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

## 🧪 Testing

### Setup Test Database

```bash
source venv/bin/activate
python apps/sql-insight-engine/scripts/setup_test_data.py
```

This creates:

- 100 users
- 1,000 products
- 10,000 orders

### Query the System

1. Open the UI: `python apps/sql-insight-engine/serve_ui.py`
2. Create a user and configure database connection
3. Ask questions like: "What are my top 5 customers by total order amount?"

---

## ☸️ Managing Deployments (Helm)

### Apply Configuration Changes

If you modify `values.yaml` (e.g., scaling replicas), apply changes without rebuilding images:

```bash
helm upgrade --install sql-insight-engine ./helm/sql-insight-engine \
    --namespace sql-insight-engine \
    --reuse-values
```

### Apply Code Changes

If you modify application code (e.g., Python files), you must rebuild the image, import it into the cluster, and restart the deployment:

```bash
# Rebuild and Deploy API
docker compose build api && \
docker save sql-insight-engine-api:latest | sudo k3s ctr images import - && \
kubectl rollout restart deployment sql-insight-engine-api -n sql-insight-engine
```

## Helpful Commands

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

### Port Forwarding

```bash
# Main API (http://localhost:8000)
kubectl port-forward svc/sql-insight-engine-api 8000:8000 -n sql-insight-engine

# Main API Load Test Port (http://localhost:8005)
kubectl port-forward svc/sql-insight-engine-api 8005:8000 -n sql-insight-engine

# UI (http://localhost:8080)
kubectl port-forward svc/sql-insight-engine-ui 8080:80 -n sql-insight-engine

# RabbitMQ Dashboard (http://localhost:15672) - guest/guest
kubectl port-forward svc/sql-insight-engine-rabbitmq 15672:15672 -n sql-insight-engine

# Grafana (http://localhost:3000) - admin/admin
kubectl port-forward svc/sql-insight-engine-grafana 3000:3000 -n sql-insight-engine

# Prometheus (http://localhost:9090)
kubectl port-forward svc/sql-insight-engine-prometheus 9090:9090 -n sql-insight-engine

# MCP Registry (http://localhost:8010)
kubectl port-forward svc/sql-insight-engine-mcp-registry 8010:8010 -n sql-insight-engine
```
