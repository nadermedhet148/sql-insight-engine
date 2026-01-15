import asyncio
import os
import sys
import json
import time
import httpx
import inspect
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass
from mcp import ClientSession
from mcp.client.sse import sse_client

# Increased thread pool for better parallelism
_mcp_executor = ThreadPoolExecutor(max_workers=100, thread_name_prefix="mcp_tool_")

# Per-server connection limiting - increased for better throughput
_MAX_CONNECTIONS_PER_SERVER = 100
_server_semaphores: Dict[str, threading.Semaphore] = {}
_semaphore_lock = threading.Lock()

def _get_server_semaphore(sse_url: str) -> threading.Semaphore:
    """Get or create a semaphore for a specific MCP server URL."""
    with _semaphore_lock:
        if sse_url not in _server_semaphores:
            _server_semaphores[sse_url] = threading.Semaphore(_MAX_CONNECTIONS_PER_SERVER)
        return _server_semaphores[sse_url]


class MCPConnectionPool:
    """Connection pool for MCP SSE sessions.

    Maintains a pool of ready-to-use SSE connections per server URL,
    avoiding the overhead of creating new connections for each tool call.
    """

    def __init__(self, pool_size: int = 10, max_idle_time: float = 300.0):
        self._pools: Dict[str, queue.Queue] = {}
        self._pool_size = pool_size
        self._max_idle_time = max_idle_time
        self._lock = threading.Lock()
        self._active_connections: Dict[str, int] = {}

    def _get_pool(self, sse_url: str) -> queue.Queue:
        """Get or create a connection pool for a specific URL."""
        with self._lock:
            if sse_url not in self._pools:
                self._pools[sse_url] = queue.Queue(maxsize=self._pool_size)
                self._active_connections[sse_url] = 0
            return self._pools[sse_url]

    async def acquire(self, sse_url: str) -> tuple:
        """Acquire a connection from the pool or create a new one."""
        pool = self._get_pool(sse_url)

        # Try to get an existing connection
        try:
            conn_data = pool.get_nowait()
            # Check if connection is still valid (not too old)
            if time.time() - conn_data['created_at'] < self._max_idle_time:
                return conn_data['read'], conn_data['write'], conn_data['session'], True
            # Connection is stale, close it
            try:
                await conn_data['session'].__aexit__(None, None, None)
            except:
                pass
        except queue.Empty:
            pass

        # Create new connection
        return None, None, None, False

    def release(self, sse_url: str, read, write, session):
        """Release a connection back to the pool."""
        pool = self._get_pool(sse_url)
        try:
            pool.put_nowait({
                'read': read,
                'write': write,
                'session': session,
                'created_at': time.time()
            })
        except queue.Full:
            # Pool is full, connection will be garbage collected
            pass


# Global connection pool
_connection_pool = MCPConnectionPool(pool_size=20)


@dataclass
class MCPToolResult:
    success: bool
    content: str
    error: Optional[str] = None


class GenericMCPClient:
    def __init__(self, sse_url: str):
        self.sse_url = sse_url

    async def list_tools(self, retries=2) -> List[Any]:
        for attempt in range(retries):
            print(f"[TRACE] list_tools for {self.sse_url} (Attempt {attempt+1})")
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
            except Exception as e:
                err_type = type(e).__name__
                if err_type == "ExceptionGroup":
                    sub_errors = []
                    if hasattr(e, 'exceptions'):
                        for sub_e in e.exceptions:
                            sub_errors.append(f"{type(sub_e).__name__}: {sub_e}")
                    print(f"[TRACE] Error listing tools from {self.sse_url}: ExceptionGroup [{', '.join(sub_errors)}]")
                else:
                    print(f"[TRACE] Error listing tools from {self.sse_url}: {err_type}: {e}")

            if attempt < retries - 1:
                await asyncio.sleep(2)

        return []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> MCPToolResult:
        """Execute a tool call with connection reuse."""
        start_time = time.time()
        retries = 2

        for attempt in range(retries + 1):
            try:
                print(f"[TRACE] Connecting to {self.sse_url} for tool {tool_name} (Attempt {attempt+1})")

                # Use connection pool approach with fresh connections
                # SSE connections are stateful, so we create per-call but with optimized settings
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
                print(f"[TRACE] Timeout calling {tool_name} on {self.sse_url}")
                if attempt == retries:
                    return MCPToolResult(success=False, content="", error="MCP call timed out")
            except Exception as e:
                print(f"[TRACE] Error calling {tool_name} on {self.sse_url}: {e}")
                if attempt == retries:
                    return MCPToolResult(success=False, content="", error=str(e))

            await asyncio.sleep(0.5)

        return MCPToolResult(success=False, content="", error="Unknown error")


# Shared event loop for MCP calls - avoids creating new loops per call
_shared_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()
_loop_thread: Optional[threading.Thread] = None


def _get_shared_loop() -> asyncio.AbstractEventLoop:
    """Get or create a shared event loop running in a dedicated thread."""
    global _shared_loop, _loop_thread

    with _loop_lock:
        if _shared_loop is None or not _shared_loop.is_running():
            _shared_loop = asyncio.new_event_loop()

            def run_loop():
                asyncio.set_event_loop(_shared_loop)
                _shared_loop.run_forever()

            _loop_thread = threading.Thread(target=run_loop, daemon=True, name="mcp-event-loop")
            _loop_thread.start()
            # Give the loop a moment to start
            time.sleep(0.1)

        return _shared_loop


