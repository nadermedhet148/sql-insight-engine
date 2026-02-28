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

from core.services.schema_graph_indexer import index_schema_to_graph

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

        # Trigger Graph-RAG schema indexing (ChromaDB + Neo4j)
        try:
            index_schema_to_graph(account_id=user.account_id, db_config=new_config)
        except Exception as e:
            print(f"Warning: Could not auto-index schema graph: {e}")

        return {"id": new_config.id, "user_id": new_config.user_id, "host": new_config.host, "db_name": new_config.db_name, "username": new_config.username}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))



# Note: Synchronous query endpoint has been removed in favor of async Saga pattern.
# Use POST /users/{user_id}/query/async for processing queries.

