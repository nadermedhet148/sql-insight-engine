import os
import google.generativeai as genai
from typing import Any
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables.")
else:
    genai.configure(api_key=API_KEY)

class GeminiClient:
    def __init__(self, model_name="models/gemini-2.0-flash", embedding_model="models/text-embedding-004", tools=None):
        self.model = genai.GenerativeModel(model_name, tools=tools)
        self.embedding_model = embedding_model

    def generate_content(self, prompt: str, chat_history=None) -> Any:
        try:
            if chat_history is not None:
                chat = self.model.start_chat(history=chat_history)
                response = chat.send_message(prompt)
            else:
                response = self.model.generate_content(prompt)
            return response
        except Exception as e:
            print(f"Error generating content: {e}")
            return None

    def get_embedding(self, text: str, task_type="retrieval_query") -> list:
        try:
            result = genai.embed_content(
                model=self.embedding_model,
                content=text,
                task_type=task_type
            )
            return result['embedding']
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return []
