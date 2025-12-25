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
        RMQ --> G[Step 2: Merged Check & Generator]
        G --> E[Step 3: Query Executor]
        E --> F[Step 4: Result Formatter]
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

### Saga Pattern Workflow
```mermaid
sequenceDiagram
    participant User as User/Frontend
    participant API as FastAPI
    participant SS as Redis (State Store)
    participant RMQ as RabbitMQ
    participant G as Step 2: Merged Check & Generator
    participant E as Step 3: Query Executor
    participant F as Step 4: Result Formatter
    
    User->>API: POST /query/async
    API->>SS: Mark Saga as Pending
    API->>RMQ: Publish QueryInitiatedMessage
    API-->>User: Return saga_id
    
    Note over G,F: Asynchronous Processing
    
    RMQ->>G: Consume Message
    G->>G: Agentic Loop (Discovery + Generate SQL)
    G->>SS: Update State (SQL + Call Stack)
    G->>RMQ: Publish QueryGeneratedMessage
    
    RMQ->>E: Consume Message
    E->>E: Execute SQL via MCP Tool
    E->>SS: Update State (Raw Results)
    E->>RMQ: Publish QueryExecutedMessage
    
    RMQ->>F: Consume Message
    F->>F: Agentic Loop (Executive Formatting)
    F->>SS: Mark as Completed (Final Result)
    
    loop Polling
        User->>API: GET /query/status/{saga_id}
        API->>SS: Fetch Current State
        SS-->>API: Current Data
        API-->>User: Status + Results (if done)
    end
```

---

## 🚀 Getting Started

### 1. Requirements
- Docker & Docker Compose
- Python 3.11+ (for local development)
- Google Gemini API Key

### 2. Running with Docker (Recommended)
The easiest way to run the entire stack (API, Consumers, Redis, RabbitMQ, PostgreSQL, ChromaDB) is via Docker Compose:

```bash
docker compose up --build
```

### 3. Local Development

#### Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 🗄️ Database Migrations

We use **Alembic** to manage database schema changes for the Metadata Database.

### Running Migrations
If you are running the project locally and want to sync your database:

```bash
# Set your database URL (if different from default)
export DATABASE_URL=postgresql://admin:password@localhost:5432/insight_engine

# Upgrade to the latest version
alembic upgrade head
```

### Creating New Migrations
After modifying models in `src/account/models.py`, generate a new migration script:

```bash
alembic revision --autogenerate -m "describe your changes"
```

### Viewing History
```bash
alembic history --verbose
```
