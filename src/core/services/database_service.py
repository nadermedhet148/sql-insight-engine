import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

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
            # If we are already in an event loop (like in some async frameworks)
            # we might need a different approach, but for RabbitMQ consumers this is fine.
            import nest_asyncio
            nest_asyncio.apply()
            
        return loop.run_until_complete(coro)

    def execute_query(self, db_config, query: str, message: Any = None) -> DatabaseOperationResult:
        """Execute a SQL SELECT query via MCP tool"""
        from core.mcp.client import create_mcp_client_from_config
        
        try:
            client = create_mcp_client_from_config(db_config)
            result = self._run_async(client.call_tool("run_query", {"query": query}, message=message))
            return DatabaseOperationResult(
                success=result.success,
                data=result.content,
                error=result.error
            )
        except Exception as e:
            return DatabaseOperationResult(success=False, data="", error=str(e))

    def get_table_names(self, db_config, schema: Optional[str] = None, message: Any = None) -> List[str]:
        """Get list of table names via MCP tool"""
        from core.mcp.client import create_mcp_client_from_config
        
        try:
            client = create_mcp_client_from_config(db_config)
            args = {}
            if schema:
                args["schema"] = schema
                
            result = self._run_async(client.call_tool("list_tables", args, message=message))
            
            print(f"\n{'='*50}\n[DEBUG] RAW MCP RESPONSE FOR list_tables:\n{result.content}\n{'='*50}\n")
            if result.success and "Tables in database:" in result.content:
                # Basic parsing of the markdown-like output
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
    def describe_table(self, db_config, table_name: str, message: Any = None) -> DatabaseOperationResult:
        """Get detailed schema for a table via MCP tool"""
        from core.mcp.client import create_mcp_client_from_config
        
        try:
            client = create_mcp_client_from_config(db_config)
            result = self._run_async(client.call_tool("describe_table", {"table_name": table_name}, message=message))
            return DatabaseOperationResult(
                success=result.success,
                data=result.content,
                error=result.error
            )
        except Exception as e:
            return DatabaseOperationResult(success=False, data="", error=str(e))

# Singleton instance
database_service = DatabaseService()
