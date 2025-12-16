# SQL Insight Engine Overview

The SQL Insight Engine is a powerful tool designed to bridge the gap between natural language questions and SQL database queries. It leverages advanced Large Language Models (LLMs) and vector database technologies to understand user intent and retrieve relevant database schema information.

## Key Features

- **Natural Language to SQL**: Converts plain English questions into optimized SQL queries.
- **Context-Aware Generation**: Uses retrieval-augmented generation (RAG) to find the most relevant table schemas and documentation.
- **Knowledge Base Integration**: Allows users to upload custom documentation (markdown/text) that helps the engine understand specific business logic or database quirks.
- **Multi-Tenant Support**: Designed with account-based isolation for secure data handling.

## Architecture

The system is built on a microservices-inspired architecture:
- **FastAPI**: Handles REST API requests.
- **PostgreSQL**: Stores metadata and user accounts.
- **ChromaDB**: Vector store for semantic search of documentation and schema info.
- **RabbitMQ**: Message broker for asynchronous document processing.
- **Minio**: S3-compatible object storage for raw document files.
