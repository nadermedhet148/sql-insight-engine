import asyncio
import os
import sys
import logging
from typing import Any, Optional, Dict
from mcp.server import Server, NotificationOptions
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from mcp.server.models import InitializationOptions
import mcp.types as types
import uvicorn

import httpx

load_dotenv()

REGISTRY_URL = os.getenv("MCP_REGISTRY_URL", "http://mcp-registry:8010")
SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-postgres:8001/sse")


# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("mcp-postgres")

class PostgresMCPServer:
    def __init__(self, server_name: str = "mcp-postgres"):
        self.server_name = server_name
        self.engines: Dict[str, Any] = {}
        logger.info(f"Initialized PostgresMCPServer helper: {server_name}")
    
    def _get_engine(self, db_url: str):
        if db_url not in self.engines:
            self.engines[db_url] = create_engine(db_url, pool_pre_ping=True)
        return self.engines[db_url]

    def create_server(self) -> Server:
        server = Server(self.server_name)
        
        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="list_tables",
                    description="List all tables in the database",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "db_url": {"type": "string", "description": "PostgreSQL connection string (optional if provided in context)"}
                        },
                        "required": []
                    }
                ),
                Tool(
                    name="describe_table",
                    description="Get column definitions for a specific table",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "The name of the table to describe"},
                            "db_url": {"type": "string", "description": "PostgreSQL connection string"}
                        },
                        "required": ["table_name"]
                    }
                )
            ]
        
        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            db_url = arguments.get("db_url")
            if not db_url:
                db_url = os.getenv("MCP_DB_URL") # Fallback
            
            if not db_url:
                return [TextContent(type="text", text="Error: No db_url provided and MCP_DB_URL not set")]

            engine = self._get_engine(db_url)
            inspector = inspect(engine)
            
            try:
                if name == "list_tables":
                    schema = arguments.get("schema") or "public"
                    tables = inspector.get_table_names(schema=schema)
                    return [TextContent(type="text", text=f"Tables:\n" + "\n".join(f"- {t}" for t in tables))]
                
                elif name == "describe_table":
                    table_name = arguments["table_name"]
                    schema = arguments.get("schema") or "public"
                    
                    columns = inspector.get_columns(table_name, schema=schema)
                    pk = inspector.get_pk_constraint(table_name, schema=schema)
                    
                    result = f"## Table: {table_name}\n\n### Columns:\n"
                    for col in columns:
                        result += f"- {col['name']}: {col['type']}\n"
                    result += f"\nPK: {', '.join(pk.get('constrained_columns', []))}\n"
                    return [TextContent(type="text", text=result)]
                
            except Exception as e:
                logger.exception(f"Error in {name}: {str(e)}")
                return [TextContent(type="text", text=f"Error: {str(e)}")]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return server


mcp_server = PostgresMCPServer()
from starlette.routing import Route

app = FastAPI()
sse = SseServerTransport("/messages")

class SSEHandler:
    async def __call__(self, scope, receive, send):
        logger.info(f"New SSE connection from {scope.get('client')}")
        try:
            server = mcp_server.create_server()
            async with sse.connect_sse(scope, receive, send) as (read_stream, write_stream):
                logger.info("SSE connection established, running server...")
                await server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name=mcp_server.server_name,
                        server_version="0.1.0",
                        capabilities=server.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    )
                )
                logger.info("mcp_server.server.run returned")
        except Exception as e:
            logger.exception(f"Error in SSEHandler: {e}")
        finally:
            logger.info("SSEHandler finished")

class MessagesHandler:
    async def __call__(self, scope, receive, send):
        logger.info(f"New message request from {scope.get('client')}")
        try:
            await sse.handle_post_message(scope, receive, send)
            logger.info("Message handled")
        except Exception as e:
            logger.exception(f"Error in MessagesHandler: {e}")

app.routes.append(Route("/sse", SSEHandler(), methods=["GET"]))
app.routes.append(Route("/messages", MessagesHandler(), methods=["POST"]))

@app.get("/health")
async def health():
    return {"status": "healthy", "server": "mcp-postgres"}

async def register_with_registry():
    """Register this server with the MCP Registry periodically"""
    while True:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{REGISTRY_URL}/register",
                    json={
                        "name": mcp_server.server_name,
                        "url": SERVER_URL
                    },
                    timeout=5.0
                )
                if response.status_code == 200:
                    logger.info(f"Successfully registered with registry: {REGISTRY_URL}")
                else:
                    logger.error(f"Failed to register with registry: {response.status_code}")
        except Exception as e:
            logger.error(f"Error registering with registry: {str(e)}")
        
        # Heartbeat every 2 minutes
        await asyncio.sleep(120)

@app.on_event("startup")
async def startup_event():
    # Start registration in the background
    asyncio.create_task(register_with_registry())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
