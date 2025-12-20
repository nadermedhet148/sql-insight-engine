
from pydantic import BaseModel
from typing import List, Any
import uvicorn
import os
import sys

# Ensure src is in python path if running directly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load .env manually since python-dotenv might not be available
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
if os.path.exists(env_path):
    print(f"Loading environment from {env_path}")
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                if key not in os.environ:
                    os.environ[key] = value

import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from account import api as users
from knowledgebase import api as knowledgebase
from knowledgebase.consumer import KnowledgeBaseActionConsumer

# Database Initialization (Ensures models are registered)
import account.models 

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start all Saga consumers
    from agentic_sql.saga.consumers import (
        start_tables_consumer,
        start_query_generator_consumer,
        start_query_executor_consumer,
        start_result_formatter_consumer
    )
    
    consumers = [
        ("Tables Check", start_tables_consumer),
        ("Query Generator", start_query_generator_consumer),
        ("Query Executor", start_query_executor_consumer),
        ("Result Formatter", start_result_formatter_consumer)
    ]
    
    threads = []
    mq_host = os.getenv("RABBITMQ_HOST", "localhost")
    
    print("\n[LIFESPAN] Starting Saga Consumers...")
    for name, starter_func in consumers:
        try:
            t = threading.Thread(
                target=starter_func,
                args=(mq_host,),
                name=f"SagaConsumer-{name}",
                daemon=True
            )
            t.start()
            threads.append(t)
            print(f"[LIFESPAN] ✓ Started {name} Consumer")
        except Exception as e:
            print(f"[LIFESPAN] ✗ Failed to start {name} Consumer: {e}")
    
    # Also keep the legacy KB consumer if needed, but the new saga replaces its role for queries
    try:
        from knowledgebase.consumer import KnowledgeBaseActionConsumer
        legacy_consumer = KnowledgeBaseActionConsumer(host=mq_host)
        t_legacy = threading.Thread(target=legacy_consumer.start_consuming, daemon=True, name="LegacyKBConsumer")
        t_legacy.start()
        print(f"[LIFESPAN] ✓ Started Legacy KnowledgeBaseActionConsumer")
    except Exception as e:
        print(f"[LIFESPAN] ⚠ Could not start legacy KB consumer: {e}")
    
    yield
    
    # Shutdown logic if needed
    
app = FastAPI(title="SQL Insight Engine API", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)

# Include async saga routes
from agentic_sql import api as agentic_sql_api
app.include_router(agentic_sql_api.router, prefix="/users", tags=["async-queries"])

app.include_router(knowledgebase.router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8002, reload=True)
