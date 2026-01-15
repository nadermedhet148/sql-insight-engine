import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from core.database.session import get_db
from account.models import User, UsageLog
from agentic_sql.saga.messages import QueryInitiatedMessage
from agentic_sql.saga.publisher import get_saga_publisher
from agentic_sql.saga.state_store import get_saga_state_store


class NaturalLanguageQueryRequest(BaseModel):
    question: str


class QueryAsyncResponse(BaseModel):
    saga_id: str
    status: str
    message: str
    status_endpoint: str


class QueryStatusResponse(BaseModel):
    saga_id: str
    status: str  # pending, completed, error
    result: dict | None = None
    message: str | None = None


router = APIRouter()


@router.post("/{user_id}/query/async", response_model=QueryAsyncResponse)
def query_user_database_async(
    user_id: int,
    request: NaturalLanguageQueryRequest,
    db: Session = Depends(get_db)
):
    # Get user
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check DB config
    if not user.db_config:
        raise HTTPException(
            status_code=400,
            detail="Database not configured for this user"
        )
    
    # Check quota
    if user.quota <= 0:
        raise HTTPException(
            status_code=403,
            detail="Query quota exceeded"
        )
    
    # Generate unique saga ID
    saga_id = str(uuid.uuid4())
    
    print(f"\n[API] New async query request")
    print(f"[API] Saga ID: {saga_id}")
    print(f"[API] User: {user.id} ({user.account_id})")
    print(f"[API] Question: '{request.question}'")
    
    # Create initial saga message
    message = QueryInitiatedMessage(
        saga_id=saga_id,
        user_id=user.id,
        account_id=user.account_id,
        question=request.question,
        db_config={
            "host": user.db_config.host,
            "port": user.db_config.port,
            "db_name": user.db_config.db_name,
            "username": user.db_config.username,
            "password": user.db_config.password,
            "db_type": user.db_config.db_type
        }
    )
    
    # Add initial call stack entry
    message.add_to_call_stack(
        step_name="api_request_received",
        status="success",
        user_id=user.id,
        account_id=user.account_id,
        question=request.question
    )
    
    # Mark as pending in state store
    saga_store = get_saga_state_store()
    saga_store.mark_pending(saga_id, {
        "question": request.question,
        "user_id": user.id,
        "account_id": user.account_id
    })
    
    # Publish to first step (tables check)
    try:
        publisher = get_saga_publisher()
        publisher.publish_query_generation(message)
        
        print(f"[API] ✓ Published to saga queue")
        print(f"[API] Saga started successfully")
        
    except Exception as e:
        print(f"[API] ✗ Failed to publish to queue: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initiate query processing: {str(e)}"
        )
    
    # Decrement quota
    user.quota -= 1
    
    # Log usage
    usage_log = UsageLog(
        user_id=user_id,
        query_text=request.question
    )
    db.add(usage_log)
    db.commit()
    
    # Return saga ID for tracking
    return QueryAsyncResponse(
        saga_id=saga_id,
        status="processing",
        message="Query is being processed asynchronously",
        status_endpoint=f"/users/{user_id}/query/status/{saga_id}"
    )


@router.get("/{user_id}/query/status/{saga_id}", response_model=QueryStatusResponse)
def get_query_status(user_id: int, saga_id: str, db: Session = Depends(get_db)):
    # Verify user exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get saga result
    saga_store = get_saga_state_store()
    status = saga_store.get_status(saga_id)
    result = saga_store.get_result(saga_id)
    
    if status == "completed" and result:
        return QueryStatusResponse(
            saga_id=saga_id,
            status="completed",
            result=result,
            message="Query completed successfully"
        )
    elif status == "error" and result:
        return QueryStatusResponse(
            saga_id=saga_id,
            status="error",
            result=result,
            message=result.get("error_message", "Query processing failed")
        )
    else:
        return QueryStatusResponse(
            saga_id=saga_id,
            status="pending",
            result=result,
            message="Query is still being processed"
        )


