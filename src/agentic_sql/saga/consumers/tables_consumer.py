import asyncio
import pika
import json
import time
from typing import List, Any, Dict
from agentic_sql.saga.messages import (
    TablesCheckedMessage,
    SagaErrorMessage, message_from_dict, QueryInitiatedMessage
)
from agentic_sql.saga.publisher import SagaPublisher
from core.gemini_client import GeminiClient
from account.models import User
from core.database.session import get_db


def run_tables_check_agentic(message: QueryInitiatedMessage, db_config_dict: Dict[str, Any]) -> tuple[bool, str, List[str]]:
    from core.mcp.client import DatabaseMCPClient, ChromaMCPClient
    
    db_url = f"postgresql://{db_config_dict['username']}:{db_config_dict['password']}@{db_config_dict['host']}:{db_config_dict['port'] or 5432}/{db_config_dict['db_name']}"
    db_client = DatabaseMCPClient(db_url)
    chroma_client = ChromaMCPClient()
    
    tools = [
        db_client.get_gemini_tool("list_tables", message=message),
        chroma_client.get_gemini_tool("search_relevant_schema", message=message),
        chroma_client.get_gemini_tool("search_business_knowledge", message=message)
    ]
    agent = GeminiClient(tools=tools)
    
    prompt = f"""
    You are a Gatekeeper for a SQL Query Engine. Your job is to strictly decide if a user's question is relevant to the specific database schema and business context.
    
    USER QUESTION: "{message.question}"
    
    INSTRUCTIONS:
    1. First, use `list_tables` to see which tables exist in the database.
    2. If no tables exist, the answer is likely IRRELEVANT (unless it's a general database setup metadata question).
    3. Use `search_relevant_schema` and `search_business_knowledge` to understand the business context and how the tables relate to the question.
    4. Decide if the question is RELEVANT or IRRELEVANT. 
    5. A question is IRRELEVANT if it's unrelated to the data in the tables or the business scope.
    6. Return a list of ALL available table names you found.
    
    RESPONSE FORMAT (STRICT):
    DECISION: [RELEVANT/IRRELEVANT]
    REASON: [Professional explanation]
    ALL_TABLES: [Comma separated list of ALL table names found, or NONE]
    """
    
    try:
        chat = agent.model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(prompt)
        text = response.text
        
        is_relevant = "DECISION: RELEVANT" in text
        reason = ""
        if "REASON:" in text:
            # Extract reason between REASON: and ALL_TABLES:
            parts = text.split("REASON:")
            if len(parts) > 1:
                reason_part = parts[1].split("ALL_TABLES:")[0].strip()
                reason = reason_part
        
        available_tables = []
        if "ALL_TABLES:" in text:
            tables_str = text.split("ALL_TABLES:")[1].strip()
            if tables_str != "NONE" and tables_str:
                available_tables = [t.strip().lower() for t in tables_str.split(",")]
        
        return is_relevant, reason, available_tables
    except Exception as e:
        print(f"[SAGA STEP 1] Agentic check failed: {e}")
        return True, "Defaulted to relevant due to error", []

from core.infra.consumer import BaseConsumer

class TablesConsumer(BaseConsumer):
    def __init__(self, host: str = None):
        super().__init__(queue_name=SagaPublisher.QUEUE_CHECK_TABLES, host=host)

    def process_message(self, ch, method, properties, body):
        process_tables_check(ch, method, properties, body)

