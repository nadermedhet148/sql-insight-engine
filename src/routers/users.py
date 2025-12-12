from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Any
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import User, UserDBConfig

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={404: {"description": "Not found"}},
)

class UserCreate(BaseModel):
    account_id: str
    quota: int = 100

class UserDBConfigCreate(BaseModel):
    host: str
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
        return db_user
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{user_id}/config", response_model=Any)
def add_db_config(user_id: int, config: UserDBConfigCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if config exists
    if user.db_config:
         raise HTTPException(status_code=400, detail="Configuration already exists for this user")

    new_config = UserDBConfig(
        user_id=user_id,
        host=config.host,
        db_name=config.db_name,
        username=config.username,
        password=config.password
    )
    try:
        db.add(new_config)
        db.commit()
        db.refresh(new_config)
        return new_config
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
