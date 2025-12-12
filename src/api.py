from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Any
import uvicorn
import os
import sys

# Ensure src is in python path if running directly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from retrieval import KnowledgeBase
from generation import SQLGenerator
from execution import QueryExecutor
from database.session import engine
from database.models import Base
from routers import users

# Create tables if they don't exist (Simple migration execution)
# Base.metadata.create_all(bind=engine)

app = FastAPI(title="SQL Insight Engine API")

app.include_router(users.router)

class QueryRequest(BaseModel):
    query: str

class QueryResponse(BaseModel):
    query: str
    generated_sql: str
    results: Any
    context: List[str]

@app.post("/query", response_model=QueryResponse)
async def process_query(request: QueryRequest):
    """
    Process a natural language query:
    1. Retrieve context from Knowledge Base
    2. Generate SQL using Gemini
    3. Execute SQL (mocked for now)
    """
    try:
        # 1. Retrieval
        kb = KnowledgeBase()
        context = kb.search(request.query)
        
        # 2. Generation
        generator = SQLGenerator()
        sql = generator.generate_sql(request.query, context)
        
        # 3. Execution
        executor = QueryExecutor()
        results = executor.execute(sql)
        
        return QueryResponse(
            query=request.query,
            generated_sql=sql,
            results=results,
            context=context
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
