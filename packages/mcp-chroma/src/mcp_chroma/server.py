import asyncio
import os
import sys
import logging
import json
from typing import Any, List, Optional
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI, Request
import uvicorn
import httpx

load_dotenv()

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
        self.server = Server(server_name)
        self.gemini_mcp_url = os.getenv("GEMINI_MCP_URL", "http://mcp-gemini:8003/sse")
        self._setup_tools()
        logger.info(f"Initialized ChromaMCPServer: {server_name}")
        
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
            logger.error(f"Failed to get embedding: {e}")
            raise

    def _setup_tools(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="search_relevant_schema",
                    description="Search for relevant database schema parts",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "account_id": {"type": "string"},
                            "n_results": {"type": "integer", "default": 2}
                        },
                        "required": ["query", "account_id"]
                    }
                )
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            if name == "search_relevant_schema":
                query = arguments["query"]
                account_id = str(arguments["account_id"])
                n_results = int(arguments.get("n_results", 2))
                
                try:
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
                        return [TextContent(type="text", text="No relevant schema found.")]
                    
                    docs = results['documents'][0]
                    formatted = "# Relevant Schema\n\n" + "\n".join(f"- {d}" for d in docs)
                    return [TextContent(type="text", text=formatted)]
                    
                except Exception as e:
                    logger.exception(f"Error in chroma search: {e}")
                    return [TextContent(type="text", text=f"Error: {str(e)}")]
            
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

mcp_server = ChromaMCPServer()
app = FastAPI()
sse = SseServerTransport("/messages")

@app.get("/sse")
async def handle_sse(request: Request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        await mcp_server.server.run(read_stream, write_stream, mcp_server.server.create_initialization_options())

@app.post("/messages")
async def handle_messages(request: Request):
    await sse.handle_post_message(request.scope, request.receive, request._send)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
