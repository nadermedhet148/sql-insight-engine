import os
import json
import time
from typing import Any, List, Optional
from google import genai
from google.genai import types

class MockResponse:
    def __init__(self, text):
        self.text = text

class MockChat:
    def __init__(self, tools=None):
        self.tools = tools
        self.history = []

    def send_message(self, prompt: str) -> MockResponse:
        print("[MockGemini] Mocking send_message request...")
        import random
        import time
        
        
        # 2. Simulate tool execution
        if self.tools:
            tool_names = [t.__name__ for t in self.tools]
            print(f"[MockGemini] Found {len(self.tools)} tools: {tool_names}. Executing relevant ones...")
            
            # Map tools by name for easier access
            tool_map = {t.__name__: t for t in self.tools}
            
            # Helper to run tool safely
            def run_tool(name, args):
                if name in tool_map:
                    print(f"[MockGemini] Calling tool '{name}' with args: {args}")
                    try:
                        res = tool_map[name](**args)
                        print(f"[MockGemini] Tool '{name}' result: {str(res)[:100]}...")
                    except Exception as e:
                        print(f"[MockGemini] Tool '{name}' failed: {e}")
                else:
                    print(f"[MockGemini] Tool '{name}' not found - skipping. Available: {tool_names}")

            # Always try to list tables if available
            run_tool("list_tables", {})
            
            # CHROMA CALL: Explicitly try to search schema
            # We use a broad try to ensure we hit it if it exists
            # Added account_id="1" to satisfy tool requirements
            run_tool("search_relevant_schema", {"query": "customer orders", "n_results": 2, "account_id": "1"})

            # CHROMA CALL: Also search knowledgebase as requested
            run_tool("search_relevant_knowledgebase", {"query": "business policies", "n_results": 2, "account_id": "1"})

            # Describe a table if we found one (simulated)
            run_tool("describe_table", {"table_name": "users"})

        # Prepare response based on prompt context
        if "EXECUTIVE SUMMARY" in prompt or "Business Intelligence" in prompt:
             return MockResponse("""
EXECUTIVE SUMMARY: This is a mocked executive summary. The system is operating in MOCK_GEMINI mode.
""")
        else:
             return MockResponse("""
DECISION: RELEVANT
REASONING: This is a mocked response for load testing. The system is operating in MOCK_GEMINI mode.
SQL: SELECT 1
""")

class GeminiClient:
    def __init__(self, model_name="gemini-2.0-flash", embedding_model="gemini-embedding-001", tools=None):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.embedding_model = embedding_model
        self.tools = tools
        self.client = None
        self.is_mock = os.getenv("MOCK_GEMINI", "false").lower() == "true"
        
        if self.is_mock:
            print("[GeminiClient] ℹ Running in MOCK mode. No actual API calls will be made.")
            return

        if not self.api_key:
            print("[GeminiClient] ⚠ Warning: GEMINI_API_KEY not found in environment.")
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
        except Exception as e:
            print(f"[GeminiClient] ✗ Failed to initialize Gemini SDK: {e}")

    def generate_content(self, prompt: str, chat_history=None) -> Any:
        if self.is_mock:
            print("[GeminiClient] returning mock content")
            return MockResponse("Mocked content response")

        if not self.client:
            print("[GeminiClient] ✗ Cannot generate content: Client not initialized (check API key)")
            return None
        try:
            config = None
            if self.tools:
                config = types.GenerateContentConfig(tools=self.tools)
            
            if chat_history:
                chat = self.client.chats.create(model=self.model_name, history=chat_history, config=config)
                return chat.send_message(prompt)
            else:
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config
                )
        except Exception as e:
            print(f"Error in GeminiClient.generate_content (SDK): {e}")
            return None

    def get_embedding(self, text: str, task_type="RETRIEVAL_QUERY") -> list:
        if self.is_mock:
            # Return a dummy embedding vector of appropriate size (e.g., 768)
            return [0.1] * 768

        if not self.client:
            print("[GeminiClient] ✗ Cannot get embedding: Client not initialized (check API key)")
            return []
        try:
            result = self.client.models.embed_content(
                model=self.embedding_model,
                contents=text,
                config=types.EmbedContentConfig(task_type=task_type.upper())
            )
            # Handle single result
            if result.embeddings:
                return result.embeddings[0].values
            return []
        except Exception as e:
            print(f"Error in GeminiClient.get_embedding (SDK): {e}")
            return []

    def get_batch_embeddings(self, texts: List[str], task_type="RETRIEVAL_DOCUMENT") -> List[List[float]]:
        """
        Get embeddings for a list of texts in a single batch request.
        """
        if not texts:
            return []

        if self.is_mock:
            return [[0.1] * 768 for _ in texts]

        if not self.client:
            print("[GeminiClient] ✗ Cannot get batch embeddings: Client not initialized")
            return []

        try:
            # The SDK typically supports list of contents for batch embedding
            # Note: Depending on SDK version, we might need to iterate or it handles it.
            # Google GenAI SDK `models.embed_content` `contents` can be a list of strings.
            # But the return type implies multiple embeddings.
            
            # For robustness with different SDK versions/limitations, checking if we can pass list.
            # If not supported directly, we loop here (client side batching), 
            # but ideally the API supports it.
            # Based on docs, `contents` can be a list of strings.
            
            result = self.client.models.embed_content(
                model=self.embedding_model,
                contents=texts,
                config=types.EmbedContentConfig(task_type=task_type.upper())
            )
            
            if result.embeddings:
                return [e.values for e in result.embeddings]
            return []
            
        except Exception as e:
            print(f"Error in GeminiClient.get_batch_embeddings (SDK): {e}")
            # Fallback to sequential if batch fails? Or just return empty.
            return []

    def start_chat(self, history=None, enable_automatic_function_calling=True):
        if self.is_mock:
            return MockChat(tools=self.tools)

        if not self.client:
            print("[GeminiClient] ✗ Cannot start chat: Client not initialized (check API key)")
            return None
        config = types.GenerateContentConfig(
            tools=self.tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=not enable_automatic_function_calling
            )
        )
        return self.client.chats.create(model=self.model_name, history=history, config=config)

function_calling_config = types.AutomaticFunctionCallingConfig(disable=False)
