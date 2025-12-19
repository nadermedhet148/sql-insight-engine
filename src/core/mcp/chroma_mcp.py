"""
MCP Server for ChromaDB Schema Search
Provides tools for semantic search of relevant database schema information.
"""
import asyncio
import os
import sys
from typing import Any, List, Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from core.infra.chroma_factory import ChromaClientFactory
from core.gemini_client import GeminiClient

class ChromaMCPServer:
    def __init__(self, server_name: str = "chroma-schema-search"):
        self.server_name = server_name
        self.server = Server(server_name)
        self.gemini_client = GeminiClient()
        self._setup_tools()
        
    def _get_collection(self, account_id: str):
        chroma_client = ChromaClientFactory.get_client()
        return chroma_client.get_or_create_collection(
            name="account_schema_info",
            metadata={"hnsw:space": "cosine"}
        )

    def _setup_tools(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="search_relevant_schema",
                    description="Search for relevant database schema parts (tables/columns) based on a semantic query. Use this when you have many tables and need to find which ones are relevant to a question.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The semantic search query (e.g., 'customer orders and payments')"
                            },
                            "account_id": {
                                "type": "string",
                                "description": "The account ID to scope the search to"
                            },
                            "n_results": {
                                "type": "integer",
                                "description": "Number of results to return (default: 5)",
                                "default": 5
                            }
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
                n_results = arguments.get("n_results", 5)
                
                try:
                    collection = self._get_collection(account_id)
                    
                    # Generate embedding
                    query_embedding = self.gemini_client.get_embedding(query, task_type="retrieval_query")
                    
                    # Query Chroma
                    results = collection.query(
                        query_embeddings=[query_embedding],
                        n_results=n_results,
                        where={"account_id": account_id}
                    )
                    
                    if not results or not results.get('documents') or not results['documents'][0]:
                        return [TextContent(type="text", text="No relevant schema information found for this query.")]
                    
                    context_docs = results['documents'][0]
                    formatted_results = "# Relevant Schema Information\n\n"
                    for idx, doc in enumerate(context_docs):
                        formatted_results += f"### Result {idx+1}:\n{doc}\n\n"
                        
                    return [TextContent(type="text", text=formatted_results)]
                    
                except Exception as e:
                    return [TextContent(type="text", text=f"Error searching schema: {str(e)}")]
            
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def run(self):
        """Run the MCP server via stdio"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream, self.server.create_initialization_options())

if __name__ == "__main__":
    server = ChromaMCPServer()
    async def main():
        await server.run()
    asyncio.run(main())
