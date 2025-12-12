from gemini_client import GeminiClient

class SQLGenerator:
    def __init__(self):
        print("Initializing SQL Generator with Gemini")
        self.client = GeminiClient()

    def generate_sql(self, query: str, context: list) -> str:
        print(f"Generating SQL for '{query}' with context: {context}")
        
        # Construct a prompt for SQL generation
        context_str = "\n".join(context)
        prompt = f"""
        You are an expert SQL assistant.
        Given the following context about the database schema and definitions:
        {context_str}

        Generate a valid SQL query for the following natural language request:
        "{query}"

        Return ONLY the SQL query, no markdown formatting or explanations.
        """
        
        sql_query = self.client.generate_content(prompt)
        # Basic cleanup to remove backticks if the model adds them
        clean_query = sql_query.replace("```sql", "").replace("```", "").strip()
        
        return clean_query
