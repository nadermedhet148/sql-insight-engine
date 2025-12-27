import asyncio
import os
import sys
import logging
from typing import Any, Optional, Dict
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv
from fastapi import FastAPI, Request
import uvicorn

load_dotenv()

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
        self.server = Server(server_name)
        self.engines: Dict[str, Any] = {}
        self._setup_tools()
        logger.info(f"Initialized PostgresMCPServer: {server_name}")
    
    def _get_engine(self, db_url: str):
        if db_url not in self.engines:
            self.engines[db_url] = create_engine(db_url, pool_pre_ping=True)
        return self.engines[db_url]
    
    def _setup_tools(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="list_tables",
                    description="List all tables in the database",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "db_url": {"type": "string"},
                            "schema": {"type": "string", "default": "public"}
                        },
                        "required": ["db_url"]
                    }
                ),
                Tool(
                    name="describe_table",
                    description="Get detailed schema information about a specific table",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "db_url": {"type": "string"},
                            "table_name": {"type": "string"},
                            "schema": {"type": "string", "default": "public"}
                        },
                        "required": ["db_url", "table_name"]
                    }
                ),
                Tool(
                    name="run_query",
                    description="Execute a read-only SQL SELECT query",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "db_url": {"type": "string"},
                            "query": {"type": "string"}
                        },
                        "required": ["db_url", "query"]
                    }
                )
            ]
        
        @self.server.call_tool()
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
                
                elif name == "run_query":
                    query = arguments["query"].strip()
                    if not query.upper().startswith("SELECT"):
                        return [TextContent(type="text", text="Error: Only SELECT queries allowed")]
                    
                    with engine.connect() as conn:
                        result = conn.execute(text(query))
                        columns = list(result.keys())
                        rows = result.fetchall()
                        output = "| " + " | ".join(columns) + " |\n| " + " | ".join(["---"] * len(columns)) + " |\n"
                        for row in rows[:50]:
                            output += "| " + " | ".join(str(v) for v in row) + " |\n"
                        return [TextContent(type="text", text=output)]

            except Exception as e:
                logger.exception(f"Error in {name}: {str(e)}")
                return [TextContent(type="text", text=f"Error: {str(e)}")]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

mcp_server = PostgresMCPServer()
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
    uvicorn.run(app, host="0.0.0.0", port=8001)