def process_tables_check(ch, method, properties, body):
    start_time = time.time()
    
    try:
        data = json.loads(body)
        message = message_from_dict(data, QueryInitiatedMessage)
        
        print(f"\n[SAGA STEP 1] Tables Check (Agentic) - Saga ID: {message.saga_id}")
        
        db = next(get_db())
        try:
            user = db.query(User).filter(User.id == message.user_id).first()
            if not user or not user.db_config:
                raise Exception("User or DB config not found")
            
            db_config_dict = {
                "host": user.db_config.host,
                "port": user.db_config.port,
                "db_name": user.db_config.db_name,
                "username": user.db_config.username,
                "password": user.db_config.password,
            }
            
            is_relevant, reason, available_tables = run_tables_check_agentic(message, db_config_dict)
            
            duration_ms = (time.time() - start_time) * 1000
            
            if not is_relevant:
                print(f"[SAGA STEP 2] 🛑 Question is IRRELEVANT: {reason}")
                
                message.add_to_call_stack(
                    step_name="check_tables_agentic",
                    status="failed",
                    duration_ms=duration_ms,
                    reason=reason
                )
                
                # Store final result as "Irrelevant" and stop
                from agentic_sql.saga.state_store import get_saga_state_store
                saga_store = get_saga_state_store()
                
                result_dict = {
                    "success": False,
                    "saga_id": message.saga_id,
                    "question": message.question,
                    "error_message": reason,
                    "formatted_response": f"As your Senior Business Intelligence Consultant, I've determined that this inquiry falls outside our current business focus and database scope. {reason}",
                    "call_stack": [entry.to_dict() for entry in message.call_stack],
                    "status": "error",
                    "is_irrelevant": True
                }
                saga_store.store_result(message.saga_id, result_dict, status="error")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            if not available_tables:
                # Fallback if LLM failed to list tables but said relevant
                print(f"[SAGA STEP 2] ⚠️ Relevant but no tables found. Proceeding with caution.")

            print(f"[SAGA STEP 2] ✓ Identified {len(available_tables)} tables via LLM")
            table_schemas = {name: {"name": name} for name in available_tables}
            
            next_message = TablesCheckedMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                schema_context=getattr(message, "schema_context", []),
                available_tables=available_tables,
                table_schemas=table_schemas,
                business_context=getattr(message, "business_context", []),
                business_documents_count=getattr(message, "business_documents_count", 0)
            )
            
            next_message.call_stack = message.call_stack.copy()
            next_message._current_tool_calls = message._current_tool_calls.copy()
            message._current_tool_calls = [] # Clear from original
            
            next_message.add_to_call_stack(
                step_name="check_tables_agentic",
                status="success",
                duration_ms=duration_ms,
                tables_found=len(available_tables),
                available_tables=available_tables,
                reason=reason
            )
            
            # Proceed to query generation
            publisher = SagaPublisher()
            publisher.publish_query_generation(next_message)
            
            # Update state store
            from agentic_sql.saga.state_store import get_saga_state_store
            saga_store = get_saga_state_store()
            saga_store.update_result(message.saga_id, {
                "call_stack": [entry.to_dict() for entry in next_message.call_stack]
            })
            
            ch.basic_ack(delivery_tag=method.delivery_tag)
            
        finally:
            db.close()
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 2] ✗ Error: {str(e)}")
        
        try:
            from agentic_sql.saga.messages import SagaErrorMessage
            error_message = SagaErrorMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                error_step="check_tables_agentic",
                error_message=str(e),
                error_details={"duration_ms": duration_ms}
            )
            
            message.add_to_call_stack(
                step_name="check_tables_agentic",
                status="error",
                duration_ms=duration_ms,
                error=str(e)
            )
            
            from agentic_sql.saga.state_store import get_saga_state_store
            saga_store = get_saga_state_store()
            
            error_dict = {
                "success": False,
                "saga_id": message.saga_id,
                "error_step": "check_tables_agentic",
                "error_message": str(e),
                "formatted_response": "As your Senior Business Intelligence Consultant, I encountered a technical hurdle while verifying your database schema. Please try again.",
                "call_stack": [entry.to_dict() for entry in message.call_stack],
                "status": "error"
            }
            saga_store.store_result(message.saga_id, error_dict, status="error")
            
            SagaPublisher().publish_error(error_message)
        except Exception:
            pass
        
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_tables_consumer(host: str = None):
    consumer = TablesConsumer(host=host)
    consumer.start_consuming()
