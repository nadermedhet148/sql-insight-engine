"""
MCP Server for PostgreSQL Database
Provides tools for schema discovery and query execution using the MCP protocol
"""
import asyncio
from typing import Any, Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from sqlalchemy import create_engine, inspect, text


class PostgresMCPServer:
    def __init__(self, db_url: str, server_name: str = "postgres-db"):
        self.db_url = db_url
        self.server_name = server_name
        self.engine = None
        self.server = Server(server_name)
        self._setup_tools()
    
    def _connect(self):
        if not self.engine:
            self.engine = create_engine(self.db_url, pool_pre_ping=True)
        return self.engine
    
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
                            "schema": {
                                "type": "string",
                                "description": "Schema name (default: public)"
                            }
                        }
                    }
                ),
                Tool(
                    name="describe_table",
                    description="Get detailed schema information about a specific table including columns, types, and constraints",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Name of the table to describe"
                            },
                            "schema": {
                                "type": "string",
                                "description": "Schema name (default: public)"
                            }
                        },
                        "required": ["table_name"]
                    }
                ),
                Tool(
                    name="get_schema_summary",
                    description="Get a complete summary of the database schema including all tables, columns, and relationships",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "schema": {
                                "type": "string",
                                "description": "Schema name (default: public)"
                            }
                        }
                    }
                ),
                Tool(
                    name="run_query",
                    description="Execute a read-only SQL SELECT query and return results",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "SQL SELECT query to execute"
                            }
                        },
                        "required": ["query"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            engine = self._connect()
            inspector = inspect(engine)
            
            if name == "list_tables":
                schema = arguments.get("schema", None)
                tables = inspector.get_table_names(schema=schema)
                return [TextContent(
                    type="text",
                    text=f"Tables in database:\n" + "\n".join(f"- {t}" for t in tables)
                )]
            
            elif name == "describe_table":
                table_name = arguments["table_name"]
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
                
                return [TextContent(type="text", text=result)]
            
            elif name == "get_schema_summary":
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
                
                return [TextContent(type="text", text=result)]
            
            elif name == "run_query":
                query = arguments["query"].strip()
                
                if not query.upper().startswith("SELECT"):
                    return [TextContent(
                        type="text",
                        text="Error: Only SELECT queries are allowed for security reasons."
                    )]
                
                try:
                    with engine.connect() as conn:
                        result = conn.execute(text(query))
                        columns = list(result.keys())
                        rows = result.fetchall()
                        
                        if not rows:
                            return [TextContent(type="text", text="Query returned no results.")]
                        
                        output = "| " + " | ".join(columns) + " |\n"
                        output += "| " + " | ".join(["---"] * len(columns)) + " |\n"
                        for row in rows[:100]:  # Limit to 100 rows
                            output += "| " + " | ".join(str(v) for v in row) + " |\n"
                        
                        if len(rows) > 100:
                            output += f"\n*...{len(rows) - 100} more rows*"
                        
                        return [TextContent(type="text", text=output)]
                        
                except Exception as e:
                    return [TextContent(type="text", text=f"Query error: {str(e)}")]
            
            
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    async def run(self):
        """Run the MCP server via stdio"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream, self.server.create_initialization_options())


def build_connection_url(db_type: str, host: str, port: int, db_name: str, username: str, password: str) -> str:
    if db_type == "postgresql":
        return f"postgresql://{username}:{password}@{host}:{port or 5432}/{db_name}"
    elif db_type == "mysql":
        return f"mysql+pymysql://{username}:{password}@{host}:{port or 3306}/{db_name}"
    else:
        return f"postgresql://{username}:{password}@{host}:{port or 5432}/{db_name}"


if __name__ == "__main__":
    import os
    import sys
    
    # Get DB URL from env or fallback to argument
    db_url = os.getenv("MCP_DB_URL")
    if not db_url:
        print("Error: MCP_DB_URL environment variable is required", file=sys.stderr)
        sys.exit(1)
        
    server = PostgresMCPServer(db_url)
    
    async def main():
        await server.run()
        
    asyncio.run(main())
