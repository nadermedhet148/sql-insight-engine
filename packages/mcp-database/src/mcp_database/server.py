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
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from starlette.responses import Response

load_dotenv()

REGISTRY_URL = os.getenv("MCP_REGISTRY_URL", "http://mcp-registry:8010")
SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-database:8001/sse")
INSTANCE_ID = os.getenv("HOSTNAME", socket.gethostname())

# MCP Tool Metrics
# Check if metrics already exist to avoid duplication error
_metric_calls_name = 'mcp_tool_calls_total'
_metric_duration_name = 'mcp_tool_duration_seconds'

try:
    if _metric_calls_name in REGISTRY._names_to_collectors:
        MCP_TOOL_CALLS = REGISTRY._names_to_collectors[_metric_calls_name]
    else:
        MCP_TOOL_CALLS = Counter(
            'mcp_tool_calls_total',
            'Total MCP tool calls',
            ['tool_name', 'service', 'instance', 'status']
        )

    if _metric_duration_name in REGISTRY._names_to_collectors:
        MCP_TOOL_DURATION = REGISTRY._names_to_collectors[_metric_duration_name]
    else:
        MCP_TOOL_DURATION = Histogram(
            'mcp_tool_duration_seconds',
            'MCP tool execution time',
            ['tool_name', 'service'],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
except Exception as e:
    logger.error(f"Error initializing metrics: {e}")
    # Fallback to avoid NameError if registry access fails completely
    # (Though this shouldn't happen if prometheus_client is working)
    MCP_TOOL_CALLS = Counter(
        'mcp_tool_calls_total_fallback',
        'Total MCP tool calls (Fallback)',
        ['tool_name', 'service', 'instance', 'status']
    )
    MCP_TOOL_DURATION = Histogram(
        'mcp_tool_duration_seconds_fallback',
        'MCP tool execution time (Fallback)',
        ['tool_name', 'service'],
        buckets=[0.01, 10.0]
    )

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("mcp-database")

class DatabaseMCPServer:
    def __init__(self, server_name: str = "mcp-database"):
        self.server_name = server_name
        self.engines: Dict[str, Any] = {}
        logger.info(f"Initialized DatabaseMCPServer helper: {server_name}")
    
    def _get_engine(self, db_url: str):
        if db_url not in self.engines:
            # SQLAlchemy handles dialects based on the prefix (postgresql://, mysql+pymysql://, mssql+pymssql://)
            self.engines[db_url] = create_engine(db_url, pool_pre_ping=True)
        return self.engines[db_url]

    def _get_default_schema(self, engine) -> Optional[str]:
        dialect = engine.dialect.name
        if dialect == 'postgresql':
            return 'public'
        elif dialect == 'mssql':
            return 'dbo'
        return None

    def create_server(self) -> Server:
        server = Server(self.server_name)
        
        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="list_tables",
                    description="List all tables in the database (Supports PostgreSQL, MySQL, MSSQL)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "db_url": {"type": "string", "description": "Database connection string. Examples: postgresql://USER:PASS@HOST:PORT/DB, mysql+pymysql://USER:PASS@HOST:PORT/DB, mssql+pymssql://USER:PASS@HOST:PORT/DB"},
                            "schema": {"type": "string", "description": "Optional schema name (default: public for PG, dbo for MSSQL)"}
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
                            "db_url": {"type": "string", "description": "Database connection string"},
                            "schema": {"type": "string", "description": "Optional schema name"}
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
                MCP_TOOL_CALLS.labels(tool_name=name, service='mcp-database', instance=INSTANCE_ID, status='error').inc()
                return [TextContent(type="text", text="Error: No db_url provided and MCP_DB_URL not set")]

            try:
                engine = self._get_engine(db_url)
                inspector = inspect(engine)
                dialect = engine.dialect.name
                
                # Determine schema
                default_schema = self._get_default_schema(engine)
                schema = arguments.get("schema") or default_schema

                if name == "list_tables":
                    logger.info(f"Listing tables for dialect: {dialect}, schema: {schema}")
                    tables = inspector.get_table_names(schema=schema)
                    logger.info(f"Found {len(tables)} tables: {tables}")
                    formatted_text = f"Tables (Dialect: {dialect}, Schema: {schema}):\n" + "\n".join(f"- {t}" for t in tables)
                    logger.info(f"Returning content: {formatted_text!r}")
                    result = [TextContent(type="text", text=formatted_text)]
                
                elif name == "describe_table":
                    table_name = arguments["table_name"]
                    
                    logger.info(f"Describing table: {table_name} in schema: {schema}")
                    columns = inspector.get_columns(table_name, schema=schema)
                    pk = inspector.get_pk_constraint(table_name, schema=schema)
                    
                    text_out = f"## Table: {table_name} ({dialect})\n\n### Columns:\n"
                    for col in columns:
                        # Normalize type representation
                        col_type = str(col['type'])
                        text_out += f"- {col['name']}: {col_type}\n"
                    
                    pk_cols = pk.get('constrained_columns', [])
                    if pk_cols:
                        text_out += f"\nPK: {', '.join(pk_cols)}\n"
                    
                    logger.info(f"Successfully described table {table_name}")
                    result = [TextContent(type="text", text=text_out)]
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
                MCP_TOOL_CALLS.labels(tool_name=name, service='mcp-database', instance=INSTANCE_ID, status=status).inc()
                MCP_TOOL_DURATION.labels(tool_name=name, service='mcp-database').observe(duration)
            
            return result

        return server


mcp_server = DatabaseMCPServer()
from starlette.routing import Route

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Register with Registry
    logger.info(f"Registering with {REGISTRY_URL}...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{REGISTRY_URL}/register",
                json={
                    "name": "mcp-database",
                    "url": SERVER_URL
                },
                timeout=5.0
            )
            if resp.status_code == 200:
                logger.info("Successfully registered with registry")
            else:
                logger.error(f"Failed to register: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"Registration failed: {e}")
    
    yield
    # Shutdown logic if needed

app = FastAPI(lifespan=lifespan)
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
_req_count_name = 'mcp_database_requests_total'
_req_latency_name = 'mcp_database_request_duration_seconds'

try:
    if _req_count_name in REGISTRY._names_to_collectors:
        REQUEST_COUNT = REGISTRY._names_to_collectors[_req_count_name]
    else:
        REQUEST_COUNT = Counter(_req_count_name, 'Total requests', ['method', 'endpoint'])

    if _req_latency_name in REGISTRY._names_to_collectors:
        REQUEST_LATENCY = REGISTRY._names_to_collectors[_req_latency_name]
    else:
        REQUEST_LATENCY = Histogram(_req_latency_name, 'Request latency', ['endpoint'])
except Exception:
    # Fallback in case of weird registry state
    REQUEST_COUNT = Counter('mcp_database_requests_total_fb', 'Total requests', ['method', 'endpoint'])
    REQUEST_LATENCY = Histogram('mcp_database_request_duration_seconds_fb', 'Request latency', ['endpoint'])

@app.get("/health")
async def health():
    REQUEST_COUNT.labels(method='GET', endpoint='/health').inc()
    return {"status": "healthy", "server": "mcp-database"}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    import multiprocessing
    workers = int(os.getenv("UVICORN_WORKERS", multiprocessing.cpu_count()))
    uvicorn.run(
        "mcp_database.server:app",
        host="0.0.0.0",
        port=8001,
        workers=workers,
        limit_concurrency=200,
        limit_max_requests=10000,
    )
