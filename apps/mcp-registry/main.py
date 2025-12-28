from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional
import uvicorn
import time

app = FastAPI(title="MCP Registry")

class MCPServerInfo(BaseModel):
    name: str
    url: str
    last_seen: float = 0.0

# In-memory registry for simplicity
registry: Dict[str, MCPServerInfo] = {}

@app.post("/register")
async def register_server(server: MCPServerInfo):
    server.last_seen = time.time()
    registry[server.name] = server
    print(f"Registered server: {server.name} at {server.url}")
    return {"status": "ok", "name": server.name}

@app.get("/servers", response_model=List[MCPServerInfo])
async def list_servers():
    # Filter out servers not seen in the last 60 seconds (optional)
    current_time = time.time()
    return [s for s in registry.values() if current_time - s.last_seen < 300]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
