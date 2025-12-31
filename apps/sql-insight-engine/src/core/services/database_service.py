import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from core.mcp.client import mcp_manager, MCPToolResult

@dataclass
class DatabaseOperationResult:
    """Result from a database operation"""
    success: bool
    data: str
    error: Optional[str] = None

class DatabaseService:
    """
    Handles database introspection and querying operations.
    Acts as a synchronous wrapper around the asynchronous MCP clients.
    """
    
    def _run_async(self, coro):
        """Helper to run async coroutines in a synchronous context"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            
        return loop.run_until_complete(coro)

    async def _call_tool_async(self, db_config, tool_name: str, arguments: Dict[str, Any]) -> MCPToolResult:
        """Helper to call an MCP tool asynchronously with db context"""
        db_url = f"postgresql://{db_config.username}:{db_config.password}@{db_config.host}:{db_config.port or 5432}/{db_config.db_name}"
        
        # Ensure tools are refreshed
        if not mcp_manager.tools_map:
            await mcp_manager.refresh_tools()
            
        if tool_name not in mcp_manager.tools_map:
            return MCPToolResult(success=False, content="", error=f"Tool {tool_name} not found")
            
        mcp_client, _ = mcp_manager.tools_map[tool_name]
        
        # Inject db_url
        arguments["db_url"] = db_url
        
        return await mcp_client.call_tool(tool_name, arguments)

    def execute_query(self, db_config, query: str) -> DatabaseOperationResult:
        """Execute a SQL SELECT query via MCP tool"""
        try:
            result = self._run_async(self._call_tool_async(db_config, "run_query", {"query": query}))
            return DatabaseOperationResult(
                success=result.success,
                data=result.content,
                error=result.error
            )
        except Exception as e:
            return DatabaseOperationResult(success=False, data="", error=str(e))

    def get_table_names(self, db_config) -> List[str]:
        """Get list of table names via MCP tool"""
        try:
            result = self._run_async(self._call_tool_async(db_config, "list_tables", {}))
            
            if result.success:
                print(f"[DEBUG] MCP Result Content: {result.content!r}")
                # Basic parsing of the markdown-like output from mcp-postgres
                lines = result.content.split('\n')
                tables = []
                for line in lines:
                    line = line.strip()
                    if line.startswith("- "):
                        tables.append(line.strip("- ").strip())
                return tables
            return []
        except Exception as e:
            print(f"Warning: Failed to get table names: {e}")
            return []

    def describe_table(self, db_config, table_name: str) -> DatabaseOperationResult:
        """Get detailed schema for a table via MCP tool"""
        try:
            result = self._run_async(self._call_tool_async(db_config, "describe_table", {"table_name": table_name}))
            return DatabaseOperationResult(
                success=result.success,
                data=result.content,
                error=result.error
            )
        except Exception as e:
            return DatabaseOperationResult(success=False, data="", error=str(e))

# Singleton instance
database_service = DatabaseService()
