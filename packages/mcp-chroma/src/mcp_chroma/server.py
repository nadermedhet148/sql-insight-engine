import asyncio
import os
import sys
import logging
import json
from typing import Any, List, Optional
from mcp.server import Server, NotificationOptions
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from mcp.server.models import InitializationOptions
import mcp.types as types
import uvicorn
import httpx
import socket
import time as time_module
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

load_dotenv()

REGISTRY_URL = os.getenv("MCP_REGISTRY_URL", "http://mcp-registry:8010")
SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-chroma:8002/sse")
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
logger = logging.getLogger("mcp-chroma")

class ChromaMCPServer:
    def __init__(self, server_name: str = "mcp-chroma"):
        self.server_name = server_name
        logger.info(f"Initialized ChromaMCPServer helper: {server_name}")
        
    def _get_client(self):
        host = os.getenv("CHROMA_HOST", "localhost")
        port = os.getenv("CHROMA_PORT", "8000")
        return chromadb.HttpClient(host=host, port=int(port))

    async def _get_embedding_from_mcp(self, text: str) -> List[float]:
        try:
            import google.genai as genai
            from google.genai import types
            api_key = os.getenv("GEMINI_API_KEY")
            client = genai.Client(api_key=api_key)
            result = client.models.embed_content(
                model="text-embedding-004",
                contents=text,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.error(f"Failed to get embedding using SDK: {e}")
            raise

    def create_server(self) -> Server:
        server = Server(self.server_name)
        
        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="search_relevant_schema",
                    description="Search for relevant database schema parts",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The search query or keyword"},
                            "account_id": {"type": "string", "description": "The account ID to filter by"},
                            "n_results": {"type": "integer", "default": 2, "description": "Number of results to return"}
                        },
                        "required": ["query", "account_id"]
                    }
                )
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            start_time = time_module.time()
            status = "success"
            
            try:
                if name == "search_relevant_schema":
                    query = arguments["query"]
                    account_id = str(arguments["account_id"])
                    n_results = int(arguments.get("n_results", 2))
                    
                    # 1. Get embedding
                    embedding = await self._get_embedding_from_mcp(query)
                    
                    # 2. Query Chroma
                    client = self._get_client()
                    collection = client.get_or_create_collection(name="account_schema_info")
                    results = collection.query(
                        query_embeddings=[embedding],
                        n_results=n_results,
                        where={"account_id": account_id}
                    )
                    
                    if not results or not results.get('documents') or not results['documents'][0]:
                        result = [TextContent(type="text", text="No relevant schema found.")]
                    else:
                        docs = results['documents'][0]
                        formatted = "# Relevant Schema\n\n" + "\n".join(f"- {d}" for d in docs)
                        result = [TextContent(type="text", text=formatted)]
                else:
                    result = [TextContent(type="text", text=f"Unknown tool: {name}")]
                    status = "unknown"
                    
            except Exception as e:
                logger.exception(f"Error in chroma search: {e}")
                status = "error"
                result = [TextContent(type="text", text=f"Error: {str(e)}")]
            
            finally:
                duration = time_module.time() - start_time
                MCP_TOOL_CALLS.labels(tool_name=name, service='mcp-chroma', instance=INSTANCE_ID, status=status).inc()
                MCP_TOOL_DURATION.labels(tool_name=name, service='mcp-chroma').observe(duration)
            
            return result

        return server

mcp_server = ChromaMCPServer()
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
REQUEST_COUNT = Counter('mcp_chroma_requests_total', 'Total requests', ['method', 'endpoint'])
REQUEST_LATENCY = Histogram('mcp_chroma_request_duration_seconds', 'Request latency', ['endpoint'])

@app.get("/health")
async def health():
    REQUEST_COUNT.labels(method='GET', endpoint='/health').inc()
    return {"status": "healthy", "server": "mcp-chroma"}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

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
    uvicorn.run(app, host="0.0.0.0", port=8002)
