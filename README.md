# 🔍 SQL Insight Engine

**An Autonomous AI Agent that acts as a Data Analyst—combining Vector-Based Knowledge Retrieval with Database Querying.**

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Database](https://img.shields.io/badge/PostgreSQL-15-blue)
![Vector DB](https://img.shields.io/badge/VectorDB-Chroma-purple)
![License](https://img.shields.io/badge/License-MIT-green)

## 📖 Overview

Most "Text-to-SQL" tools fail because they don't understand business context. If you ask for "churned users," a standard LLM guesses the logic.

**SQL Insight Engine** solves this by injecting a **Knowledge Base** layer before querying the database. It:
1.  **Retrieves** exact business definitions (e.g., "Churn = Inactive > 30 days") from a Vector Database (ChromaDB).
2.  **Generates** PostgreSQL queries based on those specific rules.
3.  **Self-Corrects** if the database returns a syntax error.
4.  **Reports** findings in executive summary format.

## 🏗️ Architecture

The system uses a "Retrieval-Augmented Generation" (RAG) flow combined with a self-correcting execution loop powered by a Saga pattern with RabbitMQ.

<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/cb0c98e9-e83f-4882-b5e6-9c992f219c74" />

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
*Note: Database migrations run automatically on startup inside the container.*

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
