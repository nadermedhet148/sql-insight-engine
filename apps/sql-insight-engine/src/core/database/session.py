from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:password@metadata_store:5432/insight_engine")

# Log masked URL for debugging
masked_url = DATABASE_URL
if "@" in DATABASE_URL:
    prefix, _, suffix = DATABASE_URL.partition("@")
    if ":" in prefix:
        main_prefix, _, _ = prefix.rpartition(":")
        masked_url = f"{main_prefix}:****@{suffix}"

print(f"DATABASE_URL being used: {masked_url}")

engine = create_engine(
    DATABASE_URL,
    pool_size=50,           # Increased from default 5
    max_overflow=50,        # Allow 50 additional connections beyond pool_size
    pool_pre_ping=True,     # Verify connections before use
    pool_recycle=3600,      # Recycle connections after 1 hour
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
