import os
from google import genai
from google.genai import types
from typing import Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

class GeminiClient:
    def __init__(self, model_name="gemini-2.0-flash", embedding_model="text-embedding-004", tools=None):
        if not API_KEY:
            print("Warning: GEMINI_API_KEY not found in environment variables.")
            self.client = None
        else:
            self.client = genai.Client(api_key=API_KEY)
        
        self.model_name = model_name.replace("models/", "")
        self.embedding_model = embedding_model.replace("models/", "")
        self.tools = tools

    def generate_content(self, prompt: str, chat_history=None) -> Any:
        if not self.client:
            return None
        try:
            config = types.GenerateContentConfig(tools=self.tools)
            if chat_history is not None:
                chat = self.client.chats.create(model=self.model_name, history=chat_history, config=config)
                response = chat.send_message(prompt)
            else:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config
                )
            return response
        except Exception as e:
            print(f"Error generating content: {e}")
            return None

    def start_chat(self, history=None, enable_automatic_function_calling=True):
        if not self.client:
            return None
            
        config = types.GenerateContentConfig(
            tools=self.tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=not enable_automatic_function_calling
            )
        )
        return self.client.chats.create(model=self.model_name, history=history, config=config)

    def get_embedding(self, text: str, task_type="RETRIEVAL_QUERY") -> list:
        if not self.client:
            return []
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
            print(f"Error generating embedding: {e}")
            return []
