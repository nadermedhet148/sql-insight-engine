from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Any, Optional
from sqlalchemy.orm import Session
from core.database.session import get_db
from account.models import User, UserDBConfig, UsageLog

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={404: {"description": "Not found"}},
)

class UserCreate(BaseModel):
    account_id: str
    quota: int = 100  # Default quota, not required from frontend

class UserDBConfigCreate(BaseModel):
    db_type: str = "postgresql"
    host: str
    port: Optional[int] = None
    db_name: str
    username: str
    password: str

@router.post("/", response_model=Any)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = User(account_id=user.account_id, quota=user.quota)
    try:
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return {"id": db_user.id, "account_id": db_user.account_id, "quota": db_user.quota}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

from core.services.database_service import database_service
from core.services.knowledge_service import index_text_content

@router.post("/{user_id}/config", response_model=Any)
def add_db_config(user_id: int, config: UserDBConfigCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.db_config:
         raise HTTPException(status_code=400, detail="Configuration already exists for this user")

    new_config = UserDBConfig(
        user_id=user_id,
        db_type=config.db_type,
        host=config.host,
        port=config.port,
        db_name=config.db_name,
        username=config.username,
        password=config.password
    )
    try:
        db.add(new_config)
        db.commit()
        db.refresh(new_config)
        
        
        # Trigger schema indexing - one document per table
        try:
            # Get list of all tables
            table_names = database_service.get_table_names(new_config)
            
            if table_names:
                indexed_count = 0
                failed_count = 0
                
                for table_name in table_names:
                    # Get detailed schema for this table
                    result = database_service.describe_table(new_config, table_name)
                    
                    if result.success:
                        # Create a separate document for each table
                        table_filename = f"table_{new_config.db_name}_{table_name}.md"
                        index_text_content(
                            account_id=user.account_id,
                            filename=table_filename,
                            content=result.data,
                            collection_name="account_schema_info"
                        )
                        indexed_count += 1
                    else:
                        print(f"Warning: Failed to get schema for table {table_name}: {result.error}")
                        failed_count += 1
                
                print(f"Post-config: Indexed {indexed_count} tables from {new_config.db_name} to knowledge base.")
                if failed_count > 0:
                    print(f"Warning: Failed to index {failed_count} tables.")
            else:
                print(f"Warning: No tables found in database {new_config.db_name}")
        except Exception as e:
            print(f"Warning: Could not auto-index schema: {e}")

        return {"id": new_config.id, "user_id": new_config.user_id, "host": new_config.host, "db_name": new_config.db_name, "username": new_config.username}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


class NaturalLanguageQueryRequest(BaseModel):
    question: str

class QueryResponse(BaseModel):
    success: bool
    generated_sql: Optional[str] = None
    raw_results: Optional[str] = None
    formatted_response: Optional[str] = None
    reasoning: Optional[str] = None
    error: Optional[str] = None

from core.services.query_service import query_service

@router.post("/{user_id}/query", response_model=QueryResponse)
def query_user_database(user_id: int, request: NaturalLanguageQueryRequest, db: Session = Depends(get_db)):
    """
    Process a natural language question about the user's data.
    
    Workflow:
    1. Retrieve schema context from knowledge base
    2. Generate SQL query using LLM
    3. Execute query on user's database
    4. Format results using LLM
    """
    # Get user and verify existence
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if user has database configuration
    if not user.db_config:
        raise HTTPException(status_code=400, detail="User has no database configured")
    
    # Check quota (optional - track usage)
    if user.quota <= 0:
        raise HTTPException(status_code=429, detail="Query quota exceeded")
    
    try:
        # Process the natural language query
        result = query_service.process_nl_query(
            account_id=user.account_id,
            db_config=user.db_config,
            question=request.question
        )
        
        # Log usage
        usage_log = UsageLog(
            user_id=user_id,
            query_text=request.question
        )
        db.add(usage_log)
        
        # Decrement quota
        user.quota -= 1
        db.commit()
        
        return QueryResponse(
            success=result.success,
            generated_sql=result.generated_sql,
            raw_results=result.raw_results,
            formatted_response=result.formatted_response,
            reasoning=result.reasoning,
            error=result.error
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Query processing failed: {str(e)}")

