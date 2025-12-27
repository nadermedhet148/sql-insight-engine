import asyncio
import os
import sys
import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from mcp import ClientSession
from mcp.client.sse import sse_client

@dataclass
class MCPToolResult:
    success: bool
    content: str
    error: Optional[str] = None

class GenericMCPClient:
    def __init__(self, sse_url: str):
        self.sse_url = sse_url
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], message: Any = None) -> MCPToolResult:
        import time
        start_time = time.time()
        try:
            async with sse_client(self.sse_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    # Filter out None or empty values from arguments
                    filtered_args = {k: v for k, v in arguments.items() if v is not None}
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

                    print(f"[MCP-SSE] Tool {tool_name} call {'success' if mcp_result.success else 'failed'} in {duration_ms:.2f}ms")
                    return mcp_result
        except Exception as e:
            return MCPToolResult(success=False, content="", error=str(e))

    def _run_tool_sync(self, tool_name: str, kwargs: Dict[str, Any], message: Any = None) -> str:
        import nest_asyncio
        try:
            nest_asyncio.apply()
        except:
            pass
            
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        res = loop.run_until_complete(self.call_tool(tool_name, kwargs, message=message))
        return res.content if res.success else f"Error: {res.error}"

class DatabaseMCPClient(GenericMCPClient):
    def __init__(self, db_url: str):
        url = os.getenv("POSTGRES_MCP_URL", "http://mcp-postgres:8001/sse")
        super().__init__(url)
        self.db_url = db_url

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], message: Any = None) -> MCPToolResult:
        arguments["db_url"] = self.db_url
        return await super().call_tool(tool_name, arguments, message)

class ChromaMCPClient(GenericMCPClient):
    def __init__(self):
        url = os.getenv("CHROMA_MCP_URL", "http://mcp-chroma:8002/sse")
        super().__init__(url)

def create_mcp_client_from_config(db_config) -> DatabaseMCPClient:
    try:
        from core.mcp.postgres_mcp import build_connection_url
    except ImportError:
        # Fallback if the file was moved or renamed
        def build_connection_url(db_type, host, port, db_name, username, password):
            return f"postgresql://{username}:{password}@{host}:{port or 5432}/{db_name}"
    
    db_url = build_connection_url(
        db_type=db_config.db_type,
        host=db_config.host,
        port=getattr(db_config, 'port', None) or 5432,
        db_name=db_config.db_name,
        username=db_config.username,
        password=db_config.password
    )
    return DatabaseMCPClient(db_url)