class DynamicMCPManager:
    def __init__(self, registry_url: str = None):
        import os
        self.registry_url = registry_url or os.getenv("MCP_REGISTRY_URL", "http://mcp-registry:8010")
        self.clients: Dict[str, GenericMCPClient] = {}
        self.tools_map: Dict[str, tuple[GenericMCPClient, Any]] = {}

    async def refresh_tools(self, retries=3, delay=2, force=False):
        """Fetch all servers from registry and their tools with retries"""
        # Simple debounce
        if not force and self.tools_map and (time.time() - getattr(self, 'last_refresh_time', 0) < 60):
            return

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
                        raise Exception(f"Registry returned status {response.status_code}")

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

                    if new_tools_map or not servers:
                        self.clients = new_clients
                        self.tools_map = new_tools_map
                        self.last_refresh_time = time.time()
                        print(f"MCP Refresh complete. Total tools: {len(self.tools_map)}")
                        return
                    else:
                        print("Warning: aggregated 0 tools, but servers were found. Keeping old cache.")
                        return

            except Exception as e:
                print(f"Error refreshing MCP tools: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)

        print("Max retries reached for MCP refresh. Using cached tools if available.")
        if not self.tools_map:
             print("CRITICAL: No tools available in cache.")

    def refresh_tools_sync(self, force=False):
        """Sync wrapper for refresh_tools to allow usage in synchronous contexts"""
        try:
             loop = _get_shared_loop()
             future = asyncio.run_coroutine_threadsafe(
                 self.refresh_tools(force=force),
                 loop
             )
             # Wait for result with timeout
             return future.result(timeout=20.0)
        except Exception as e:
            print(f"Error in refresh_tools_sync: {e}")

    def get_gemini_tools(self, message: Any = None, context: Dict[str, Any] = None) -> List[Callable]:
        """Convert all discovered tools into Gemini-compatible functions"""
        gemini_tools = []

        for tool_name, (mcp_client, tool_def) in self.tools_map.items():
            def create_tool(name=tool_name, client=mcp_client, definition=tool_def):
                def tool_wrapper(**kwargs):
                    # Robust type casting based on annotations
                    if hasattr(tool_wrapper, "__annotations__"):
                        for k, v in kwargs.items():
                            expected_type = tool_wrapper.__annotations__.get(k)
                            if expected_type and v is not None:
                                if expected_type is int and isinstance(v, str):
                                    try: kwargs[k] = int(v)
                                    except: pass
                                elif expected_type is float and isinstance(v, (str, int)):
                                    try: kwargs[k] = float(v)
                                    except: pass
                                elif expected_type is bool and isinstance(v, str):
                                    kwargs[k] = v.lower() in ("true", "1", "yes")

                    # Inject context if provided
                    if context:
                        for k, v in context.items():
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

                try:
                    params = []
                    properties = definition.inputSchema.get("properties", {})
                    required = definition.inputSchema.get("required", [])

                    tool_annotations = {}
                    for p_name, p_info in properties.items():
                        if context and p_name in context:
                            continue

                        json_type = p_info.get("type", "string")
                        py_type = str
                        if json_type == "integer": py_type = int
                        elif json_type == "number": py_type = float
                        elif json_type == "boolean": py_type = bool
                        elif json_type == "array": py_type = list
                        elif json_type == "object": py_type = dict

                        params.append(inspect.Parameter(
                            p_name,
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            annotation=py_type
                        ))
                        tool_annotations[p_name] = py_type

                    if params:
                        tool_wrapper.__signature__ = inspect.Signature(params)
                        tool_wrapper.__annotations__ = tool_annotations
                except Exception as e:
                    print(f"Failed to set signature for tool {name}: {e}")

                return tool_wrapper

            gemini_tools.append(create_tool())

        return gemini_tools

    def _run_tool_sync(self, client: GenericMCPClient, tool_name: str, kwargs: Dict[str, Any]) -> str:
        """Execute MCP tool call using a shared event loop for better performance.

        Uses a shared event loop running in a dedicated thread, avoiding the overhead
        of creating new event loops for each call (asyncio.run() overhead).
        """
        semaphore = _get_server_semaphore(client.sse_url)

        def _execute_with_shared_loop():
            with semaphore:
                try:
                    loop = _get_shared_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        client.call_tool(tool_name, kwargs),
                        loop
                    )
                    # Wait for result with timeout
                    result = future.result(timeout=45.0)
                    if isinstance(result, MCPToolResult):
                        return result.content if result.success else f"Error: {result.error}"
                    return str(result)
                except Exception as e:
                    return f"Error: {e}"

        try:
            future = _mcp_executor.submit(_execute_with_shared_loop)
            return future.result(timeout=50.0)
        except Exception as e:
            return f"Error: {e}"


# Global manager instance
mcp_manager = DynamicMCPManager()

async def initialize_mcp():
    await mcp_manager.refresh_tools()

def get_discovered_tools(message: Any = None, context: Dict[str, Any] = None) -> List[Callable]:
    """Helper to get tools from the global manager - uses cached tools."""
    if not mcp_manager.tools_map:
        print("[DEBUG] No cached tools available - attempting sync refresh...")
        mcp_manager.refresh_tools_sync(force=True)
        if not mcp_manager.tools_map:
            print("[DEBUG] Still no tools after refresh.")

    return mcp_manager.get_gemini_tools(message, context)
