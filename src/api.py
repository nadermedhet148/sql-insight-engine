
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        mq_host = os.getenv("RABBITMQ_HOST", "localhost")
        consumer = KnowledgeBaseActionConsumer(host=mq_host)
        t = threading.Thread(target=consumer.start_consuming, daemon=True)
        t.start()
        print(f"Started KnowledgeBaseActionConsumer on thread {t.name}")
    except Exception as e:
        print(f"Failed to start consumer: {e}")
    
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
app.include_router(knowledgebase.router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8002, reload=True)
