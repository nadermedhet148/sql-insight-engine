import asyncio
import subprocess
import sys
import os
import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass
class MCPToolResult:
    """Result from an MCP tool call"""
    success: bool
    content: str
    error: Optional[str] = None


class GenericMCPClient:
    """Base class for MCP clients communicating via stdio"""
    def __init__(self, command: str, args: List[str], env: Optional[Dict[str, str]] = None):
        self.server_params = StdioServerParameters(
            command=command,
            args=args,
            env={**os.environ, **(env or {}), "PYTHONPATH": f"{os.getcwd()}/src:{os.getcwd()}"}
        )
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], message: Any = None) -> MCPToolResult:
        import time
        start_time = time.time()
        try:
            async with stdio_client(self.server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    # Filter out None or empty values from arguments to avoid schema validation errors
                    filtered_args = {k: v for k, v in arguments.items() if v is not None and v != ""}
                    result = await session.call_tool(tool_name, filtered_args)
                    
                    content_text = ""
                    for content in result.content:
                        if hasattr(content, "text"):
                            content_text += content.text
                            
                    duration_ms = (time.time() - start_time) * 1000
                    
                    mcp_result = MCPToolResult(
                        success=not result.isError if hasattr(result, "isError") else True,
                        content=content_text
                    )

                    if message and hasattr(message, "track_tool_call"):
                        message.track_tool_call(
                            tool=tool_name,
                            args=filtered_args,
                            response=content_text,
                            duration_ms=duration_ms,
                            status="success" if mcp_result.success else "error"
                        )

                    return mcp_result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            if message and hasattr(message, "track_tool_call"):
                message.track_tool_call(
                    tool=tool_name,
                    args=arguments,
                    response=str(e),
                    duration_ms=duration_ms,
                    status="error"
                )
            return MCPToolResult(success=False, content="", error=str(e))


class DatabaseMCPClient(GenericMCPClient):
    """MCP Client for the Postgres server"""
    def __init__(self, db_url: str):
        super().__init__(
            command=sys.executable,
            args=["src/core/mcp/postgres_mcp.py"],
            env={"MCP_DB_URL": db_url}
        )


class ChromaMCPClient(GenericMCPClient):
    """MCP Client for the Chroma schema search server"""
    def __init__(self):
        super().__init__(
            command=sys.executable,
            args=["src/core/mcp/chroma_mcp.py"]
        )

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Return the list of available MCP tools (standard Postgres set)"""
        return [
            {"name": "list_tables", "description": "List all tables"},
            {"name": "describe_table", "description": "Get table schema", "parameters": {"table_name": "string"}},
            {"name": "get_schema_summary", "description": "Get full schema summary"},
            {"name": "run_query", "description": "Run SELECT query", "parameters": {"query": "string"}}
        ]


def create_mcp_client_from_config(db_config) -> DatabaseMCPClient:
    """Create an MCP client from a UserDBConfig object"""
    from core.mcp.postgres_mcp import build_connection_url
    
    db_url = build_connection_url(
        db_type=db_config.db_type,
        host=db_config.host,
        port=getattr(db_config, 'port', None) or 5432,
        db_name=db_config.db_name,
        username=db_config.username,
        password=db_config.password
    )
    return DatabaseMCPClient(db_url)
