from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
import uvicorn
import time
import os
import redis
import json
import asyncio
import httpx
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="MCP Registry")

# Prometheus metrics
Instrumentator().instrument(app).expose(app)

class MCPServerInfo(BaseModel):
    name: str
    url: str
    last_seen: float = 0.0
    status: str = "unknown" # New field

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

REDIS_KEY = "mcp_servers"

@app.post("/register")
async def register_server(server: MCPServerInfo):
    server.last_seen = time.time()
    # If it's registering, it's likely healthy, but the background task will confirm
    server.status = "healthy"
    # Use URL as key to allow multiple replicas of the same service
    r.hset(REDIS_KEY, server.url, server.model_dump_json())
    print(f"Registered server: {server.name} at {server.url}")
    return {"status": "ok", "url": server.url}

@app.get("/servers", response_model=List[MCPServerInfo])
async def list_servers():
    current_time = time.time()
    try:
        servers_data = r.hgetall(REDIS_KEY)
        servers = []
        for name, data in servers_data.items():
            server = MCPServerInfo.model_validate_json(data)
            # Filter out servers not seen in the last 45 seconds (down from 60)
            # and only return those that are still healthy according to the monitor
            if current_time - server.last_seen < 45 and server.status == "healthy":
                servers.append(server)
            elif current_time - server.last_seen >= 45:
                # Cleanup old servers
                r.hdel(REDIS_KEY, name)
        return servers
    except Exception as e:
        print(f"Error listing servers from Redis: {e}")
        return []

@app.get("/health")
async def health_check():
    try:
        r.ping()
        return {"status": "healthy", "redis": "connected", "timestamp": time.time()}
    except Exception as e:
        return {"status": "unhealthy", "redis": str(e), "timestamp": time.time()}

async def monitor_servers():
    """Background task to check health of registered services"""
    print("Starting background server monitor...")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                servers_data = r.hgetall(REDIS_KEY)
                for key, data in servers_data.items():
                    server = MCPServerInfo.model_validate_json(data)
                    base_url = server.url.replace("/sse", "")
                    health_url = f"{base_url}/health"
                    
                    try:
                        resp = await client.get(health_url, timeout=3.0)
                        if resp.status_code == 200:
                            new_status = "healthy"
                        else:
                            new_status = f"unhealthy ({resp.status_code})"
                    except Exception as e:
                        new_status = f"error: {repr(e)}"
                    
                    if server.status != new_status:
                        server.status = new_status
                        r.hset(REDIS_KEY, key, server.model_dump_json())
                        print(f"Server {server.name} at {key} status changed to: {new_status}")
                        
            except Exception as e:
                print(f"Error in monitor loop: {e}")
            
            await asyncio.sleep(30) # Check every 30 seconds

@app.on_event("startup")
async def startup_event():
    # Start monitor in the background
    asyncio.create_task(monitor_servers())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
