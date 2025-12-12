class SQLGenerator:
    def __init__(self):
        print("Initializing SQL Generator")

    def generate_sql(self, query: str, context: list) -> str:
        # Construct prompt with context
        print(f"Generating SQL for '{query}' with context: {context}")
        # Call LLM ...
        return "SELECT * FROM users WHERE last_login < NOW() - INTERVAL '30 days';"
