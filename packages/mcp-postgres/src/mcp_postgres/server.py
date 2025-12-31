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
import socket
import time
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

load_dotenv()

REGISTRY_URL = os.getenv("MCP_REGISTRY_URL", "http://mcp-registry:8010")
SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-postgres:8001/sse")
INSTANCE_ID = os.getenv("HOSTNAME", socket.gethostname())

# MCP Tool Metrics
MCP_TOOL_CALLS = Counter(
    'mcp_tool_calls_total',
    'Total MCP tool calls',
    ['tool_name', 'service', 'instance', 'status']
)
MCP_TOOL_DURATION = Histogram(
    'mcp_tool_duration_seconds',
    'MCP tool execution time',
    ['tool_name', 'service'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

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
            start_time = time.time()
            status = "success"
            
            # Mask sensitive info for logging
            log_args = arguments.copy()
            if "db_url" in log_args:
                log_args["db_url"] = "***"
            
            logger.info(f"Tool call: {name} | Args: {log_args}")
            
            db_url = arguments.get("db_url")
            if not db_url:
                db_url = os.getenv("MCP_DB_URL") # Fallback
            
            if not db_url:
                logger.error(f"Tool {name} failed: No db_url provided")
                MCP_TOOL_CALLS.labels(tool_name=name, service='mcp-postgres', instance=INSTANCE_ID, status='error').inc()
                return [TextContent(type="text", text="Error: No db_url provided and MCP_DB_URL not set")]

            engine = self._get_engine(db_url)
            inspector = inspect(engine)
            
            try:
                if name == "list_tables":
                    schema = arguments.get("schema") or "public"
                    logger.info(f"Listing tables for schema: {schema}")
                    tables = inspector.get_table_names(schema=schema)
                    logger.info(f"Found {len(tables)} tables: {tables}")
                    formatted_text = f"Tables:\n" + "\n".join(f"- {t}" for t in tables)
                    logger.info(f"Returning content: {formatted_text!r}")
                    result = [TextContent(type="text", text=formatted_text)]
                
                elif name == "describe_table":
                    table_name = arguments["table_name"]
                    schema = arguments.get("schema") or "public"
                    
                    logger.info(f"Describing table: {table_name} in schema: {schema}")
                    columns = inspector.get_columns(table_name, schema=schema)
                    pk = inspector.get_pk_constraint(table_name, schema=schema)
                    
                    text = f"## Table: {table_name}\n\n### Columns:\n"
                    for col in columns:
                        text += f"- {col['name']}: {col['type']}\n"
                    text += f"\nPK: {', '.join(pk.get('constrained_columns', []))}\n"
                    logger.info(f"Successfully described table {table_name}")
                    result = [TextContent(type="text", text=text)]
                else:
                    logger.warning(f"Unknown tool requested: {name}")
                    result = [TextContent(type="text", text=f"Unknown tool: {name}")]
                    status = "unknown"
                
            except Exception as e:
                logger.exception(f"Error executing {name}: {str(e)}")
                status = "error"
                result = [TextContent(type="text", text=f"Error: {str(e)}")]
            
            finally:
                duration = time.time() - start_time
                logger.info(f"Tool call finished: {name} | Status: {status} | Duration: {duration:.3f}s")
                MCP_TOOL_CALLS.labels(tool_name=name, service='mcp-postgres', instance=INSTANCE_ID, status=status).inc()
                MCP_TOOL_DURATION.labels(tool_name=name, service='mcp-postgres').observe(duration)
            
            return result

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

# Prometheus metrics
REQUEST_COUNT = Counter('mcp_postgres_requests_total', 'Total requests', ['method', 'endpoint'])
REQUEST_LATENCY = Histogram('mcp_postgres_request_duration_seconds', 'Request latency', ['endpoint'])

@app.get("/health")
async def health():
    REQUEST_COUNT.labels(method='GET', endpoint='/health').inc()
    return {"status": "healthy", "server": "mcp-postgres"}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

def get_local_ip():
    try:
        # In Docker Swarm, the hostname resolves to the overlay network IP
        return socket.gethostbyname(socket.gethostname())
    except Exception as e:
        logger.warning(f"IP detection error: {e}")
        return "127.0.0.1"

async def register_with_registry():
    """Register this server with the MCP Registry periodically"""
    local_ip = get_local_ip()
    port = 8001 # Hardcoded for this service
    # Construct URL using the real IP of this replica
    registration_url = f"http://{local_ip}:{port}/sse"
    
    while True:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{REGISTRY_URL}/register",
                    json={
                        "name": mcp_server.server_name,
                        "url": registration_url
                    },
                    timeout=5.0
                )
                if response.status_code == 200:
                    logger.info(f"Registered (replica {INSTANCE_ID}) at {registration_url}")
                else:
                    logger.error(f"Failed to register: {response.status_code}")
        except Exception as e:
            logger.error(f"Error registering: {str(e)}")
        
        # Heartbeat every 15 seconds
        await asyncio.sleep(15)

@app.on_event("startup")
async def startup_event():
    # Start registration in the background
    asyncio.create_task(register_with_registry())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
