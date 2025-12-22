"""
MCP Server for ChromaDB Schema Search
Provides tools for semantic search of relevant database schema information.
"""
import asyncio
import os
import sys
import logging
from typing import Any, List, Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from core.infra.chroma_factory import ChromaClientFactory
from core.gemini_client import GeminiClient

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("chroma-mcp")

class ChromaMCPServer:
    def __init__(self, server_name: str = "chroma-schema-search"):
        self.server_name = server_name
        self.server = Server(server_name)
        self.gemini_client = GeminiClient()
        self._setup_tools()
        logger.info(f"Initialized ChromaMCPServer: {server_name}")
        
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
                                "description": "Number of results to return (default: 2)",
                                "default": 2
                            }
                        },
                        "required": ["query", "account_id"]
                    }
                ),
                Tool(
                    name="search_business_knowledge",
                    description="Search for business rules, definitions, or organizational knowledge relevant to the query. Use this if the user uses business terms that aren't clear from the table names alone, and you should send the user query so we can found the revelevent data",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "A precise, keyword-focused semantic search string extracted from the user's question. Do not include phrases like 'I need to find' or 'search for'. Just the topic."
                            },
                            "account_id": {
                                "type": "string",
                                "description": "The account ID to scope the search to"
                            },
                            "n_results": {
                                "type": "integer",
                                "description": "Number of results to return (default: 1)",
                                "default": 1
                            }
                        },
                        "required": ["query", "account_id"]
                    }
                )
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            logger.info(f"Tool called: {name} with arguments: {arguments}")
            if name == "search_relevant_schema":
                return await self._handle_search(arguments, "account_schema_info", "# Relevant Schema Information")
            elif name == "search_business_knowledge":
                return await self._handle_search(arguments, "knowledgebase", "# Business Knowledge Context")
            
            logger.error(f"Unknown tool: {name}")
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def _handle_search(self, arguments: dict, collection_name: str, title: str) -> list[TextContent]:
        query = arguments["query"]
        account_id = str(arguments["account_id"])
        n_results = int(arguments.get("n_results", 2 if collection_name == "account_schema_info" else 1))
        
        try:
            chroma_client = ChromaClientFactory.get_client()
            collection = chroma_client.get_or_create_collection(name=collection_name)
            
            # Generate embedding
            query_embedding = self.gemini_client.get_embedding(query, task_type="retrieval_query")
            
            # Query Chroma
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where={"account_id": account_id}
            )
            print(results)
            if not results or not results.get('documents') or not results['documents'][0]:
                logger.info(f"No results found in {collection_name} for query: {query}")
                return [TextContent(type="text", text=f"No relevant items found in {collection_name} for this query.")]
            
            context_docs = results['documents'][0]
            logger.info(f"Found {len(context_docs)} results in {collection_name}")
            formatted_results = f"{title}\n\n"
            for idx, doc in enumerate(context_docs):
                formatted_results += f"### Result {idx+1}:\n{doc}\n\n"
                
            return [TextContent(type="text", text=formatted_results)]
            
        except Exception as e:
            logger.exception(f"Error searching {collection_name}: {str(e)}")
            return [TextContent(type="text", text=f"Error searching {collection_name}: {str(e)}")]

    async def run(self):
        """Run the MCP server via stdio"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream, self.server.create_initialization_options())

if __name__ == "__main__":
    server = ChromaMCPServer()
    async def main():
        await server.run()
    asyncio.run(main())
