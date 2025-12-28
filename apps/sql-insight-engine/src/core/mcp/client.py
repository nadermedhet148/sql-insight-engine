import asyncio
import os
import sys
import json
import time
import httpx
import inspect
from typing import Any, Dict, List, Optional, Callable
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
    
    async def list_tools(self) -> List[Any]:
        print(f"[TRACE] list_tools for {self.sse_url}")
        try:
            async with sse_client(self.sse_url) as (read, write):
                print(f"[TRACE] SSE connected for {self.sse_url}")
                async with ClientSession(read, write) as session:
                    print(f"[TRACE] Session created, initializing... {self.sse_url}")
                    await asyncio.wait_for(session.initialize(), timeout=5.0)
                    print(f"[TRACE] Session initialized, listing tools... {self.sse_url}")
                    result = await asyncio.wait_for(session.list_tools(), timeout=5.0)
                    print(f"[TRACE] Tools listed for {self.sse_url}: {len(result.tools)}")
                    return result.tools
        except asyncio.TimeoutError:
            print(f"[TRACE] Timeout in list_tools for {self.sse_url}")
            return []
        except Exception as e:
            print(f"Error listing tools from {self.sse_url}: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPToolResult:
        start_time = time.time()
        try:
            async with sse_client(self.sse_url) as (read, write):
                async with ClientSession(read, write) as session:
                    print(f"[TRACE] session initializing for {tool_name}...")
                    await asyncio.wait_for(session.initialize(), timeout=5.0)
                    print(f"[TRACE] session initialized. calling {tool_name} with {arguments}...")
                    filtered_args = {k: v for k, v in arguments.items() if v is not None}
                    result = await asyncio.wait_for(session.call_tool(tool_name, filtered_args), timeout=30.0)
                    print(f"[TRACE] {tool_name} returned success.")
                    
                    content_text = ""
                    for content in result.content:
                        if hasattr(content, "text"):
                            content_text += content.text
                            
                    return MCPToolResult(
                        success=not result.isError if hasattr(result, "isError") else True,
                        content=content_text
                    )
        except asyncio.TimeoutError:
            return MCPToolResult(success=False, content="", error="MCP call timed out")
        except Exception as e:
            return MCPToolResult(success=False, content="", error=str(e))

class DynamicMCPManager:
    def __init__(self, registry_url: str = None):
        import os
        self.registry_url = registry_url or os.getenv("MCP_REGISTRY_URL", "http://mcp-registry:8010")
        self.clients: Dict[str, GenericMCPClient] = {}
        self.tools_map: Dict[str, tuple[GenericMCPClient, Any]] = {}  # tool_name -> (client, Tool object)

    async def refresh_tools(self, retries=3, delay=2):
        """Fetch all servers from registry and their tools with retries"""
        for attempt in range(retries):
            try:
                print(f"Refreshing MCP tools (attempt {attempt+1}/{retries})...")
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{self.registry_url}/servers", timeout=5.0)
                    if response.status_code != 200:
                        print(f"Failed to fetch servers from registry: {response.status_code}")
                        if attempt < retries - 1:
                            await asyncio.sleep(delay)
                            continue
                        return
                    
                    servers = response.json()
                    print(f"Registry returned {len(servers)} servers: {[s['name'] for s in servers]}")
                    
                    new_clients = {}
                    new_tools_map = {}
                    
                    for s in servers:
                        name = s["name"]
                        url = s["url"]
                        print(f"Connecting to MCP server: {name} at {url}")
                        mcp_client = GenericMCPClient(url)
                        new_clients[name] = mcp_client
                        
                        try:
                            tools = await mcp_client.list_tools()
                            print(f"Server {name} reported {len(tools)} tools")
                            for t in tools:
                                new_tools_map[t.name] = (mcp_client, t)
                                print(f"Discovered tool: {t.name} from {name}")
                        except Exception as e:
                            print(f"Failed to list tools from {name}: {e}")
                    
                    self.clients = new_clients
                    self.tools_map = new_tools_map
                    print(f"MCP Refresh complete. Total tools: {len(self.tools_map)}")
                    return # Success
                    
            except Exception as e:
                print(f"Error refreshing MCP tools: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
        
        print("Max retries reached for MCP refresh.")

    def get_gemini_tools(self, message: Any = None, context: Dict[str, Any] = None) -> List[Callable]:
        """Convert all discovered tools into Gemini-compatible functions"""
        gemini_tools = []
        
        for tool_name, (mcp_client, tool_def) in self.tools_map.items():
            def create_tool(name=tool_name, client=mcp_client, definition=tool_def):
                def tool_wrapper(**kwargs):
                    # Inject context if provided
                    if context:
                        for k, v in context.items():
                            # If the tool expects this argument and it's not provided
                            # (We assume it expects it if it's in context, for now)
                            if k not in kwargs or not kwargs[k]:
                                kwargs[k] = v

                    if message and hasattr(message, "add_tool_call"):
                        call_start = time.time()
                        try:
                            res = self._run_tool_sync(client, name, kwargs)
                            duration = (time.time() - call_start) * 1000
                            message.add_tool_call(name, kwargs, res, duration, "success")
                            return res
                        except Exception as e:
                            duration = (time.time() - call_start) * 1000
                            message.add_tool_call(name, kwargs, str(e), duration, "error")
                            raise e
                    else:
                        return self._run_tool_sync(client, name, kwargs)
                
                tool_wrapper.__name__ = name
                tool_wrapper.__doc__ = definition.description
                
                # Try to set a signature based on the inputSchema
                try:
                    params = []
                    properties = definition.inputSchema.get("properties", {})
                    required = definition.inputSchema.get("required", [])
                    
                    tool_annotations = {}
                    for p_name, p_info in properties.items():
                        # If it's in context, don't expose it to Gemini
                        if context and p_name in context:
                            continue
                            
                        # Default all to string for Gemini tools compatibility
                        params.append(inspect.Parameter(
                            p_name,
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            annotation=str
                        ))
                        tool_annotations[p_name] = str
                    
                    if params:
                        tool_wrapper.__signature__ = inspect.Signature(params)
                        tool_wrapper.__annotations__ = tool_annotations
                except Exception as e:
                    print(f"Failed to set signature for tool {name}: {e}")

                return tool_wrapper
            
            gemini_tools.append(create_tool())
            
        return gemini_tools

    def _run_tool_sync(self, client: GenericMCPClient, tool_name: str, kwargs: Dict[str, Any]) -> str:
        try:
            return asyncio.run(client.call_tool(tool_name, kwargs))
        except Exception as e:
            return f"Error: {e}"

# Global manager instance
mcp_manager = DynamicMCPManager()

async def initialize_mcp():
    await mcp_manager.refresh_tools()

def get_discovered_tools(message: Any = None, context: Dict[str, Any] = None) -> List[Callable]:
    """Helper to get tools from the global manager"""
    if not mcp_manager.tools_map:
        print("[DEBUG] No tools in map, attempting proactive refresh...")
        try:
            # We use a simplified refresh if we're already in a loop
            import nest_asyncio
            nest_asyncio.apply()
            asyncio.run(mcp_manager.refresh_tools(retries=1, delay=0.5))
        except Exception as e:
            print(f"[DEBUG] Proactive refresh failed: {e}")
    
    return mcp_manager.get_gemini_tools(message, context)

# Legacy compatibility (to be removed once consumers are updated)
class DatabaseMCPClient(GenericMCPClient):
    def __init__(self, db_url: str):
        url = os.getenv("POSTGRES_MCP_URL", "http://mcp-postgres:8001/sse")
        super().__init__(url)
        self.db_url = db_url

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPToolResult:
        arguments["db_url"] = self.db_url
        return await super().call_tool(tool_name, arguments)

class ChromaMCPClient(GenericMCPClient):
    def __init__(self):
        url = os.getenv("CHROMA_MCP_URL", "http://mcp-chroma:8002/sse")
        super().__init__(url)

def create_mcp_client_from_config(db_config) -> DatabaseMCPClient:
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
