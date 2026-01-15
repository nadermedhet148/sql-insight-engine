import sys
import os
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, Float
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.sql import func

# Ensure src is in python path
src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.append(src_path)

from core.database.session import SessionLocal as MetadataSessionLocal, engine as MetadataEngine, Base as MetadataBase
from account.models import User as MetadataUser, UserDBConfig

# --- Configuration for External Test DB ---
# Use localhost:5433 when running from host machine (5433 is mapped in docker-compose)
# Use external_test_db:5432 when running inside Docker
TEST_DB_URL = os.getenv("EXTERNAL_TEST_DB_URL", "postgresql://test_user:test_password@localhost:5433/external_test_db")
TestBase = declarative_base()

# --- Models for External Test DB ---
class TestUser(TestBase):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    orders = relationship("TestOrder", back_populates="user")

class TestProduct(TestBase):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    description = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    orders = relationship("TestOrder", back_populates="product")

class TestOrder(TestBase):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer, default=1)
    status = Column(String, default="pending")
    order_date = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("TestUser", back_populates="orders")
    product = relationship("TestProduct", back_populates="orders")

def setup_test_database():
    print(f"Connecting to Test Database at {TEST_DB_URL}...")
    engine = create_engine(TEST_DB_URL)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()

    try:
        # Create Tables
        print("Creating tables in Test Database...")
        TestBase.metadata.drop_all(engine) # Clean slate
        TestBase.metadata.create_all(engine)

        # Add Seed Data
        print("Seeding Test Database...")
        
        # Add Seed Data
        print("Seeding Test Database...")
        
        import random
        from datetime import datetime, timedelta

        # 1. Bulk Users (100)
        print("Generating 100 Users...")
        users_data = []
        for i in range(1, 101):
            users_data.append({
                "username": f"user_{i}",
                "email": f"user_{i}@example.com"
            })
        session.bulk_insert_mappings(TestUser, users_data)
        session.commit()

        # 2. Bulk Products (1000)
        print("Generating 1000 Products...")
        products_data = []
        for i in range(1, 1001):
            products_data.append({
                "name": f"Product {i}",
                "price": round(random.uniform(10.0, 1000.0), 2),
                "description": f"Description for product {i}"
            })
        session.bulk_insert_mappings(TestProduct, products_data)
        session.commit()

        # 3. Bulk Orders (1,000,000)
        print("Generating 1,000,000 Orders (this may take a while)...")
        
        BATCH_SIZE = 10000
        TOTAL_ORDERS = 10000
        statuses = ["pending", "completed", "cancelled", "shipped"]
        
        # Get user and product ID ranges using what we just inserted
        # (Assuming sequential IDs starting at 1 because we just dropped tables)
        user_ids = list(range(1, 101))
        product_ids = list(range(1, 1001))

        created_count = 0
        while created_count < TOTAL_ORDERS:
            orders_batch = []
            
            # Determine size of this batch (handle the last chunk)
            current_batch_size = min(BATCH_SIZE, TOTAL_ORDERS - created_count)
            
            for _ in range(current_batch_size):
                orders_batch.append({
                    "user_id": random.choice(user_ids),
                    "product_id": random.choice(product_ids),
                    "quantity": random.randint(1, 5),
                    "status": random.choice(statuses),
                    "order_date": datetime.now() - timedelta(days=random.randint(0, 365))
                })
            
            session.bulk_insert_mappings(TestOrder, orders_batch)
            session.commit()
            
            created_count += len(orders_batch)
            print(f"Inserted {created_count} orders...")

        print("Test Database seeded successfully.")
    
    finally:
        session.close()

def setup_metadata_user():
    print("Setting up Metadata User...")
    session = MetadataSessionLocal()
    try:
        # Create a test user if not exists
        user = session.query(MetadataUser).filter(MetadataUser.id == 1).first()
        if not user:
            user = MetadataUser(id=1, username="testuser", email="test@example.com", account_id="ACC123", quota=100)
            session.add(user)
            session.commit()
            print("Created Metadata User 1")
        
        # Add DB Config
        db_config = session.query(UserDBConfig).filter(UserDBConfig.user_id == 1).first()
        if not db_config:
            db_config = UserDBConfig(
                user_id=1,
                host="external_test_db",
                port=5432,
                db_name="external_test_db",
                username="test_user",
                password="test_password",
                db_type="postgresql"
            )
            session.add(db_config)
            session.commit()
            print("Added DB Config for User 1")
        else:
            print("DB Config already exists for User 1")
            
    except Exception as e:
        print(f"Error setting up Metadata User: {e}")
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    setup_metadata_user()
    setup_test_database()
