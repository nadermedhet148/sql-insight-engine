import sys
from retrieval import KnowledgeBase
from generation import SQLGenerator
from execution import QueryExecutor

def main():
    if len(sys.argv) < 2:
        print("Usage: python src/main.py 'Your query here'")
        sys.exit(1)

    user_query = sys.argv[1]
    
    # 1. Retrieval
    kb = KnowledgeBase()
    context = kb.search(user_query)
    
    # 2. Generation
    generator = SQLGenerator()
    sql = generator.generate_sql(user_query, context)
    
    # 3. Execution
    executor = QueryExecutor()
    results = executor.execute(sql)
    
    # 4. Report
    print(f"\nResults: {results}")

if __name__ == "__main__":
    main()
