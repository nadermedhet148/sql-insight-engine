from sqlalchemy import create_engine, inspect

# Use localhost:5433 which I forwarded to the external-test-db pod
DB_URL = "postgresql://test_user:test_password@localhost:5433/external_test_db"

def check_tables():
    print(f"Connecting to {DB_URL}...")
    engine = create_engine(DB_URL)
    inspector = inspect(engine)
    
    print("Checking 'public' schema...")
    tables = inspector.get_table_names(schema="public")
    print(f"Tables in public: {tables}")
    
    # Try without schema
    print("Checking default schema...")
    tables_default = inspector.get_table_names()
    print(f"Tables in default: {tables_default}")

if __name__ == "__main__":
    check_tables()
