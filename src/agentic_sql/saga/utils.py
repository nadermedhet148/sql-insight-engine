"""
Saga Utility Functions
"""

import json
from typing import Any, Dict, List
from agentic_sql.saga.messages import SagaBaseMessage, CallStackEntry

def sanitize_for_json(obj):
    """
    Recursively sanitize objects for JSON serialization.
    Specifically handles Gemini/VertexAI internal types that pika/json can't handle.
    """
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    elif hasattr(obj, "__dict__"):
        # Handle custom objects or types with __dict__
        return sanitize_for_json(obj.__dict__)
    elif str(type(obj)).find("MapComposite") != -1:
        # Specifically handle Gemini's MapComposite by converting it to a basic dict
        try:
            return {k: sanitize_for_json(v) for k, v in dict(obj).items()}
        except:
            return str(obj)
    elif not isinstance(obj, (str, int, float, bool, type(None))):
        return str(obj)
    return obj

def update_saga_state(saga_id: str, update_data: Dict[str, Any], status: str = None):
    """
    Utility to update the saga state store with sanitized data.
    """
    from agentic_sql.saga.state_store import get_saga_state_store
    saga_store = get_saga_state_store()
    
    sanitized_data = sanitize_for_json(update_data)
    
    if status:
        saga_store.update_result(saga_id, sanitized_data, status=status)
    else:
        saga_store.update_result(saga_id, sanitized_data)

def store_saga_error(message: SagaBaseMessage, error_step: str, error_msg: str, 
                     duration_ms: float, formatted_response: str = None, **extra_metadata):
    """
    Utility to handle saga error storage and call stack updates.
    """
    from agentic_sql.saga.state_store import get_saga_state_store
    from agentic_sql.saga.publisher import SagaPublisher
    from agentic_sql.saga.messages import SagaErrorMessage
    
    saga_store = get_saga_state_store()
    
    # 1. Update call stack
    message.add_to_call_stack(
        step_name=error_step,
        status="error",
        duration_ms=duration_ms,
        error=error_msg,
        **extra_metadata
    )
    
    # 2. Store in state store
    if not formatted_response:
        formatted_response = f"As your Senior Business Intelligence Consultant, I encountered an issue during {error_step}: {error_msg}"
        
    error_dict = {
        "success": False,
        "saga_id": message.saga_id,
        "error_step": error_step,
        "error_message": error_msg,
        "formatted_response": formatted_response,
        "call_stack": [entry.to_dict() for entry in message.call_stack],
        "status": "error",
        "user_id": message.user_id,
        "account_id": message.account_id
    }
    
    saga_store.store_result(message.saga_id, error_dict, status="error")
    
    # 3. Publish error event
    try:
        err_event = SagaErrorMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            error_step=error_step,
            error_message=error_msg,
            error_details={"duration_ms": duration_ms, **extra_metadata}
        )
        SagaPublisher().publish_error(err_event)
    except Exception as e:
        print(f"[SAGA UTIL] Failed to publish error: {e}")
