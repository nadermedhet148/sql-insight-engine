"""
MCP Client for connecting to database MCP servers
Used by the agent to interact with user databases
"""
import asyncio
import subprocess
import sys
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class MCPToolResult:
    """Result from an MCP tool call"""
    success: bool
    content: str
    error: Optional[str] = None


class DatabaseMCPClient:
    """
    MCP Client that connects to a PostgreSQL MCP server.
    Manages the server process and provides tool calling interface.
    """
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.process: Optional[subprocess.Popen] = None
        self._connected = False
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Return the list of available MCP tools"""
        return [
            {
                "name": "list_tables",
                "description": "List all tables in the database",
                "parameters": {
                    "schema": {"type": "string", "description": "Schema name (optional, default: public)"}
                }
            },
            {
                "name": "describe_table", 
                "description": "Get detailed schema information about a specific table including columns, types, and constraints",
                "parameters": {
                    "table_name": {"type": "string", "description": "Name of the table to describe", "required": True},
                    "schema": {"type": "string", "description": "Schema name (optional)"}
                }
            },
            {
                "name": "get_schema_summary",
                "description": "Get a complete summary of the database schema including all tables, columns, and relationships",
                "parameters": {
                    "schema": {"type": "string", "description": "Schema name (optional)"}
                }
            },
            {
                "name": "run_query",
                "description": "Execute a read-only SQL SELECT query and return results",
                "parameters": {
                    "query": {"type": "string", "description": "SQL SELECT query to execute", "required": True}
                }
            }
        ]
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPToolResult:
        """
        Call an MCP tool directly (synchronous interface for agent use).
        This uses direct SQLAlchemy calls internally for simplicity.
        """
        from sqlalchemy import create_engine, inspect, text
        
        try:
            engine = create_engine(self.db_url, pool_pre_ping=True)
            inspector = inspect(engine)
            
            if tool_name == "list_tables":
                schema = arguments.get("schema", None)
                tables = inspector.get_table_names(schema=schema)
                return MCPToolResult(
                    success=True,
                    content="Tables in database:\n" + "\n".join(f"- {t}" for t in tables)
                )
            
            elif tool_name == "describe_table":
                table_name = arguments.get("table_name")
                if not table_name:
                    return MCPToolResult(success=False, content="", error="table_name is required")
                
                schema = arguments.get("schema", None)
                
                columns = inspector.get_columns(table_name, schema=schema)
                pk = inspector.get_pk_constraint(table_name, schema=schema)
                fks = inspector.get_foreign_keys(table_name, schema=schema)
                indexes = inspector.get_indexes(table_name, schema=schema)
                
                result = f"## Table: {table_name}\n\n"
                result += "### Columns:\n"
                for col in columns:
                    nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
                    result += f"- **{col['name']}**: {col['type']} ({nullable})\n"
                
                result += f"\n### Primary Key: {', '.join(pk.get('constrained_columns', []))}\n"
                
                if fks:
                    result += "\n### Foreign Keys:\n"
                    for fk in fks:
                        result += f"- {', '.join(fk['constrained_columns'])} → {fk['referred_table']}({', '.join(fk['referred_columns'])})\n"
                
                if indexes:
                    result += "\n### Indexes:\n"
                    for idx in indexes:
                        unique = "UNIQUE " if idx.get("unique") else ""
                        result += f"- {unique}{idx['name']}: ({', '.join(idx['column_names'])})\n"
                
                return MCPToolResult(success=True, content=result)
            
            elif tool_name == "get_schema_summary":
                schema = arguments.get("schema", None)
                tables = inspector.get_table_names(schema=schema)
                
                result = f"# Database Schema Summary\n\n"
                result += f"**Total Tables:** {len(tables)}\n\n"
                
                for table in tables:
                    columns = inspector.get_columns(table, schema=schema)
                    pk = inspector.get_pk_constraint(table, schema=schema)
                    
                    result += f"## {table}\n"
                    result += f"Columns: {len(columns)} | "
                    result += f"PK: {', '.join(pk.get('constrained_columns', ['none']))}\n"
                    for col in columns:
                        result += f"  - {col['name']}: {col['type']}\n"
                    result += "\n"
                
                return MCPToolResult(success=True, content=result)
            
            elif tool_name == "run_query":
                query = arguments.get("query", "").strip()
                
                if not query:
                    return MCPToolResult(success=False, content="", error="query is required")
                
                # Security: Only allow SELECT queries
                if not query.upper().startswith("SELECT"):
                    return MCPToolResult(
                        success=False,
                        content="",
                        error="Only SELECT queries are allowed for security reasons."
                    )
                
                with engine.connect() as conn:
                    result = conn.execute(text(query))
                    columns = list(result.keys())
                    rows = result.fetchall()
                    
                    if not rows:
                        return MCPToolResult(success=True, content="Query returned no results.")
                    
                    # Format as markdown table
                    output = "| " + " | ".join(columns) + " |\n"
                    output += "| " + " | ".join(["---"] * len(columns)) + " |\n"
                    for row in rows[:100]:  # Limit to 100 rows
                        output += "| " + " | ".join(str(v) for v in row) + " |\n"
                    
                    if len(rows) > 100:
                        output += f"\n*...{len(rows) - 100} more rows*"
                    
                    return MCPToolResult(success=True, content=output)
            
            elif tool_name == "get_foreign_keys":
                table_name = arguments.get("table_name")
                if not table_name:
                    return MCPToolResult(success=False, content="", error="table_name is required")
                
                schema = arguments.get("schema", None)
                fks = inspector.get_foreign_keys(table_name, schema=schema)
                
                if not fks:
                    return MCPToolResult(
                        success=True,
                        content=f"No foreign keys found for table {table_name}"
                    )
                
                result = f"## Foreign Keys for {table_name}\n\n"
                for fk in fks:
                    result += f"- **{fk.get('name', 'unnamed')}**: "
                    result += f"{', '.join(fk['constrained_columns'])} → "
                    result += f"{fk['referred_table']}({', '.join(fk['referred_columns'])})\n"
                
                return MCPToolResult(success=True, content=result)
            
            else:
                return MCPToolResult(
                    success=False,
                    content="",
                    error=f"Unknown tool: {tool_name}"
                )
                
        except Exception as e:
            return MCPToolResult(success=False, content="", error=str(e))
        finally:
            if 'engine' in locals():
                engine.dispose()


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
