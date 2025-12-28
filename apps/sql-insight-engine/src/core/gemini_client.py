import os
import json
from typing import Any, List, Optional
from google import genai
from google.genai import types

class GeminiClient:
    def __init__(self, model_name="gemini-2.0-flash", embedding_model="text-embedding-004", tools=None):
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.embedding_model = embedding_model
        # Optional tool definitions for agentic behavior
        self.tools = tools

    def generate_content(self, prompt: str, chat_history=None) -> Any:
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
        try:
            result = self.client.models.embed_content(
                model=self.embedding_model,
                contents=text,
                config=types.EmbedContentConfig(task_type=task_type.upper())
            )
            if result.embeddings:
                return result.embeddings[0].values
            return []
        except Exception as e:
            print(f"Error in GeminiClient.get_embedding (SDK): {e}")
            return []

    def start_chat(self, history=None, enable_automatic_function_calling=True):
        config = types.GenerateContentConfig(
            tools=self.tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=not enable_automatic_function_calling
            )
        )
        return self.client.chats.create(model=self.model_name, history=history, config=config)
function_calling_config = types.AutomaticFunctionCallingConfig(disable=False)
