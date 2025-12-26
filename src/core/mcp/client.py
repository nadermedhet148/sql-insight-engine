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

                    print(f"[MCP] Tool {tool_name} call {'success' if mcp_result.success else 'failed'} in {duration_ms:.2f}ms")
                    if not mcp_result.success:
                        print(f"[MCP] Tool Error: {content_text}")

                    if message and hasattr(message, "track_tool_call"):
                        print(f"[MCP] Tracking tool call {tool_name} on message {type(message).__name__}")
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

    def _run_tool_sync(self, tool_name: str, kwargs: Dict[str, Any], message: Any = None) -> str:
        import nest_asyncio
        import asyncio
        
        try:
            nest_asyncio.apply()
        except:
            pass
            
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Inject account_id if available in message and expected by tool
        if message and hasattr(message, 'account_id') and tool_name in ["search_relevant_schema", "search_business_knowledge"]:
            kwargs["account_id"] = message.account_id
            
        res = loop.run_until_complete(self.call_tool(tool_name, kwargs, message=message))
        return res.content if res.success else f"Error: {res.error}"

    def get_gemini_tool(self, tool_name: str, message: Any = None):
        
        if tool_name == "search_relevant_schema":
            def search_relevant_schema(query: str, n_results: int = 2) -> str:
                return self._run_tool_sync("search_relevant_schema", {"query": query, "n_results": int(n_results)}, message)
            return search_relevant_schema
            
        elif tool_name == "search_business_knowledge":
            def search_business_knowledge(query: str, n_results: int = 1) -> str:
                return self._run_tool_sync("search_business_knowledge", {"query": query, "n_results": int(n_results)}, message)
            return search_business_knowledge
            
        elif tool_name == "list_tables":
            def list_tables(schema: str = "public") -> str:
                return self._run_tool_sync("list_tables", {"schema": schema}, message)
            return list_tables
            
        elif tool_name == "describe_table":
            def describe_table(table_name: str, schema: str = "public") -> str:
         
                return self._run_tool_sync("describe_table", {"table_name": table_name, "schema": schema}, message)
            return describe_table
            
        elif tool_name == "get_schema_summary":
            def get_schema_summary(schema: str = "public") -> str:
     
                return self._run_tool_sync("get_schema_summary", {"schema": schema}, message)
            return get_schema_summary
            
        elif tool_name == "run_query":
            def run_query(query: str) -> str:
                return self._run_tool_sync("run_query", {"query": query}, message)
            return run_query
            
        # Fallback for unknown tools
        def tool_wrapper(**kwargs) -> str:
            return self._run_tool_sync(tool_name, kwargs, message)
        tool_wrapper.__name__ = tool_name
        return tool_wrapper


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
        """Return the list of available MCP tools for Chroma"""
        return [
            {
                "name": "search_relevant_schema", 
                "description": "Search for relevant database schema parts (tables/columns) based on a semantic query.", 
                "parameters": {
                    "query": "string", 
                    "account_id": "string",
                    "n_results": "integer"
                }
            },
            {
                "name": "search_business_knowledge", 
                "description": "Search for business rules, definitions, or organizational knowledge relevant to the query.", 
                "parameters": {
                    "query": "string", 
                    "account_id": "string",
                    "n_results": "integer"
                }
            }
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
