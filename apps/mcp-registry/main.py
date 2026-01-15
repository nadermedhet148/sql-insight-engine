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
    status: str = "unknown"
    is_static: bool = False # New field to prevent deletion of static config

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

@app.on_event("startup")
async def startup_event():
    # Read static configuration from environment
    mcp_services_config = os.getenv("MCP_SERVICES")
    if mcp_services_config:
        try:
            services = json.loads(mcp_services_config)
            print(f"Loading static services config: {services}")
            for svc in services:
                server = MCPServerInfo(
                    name=svc["name"],
                    url=svc["url"],
                    last_seen=time.time(),
                    status="unknown", # Will be checked by monitor
                    is_static=True
                )
                # Store with a specific prefix or flag to identify as static if needed, 
                # but for now standard processing is fine as long as we keep updating it.
                r.hset(REDIS_KEY, server.url, server.model_dump_json())
                print(f"Registered static server: {server.name} at {server.url}")
        except json.JSONDecodeError as e:
            print(f"Error parsing MCP_SERVICES environment variable: {e}")
        except Exception as e:
            print(f"Error registering static services: {e}")

    # Start monitor in the background
    asyncio.create_task(monitor_servers())

@app.get("/servers", response_model=List[MCPServerInfo])
async def list_servers():
    current_time = time.time()
    try:
        servers_data = r.hgetall(REDIS_KEY)
        servers = []
        for name, data in servers_data.items():
            server = MCPServerInfo.model_validate_json(data)
            
            # Logic update: If it's a "static" server (loaded from env), we generally want to keep it
            # unless it's explicitly unhealthy for a long time?
            # For this implementation, we will treat them similarly but rely on the monitor loop 
            # to keep their 'last_seen' updated if we wanted to use strict timeouts.
            # HOWEVER, the requirement is "static config". So we should NOT delete them just because 
            # they haven't "registered" recently (since they don't register anymore).
            
            # WE WILL ASSUME that the monitor_servers loop updates 'last_seen' or we ignore last_seen for static.
            # But monitor_servers currently only updates STATUS.
            
            # Simple fix: If it's in the Env Var config, we never delete it.
            # But we don't have that list strictly here.
            
            # BETTER APPROACH: The monitor loop should update 'last_seen' for successful health checks.
            # Let's modify monitor_servers as well.
            
            servers.append(server)
            
            # We are removing the aggressive TTL cleanup for now to support static services
            # that don't self-register. The monitor will mark them unhealthy rather than deleting them.
            
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
                            # Update last_seen so we know it's alive, even if static
                            server.last_seen = time.time()
                        else:
                            new_status = f"unhealthy ({resp.status_code})"
                    except Exception as e:
                        new_status = f"error: {repr(e)}"
                    
                    if new_status == "healthy":
                        if server.status != new_status:
                            server.status = new_status
                            print(f"Server {server.name} at {key} status changed to: {new_status}")
                        # Only save (update last_seen/status) if healthy
                        r.hset(REDIS_KEY, key, server.model_dump_json())
                    else:
                        print(f"Server {server.name} at {key} is unhealthy (Status: {new_status})")
                        if server.is_static:
                             print(f"Keeping static server {server.name} despite failure.")
                             if server.status != new_status:
                                 server.status = new_status
                                 r.hset(REDIS_KEY, key, server.model_dump_json())
                        else:
                             print(f"Removing unhealthy server: {server.name} at {key}")
                             r.hdel(REDIS_KEY, key)
                        
            except Exception as e:
                print(f"Error in monitor loop: {e}")
            
            await asyncio.sleep(30) # Check every 30 seconds

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
