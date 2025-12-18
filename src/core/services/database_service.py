"""
Database Service Layer
Provides a clean abstraction for database operations without exposing MCP implementation details.
"""
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
    Abstracts away the underlying implementation (MCP, direct SQLAlchemy, etc.)
    """
    
    def get_schema_summary(self, db_config, schema: Optional[str] = None) -> DatabaseOperationResult:
        """
        Get a complete summary of the database schema.
        
        Args:
            db_config: UserDBConfig object containing database connection details
            schema: Optional schema name to filter by
            
        Returns:
            DatabaseOperationResult with schema summary in markdown format
        """
        from core.mcp.client import create_mcp_client_from_config
        
        try:
            client = create_mcp_client_from_config(db_config)
            arguments = {}
            if schema:
                arguments["schema"] = schema
                
            result = client.call_tool("get_schema_summary", arguments)
            return DatabaseOperationResult(
                success=result.success,
                data=result.content,
                error=result.error
            )
        except Exception as e:
            return DatabaseOperationResult(
                success=False,
                data="",
                error=f"Failed to get schema summary: {str(e)}"
            )
    
    def list_tables(self, db_config, schema: Optional[str] = None) -> DatabaseOperationResult:
        """
        List all tables in the database.
        
        Args:
            db_config: UserDBConfig object containing database connection details
            schema: Optional schema name to filter by
            
        Returns:
            DatabaseOperationResult with list of tables
        """
        from core.mcp.client import create_mcp_client_from_config
        
        try:
            client = create_mcp_client_from_config(db_config)
            arguments = {}
            if schema:
                arguments["schema"] = schema
                
            result = client.call_tool("list_tables", arguments)
            return DatabaseOperationResult(
                success=result.success,
                data=result.content,
                error=result.error
            )
        except Exception as e:
            return DatabaseOperationResult(
                success=False,
                data="",
                error=f"Failed to list tables: {str(e)}"
            )
    
    def describe_table(self, db_config, table_name: str, schema: Optional[str] = None) -> DatabaseOperationResult:
        """
        Get detailed schema information about a specific table.
        
        Args:
            db_config: UserDBConfig object containing database connection details
            table_name: Name of the table to describe
            schema: Optional schema name
            
        Returns:
            DatabaseOperationResult with table details including columns, types, and constraints
        """
        from core.mcp.client import create_mcp_client_from_config
        
        try:
            client = create_mcp_client_from_config(db_config)
            arguments = {"table_name": table_name}
            if schema:
                arguments["schema"] = schema
                
            result = client.call_tool("describe_table", arguments)
            return DatabaseOperationResult(
                success=result.success,
                data=result.content,
                error=result.error
            )
        except Exception as e:
            return DatabaseOperationResult(
                success=False,
                data="",
                error=f"Failed to describe table: {str(e)}"
            )
    
    def execute_query(self, db_config, query: str) -> DatabaseOperationResult:
        """
        Execute a read-only SQL SELECT query.
        
        Args:
            db_config: UserDBConfig object containing database connection details
            query: SQL SELECT query to execute
            
        Returns:
            DatabaseOperationResult with query results in markdown table format
        """
        from core.mcp.client import create_mcp_client_from_config
        
        try:
            client = create_mcp_client_from_config(db_config)
            result = client.call_tool("run_query", {"query": query})
            return DatabaseOperationResult(
                success=result.success,
                data=result.content,
                error=result.error
            )
        except Exception as e:
            return DatabaseOperationResult(
                success=False,
                data="",
                error=f"Failed to execute query: {str(e)}"
            )
    
    def get_foreign_keys(self, db_config, table_name: str, schema: Optional[str] = None) -> DatabaseOperationResult:
        """
        Get foreign key relationships for a specific table.
        
        Args:
            db_config: UserDBConfig object containing database connection details
            table_name: Name of the table
            schema: Optional schema name
            
        Returns:
            DatabaseOperationResult with foreign key information
        """
        from core.mcp.client import create_mcp_client_from_config
        
        try:
            client = create_mcp_client_from_config(db_config)
            arguments = {"table_name": table_name}
            if schema:
                arguments["schema"] = schema
                
            result = client.call_tool("get_foreign_keys", arguments)
            return DatabaseOperationResult(
                success=result.success,
                data=result.content,
                error=result.error
            )
        except Exception as e:
            return DatabaseOperationResult(
                success=False,
                data="",
                error=f"Failed to get foreign keys: {str(e)}"
            )
    
    def get_table_names(self, db_config, schema: Optional[str] = None) -> List[str]:
        """
        Get a list of table names from the database.
        
        Args:
            db_config: UserDBConfig object containing database connection details
            schema: Optional schema name to filter by
            
        Returns:
            List of table names, or empty list if operation fails
        """
        from sqlalchemy import create_engine, inspect
        from core.mcp.postgres_mcp import build_connection_url
        
        try:
            db_url = build_connection_url(
                db_type=db_config.db_type,
                host=db_config.host,
                port=getattr(db_config, 'port', None) or 5432,
                db_name=db_config.db_name,
                username=db_config.username,
                password=db_config.password
            )
            engine = create_engine(db_url, pool_pre_ping=True)
            inspector = inspect(engine)
            tables = inspector.get_table_names(schema=schema)
            engine.dispose()
            return tables
        except Exception as e:
            print(f"Warning: Failed to get table names: {e}")
            return []


# Singleton instance for convenience
database_service = DatabaseService()
