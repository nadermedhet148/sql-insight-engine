import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables.")
else:
    genai.configure(api_key=API_KEY)

class GeminiClient:
    def __init__(self, model_name="models/gemini-2.5-flash", embedding_model="models/text-embedding-004"):
        self.model = genai.GenerativeModel(model_name)
        self.embedding_model = embedding_model

    def generate_content(self, prompt: str) -> str:
        """
        Generates text content based on the provided prompt.
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error generating content: {e}")
            return ""

    def get_embedding(self, text: str, task_type="retrieval_query") -> list:
        """
        Generates an embedding for the provided text.
        """
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
