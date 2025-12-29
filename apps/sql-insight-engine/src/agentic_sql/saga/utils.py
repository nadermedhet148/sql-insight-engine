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

def get_interaction_history(chat) -> List[Dict[str, Any]]:
    """
    Safely extract and sanitize interaction history from a chat object.
    Handles differences between SDK versions and internal types.
    """
    interaction_history = []
    try:
        # Chat object should have history property (from our wrapper or SDK)
        history = getattr(chat, "history", [])
        if not history and hasattr(chat, "_history"):
            history = chat._history
            
        for m in history:
            role = m.role
            parts = []
            for part in m.parts:
                if hasattr(part, "text") and part.text:
                    parts.append({"text": part.text})
                elif hasattr(part, "function_call") and part.function_call:
                    parts.append({
                        "function_call": {
                            "name": part.function_call.name,
                            "args": dict(part.function_call.args)
                        }
                    })
                elif hasattr(part, "function_response") and part.function_response:
                    resp = getattr(part.function_response, "response", None)
                    if resp is None and hasattr(part.function_response, "fields"):
                         # Handle cases where response might be in fields
                         resp = part.function_response.fields
                         
                    if not isinstance(resp, (str, int, float, bool, list, dict, type(None))):
                        resp = str(resp)
                    
                    parts.append({
                        "function_response": {
                            "name": part.function_response.name,
                            "response": resp
                        }
                    })
            interaction_history.append({"role": role, "parts": parts})
        return sanitize_for_json(interaction_history)
    except Exception as e:
        print(f"[SAGA UTIL] Warning: Failed to extract interaction history: {e}")
        return []

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
    # Explicitly include any tool calls from the current message if not in extra_metadata
    if hasattr(message, "_current_tool_calls") and message._current_tool_calls and "tools_used" not in extra_metadata:
        extra_metadata["tools_used"] = message._current_tool_calls.copy()
        message._current_tool_calls = []

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
        "all_tool_calls": message.all_tool_calls,
        "status": "error",
        "user_id": message.user_id,
        "account_id": message.account_id
    }
    
    sanitized_error = sanitize_for_json(error_dict)
    saga_store.store_result(message.saga_id, sanitized_error, status="error")
    
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

def parse_llm_response(response_text: str, tags: List[str] = None) -> Dict[str, Any]:
    """
    Parses an LLM response that might contain JSON or custom tags.
    """
    import re
    result = {}
    
    # Clean up Markdown
    clean_text = response_text.replace("```json", "").replace("```", "").strip()
    
    # 1. Try JSON parsing
    try:
        # Improved regex to find JSON object
        json_match = re.search(r'\{(?:[^{}]|\{[^{}]*\})*\}', clean_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            # Merge JSON data (handling both lowercase and uppercase keys for robustness)
            for k, v in data.items():
                result[k.upper()] = v
                result[k.lower()] = v
    except:
        pass
        
    # 2. Tag-based parsing (fallback or secondary)
    if tags:
        for tag in tags:
            tag_upper = tag.upper()
            search_tag = f"{tag_upper}:"
            if search_tag in clean_text:
                # Find start of this tag
                start_p = clean_text.find(search_tag) + len(search_tag)
                # Find end (next tag or end of string)
                end_p = len(clean_text)
                for other_tag in tags:
                    other_search = f"{other_tag.upper()}:"
                    other_p = clean_text.find(other_search, start_p)
                    if other_p != -1 and other_p < end_p:
                        end_p = other_p
                
                val = clean_text[start_p:end_p].strip()
                # Remove brackets [ ] if they wrap the value
                if val.startswith("[") and val.endswith("]"):
                    val = val[1:-1].strip()
                result[tag_upper] = val
                result[tag.lower()] = val

    # 3. Specific cleanups
    if "SQL" in result and isinstance(result["SQL"], str):
        result["SQL"] = result["SQL"].replace("```sql", "").replace("```", "").strip()
        if result["SQL"].endswith(";"): result["SQL"] = result["SQL"][:-1]
        
    return result

def extract_response_metadata(response) -> Dict[str, Any]:
    """Extracts usage metadata from Gemini response object"""
    usage = {}
    if hasattr(response, "usage_metadata"):
        usage = {
            "prompt_token_count": getattr(response.usage_metadata, "prompt_token_count", 0),
            "candidates_token_count": getattr(response.usage_metadata, "candidates_token_count", 0),
            "total_token_count": getattr(response.usage_metadata, "total_token_count", 0)
        }
    return usage
