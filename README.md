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

The system uses a "Retrieval-Augmented Generation" (RAG) flow combined with a self-correcting execution loop.

```mermaid
graph TD
    User["User Query"] --> Router{"Router"}
    Router -- "General Chat" --> LLM["LLM Response"]
    
    subgraph RAG ["Knowledge Augmentation (RAG)"]
    Router -- "Data Request" --> VectorStore["Vector DB (Chroma)"]
    VectorStore -- "Semantic Search for Rules" --> Context["Context Builder"]
    end

    subgraph Analysis ["The Analyst Loop"]
    Context --> Schema["Schema Selector"]
    Schema --> SQLGen["SQL Generator"]
    SQLGen --> Safety{"Safety Check"}
    Safety -- "Dangerous (DROP/DELETE)" --> Error["Return Safety Error"]
    Safety -- "Safe (SELECT)" --> Exec[("PostgreSQL DB")]
    
    Exec -- "SQL Error" --> Reflection["Error Reflector"]
    Reflection --> SQLGen
    
    Exec -- "Success (Raw Data)" --> Analyst["Data Summarizer"]
    end
    
    Analyst --> Report["Final Insight Report"]
