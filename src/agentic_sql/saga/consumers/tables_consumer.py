"""
Saga Step 2: Check Tables

Retrieves actual table information from user's database.
"""

import pika
import json
import time
from typing import List, Any
from agentic_sql.saga.messages import (
    TablesCheckedMessage,
    SagaErrorMessage, message_from_dict, QueryInitiatedMessage
)
from agentic_sql.saga.publisher import SagaPublisher
from core.services.database_service import database_service
from core.gemini_client import GeminiClient
from account.models import User
from core.database.session import get_db

# Initialize Gemini for relevance check
gemini_client = GeminiClient(model_name="models/gemini-2.0-flash")


def get_table_names_logic(db_config, message: Any = None) -> List[str]:
    """Logic to retrieve table names from user database"""
    print(f"[SAGA STEP 2] Checking available tables in user database...")
    # database_service.get_table_names returns List[str]
    try:
        available_tables = database_service.get_table_names(db_config, message=message)
        return available_tables if isinstance(available_tables, list) else []
    except Exception as e:
        print(f"[SAGA STEP 2] Error in get_table_names_logic: {e}")
        return []

def check_question_relevance(question: str, schema_context: List[str], business_context: List[str], tables: List[str]) -> tuple[bool, str]:
    """Check if the question is relevant to the available database context"""
    context_str = "\n".join(schema_context + business_context)
    tables_str = ", ".join(tables) if tables else "NONE (No tables found in database)"
    
    prompt = f"""
    You are a Gatekeeper for a SQL Query Engine. Your job is to strictly decide if a user's question is relevant to the specific database schema and business context provided below.
    
    AVAILABLE TABLES:
    {tables_str}
    
    BUSINESS RULES & SCHEMA FRAGMENTS:
    {context_str if context_str else "No additional business context found."}
    
    USER QUESTION: "{question}"
    
    RULES FOR DECISION:
    1. IRRELEVANT: The question is about general knowledge, sports (unrelated to these tables), entities not in the tables (e.g., "football players" when tables are about "retail orders"), or casual conversation.
    2. RELEVANT: The question asks for data, statistics, or reports that can be reasonably constructed using the tables and context provided. 
    3. If there are NO TABLES found, everything is IRRELEVANT unless it's a metadata question.
    
    RESPONSE FORMAT (You MUST follow this exactly):
    DECISION: [RELEVANT/IRRELEVANT]
    REASON: [A polite, professional explanation of why the question doesn't match the database context. Be specific about what data we HAVE vs what they ASKED.]
    """
    
    try:
        response = gemini_client.generate_content(prompt)
        if not response:
            return True, ""
            
        text = response.text
        is_relevant = "DECISION: RELEVANT" in text
        reason = ""
        if "REASON:" in text:
            reason = text.split("REASON:")[1].strip()
            
        return is_relevant, reason
    except Exception as e:
        print(f"[SAGA STEP 2] Relevance check failed: {e}")
        return True, "" # Default to relevant on error to avoid blocking valid queries

def process_tables_check(ch, method, properties, body):
    """Process tables check step"""
    start_time = time.time()
    
    try:
        # Parse message
        data = json.loads(body)
        message = message_from_dict(data, QueryInitiatedMessage)
        
        print(f"\n[SAGA STEP 2] Tables Check - Saga ID: {message.saga_id}")
        
        # Get user's DB config from database
        db = next(get_db())
        try:
            user = db.query(User).filter(User.id == message.user_id).first()
            if not user or not user.db_config:
                raise Exception("User or DB config not found")
            
            db_config = user.db_config
            
            # Logic moved from QueryService
            available_tables = get_table_names_logic(db_config, message=message)
            print(f"[SAGA STEP 2] Debug available_tables: {available_tables}")
            table_schemas = {name: {"name": name} for name in available_tables}
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Create next message
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
            
            # Copy call stack and pending tool calls
            next_message.call_stack = message.call_stack.copy()
            next_message._current_tool_calls = message._current_tool_calls.copy()
            message._current_tool_calls = [] # Clear from original
            
            # Add this step to call stack
            next_message.add_to_call_stack(
                step_name="check_tables",
                status="success",
                duration_ms=duration_ms,
                tables_found=len(available_tables),
                available_tables=available_tables
            )
            
            print(f"[SAGA STEP 2] ✓ Found {len(available_tables)} tables in {duration_ms:.2f}ms")
            
            if len(available_tables) == 0:
                error_msg = "No tables were found in the database. Please ensure your database connection is correct and that you have tables in the 'public' schema."
                print(f"[SAGA STEP 2] 🛑 {error_msg}")
                
                # Update call stack
                message.add_to_call_stack(
                    step_name="check_tables",
                    status="failed",
                    duration_ms=duration_ms,
                    error=error_msg
                )
                
                # Store final result as error
                from agentic_sql.saga.state_store import get_saga_state_store
                saga_store = get_saga_state_store()
                
                result_dict = {
                    "success": False,
                    "saga_id": message.saga_id,
                    "question": message.question,
                    "error_message": error_msg,
                    "formatted_response": "As your Senior Business Intelligence Consultant, I'm unable to provide insights because I couldn't find any data tables in your database. Please ensure your data is properly connected and synchronized.",
                    "call_stack": [entry.to_dict() for entry in message.call_stack],
                    "status": "error",
                    "is_irrelevant": True
                }
                saga_store.store_result(message.saga_id, result_dict, status="error")
                
                # Acknowledge and stop
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # Relevance Guardrail
            print(f"[SAGA STEP 2] Performing relevance check for: '{message.question}'...")
            is_relevant, irrelevant_reason = check_question_relevance(
                message.question, 
                getattr(message, "schema_context", []), 
                getattr(message, "business_context", []), 
                available_tables
            )
            
            if not is_relevant:
                print(f"[SAGA STEP 2] 🛑 Question is IRRELEVANT: {irrelevant_reason}")
                
                # Update call stack
                message.add_to_call_stack(
                    step_name="relevance_check",
                    status="failed",
                    duration_ms=(time.time() - start_time) * 1000,
                    reason=irrelevant_reason
                )
                
                # Store final result as "Irrelevant" and stop
                from agentic_sql.saga.state_store import get_saga_state_store
                saga_store = get_saga_state_store()
                
                result_dict = {
                    "success": False,
                    "saga_id": message.saga_id,
                    "question": message.question,
                    "error_message": irrelevant_reason,
                    "formatted_response": "As your Senior Business Intelligence Consultant, I've determined that this inquiry falls outside our current business focus and database scope. I am unable to provide a response for this request.",
                    "call_stack": [entry.to_dict() for entry in message.call_stack],
                    "status": "error",
                    "is_irrelevant": True
                }
                # Store as 'error' so the UI displays the reason
                saga_store.store_result(message.saga_id, result_dict, status="error")
                
                # Acknowledge and stop saga
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # If relevant, proceed to query generation
            publisher = SagaPublisher()
            publisher.publish_query_generation(next_message)
            
            # Update progress in store
            from agentic_sql.saga.state_store import get_saga_state_store
            saga_store = get_saga_state_store()
            saga_store.update_result(message.saga_id, {
                "call_stack": [entry.to_dict() for entry in next_message.call_stack]
            })
            
            # Acknowledge message
            ch.basic_ack(delivery_tag=method.delivery_tag)
            
        finally:
            db.close()
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 2] ✗ Error: {str(e)}")
        
        # Create error message
        try:
            data = json.loads(body)
            message = message_from_dict(data, QueryInitiatedMessage)
            
            error_message = SagaErrorMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                error_step="check_tables",
                error_message=str(e),
                error_details={"duration_ms": duration_ms}
            )
            
            error_message.call_stack = message.call_stack.copy()
            error_message._current_tool_calls = message._current_tool_calls.copy()
            error_message.add_to_call_stack(
                step_name="check_tables",
                status="error",
                duration_ms=duration_ms,
                error=str(e)
            )
            
            # Update state store
            from agentic_sql.saga.state_store import get_saga_state_store
            saga_store = get_saga_state_store()
            
            error_dict = {
                "success": False,
                "saga_id": message.saga_id,
                "error_step": "check_tables",
                "error_message": str(e),
                "formatted_response": "As your Senior Business Intelligence Consultant, I encountered a technical hurdle while verifying your database schema. Please ensure your database is accessible and try again.",
                "call_stack": [entry.to_dict() for entry in error_message.call_stack],
                "status": "error"
            }
            saga_store.store_result(message.saga_id, error_dict, status="error")
            
            # Publish error
            publisher = SagaPublisher()
            publisher.publish_error(error_message)
        except Exception as store_err:
            print(f"[SAGA STEP 2] Failed to log error to store: {store_err}")
        
        # Negative acknowledgment - don't requeue
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_tables_consumer(host: str = None):
    """Start the tables check consumer"""
    from agentic_sql.saga.publisher import SagaPublisher
    
    host = host or "localhost"
    
    try:
        # Setup connection
        credentials = pika.PlainCredentials('guest', 'guest')
        parameters = pika.ConnectionParameters(
            host=host,
            credentials=credentials,
            heartbeat=600
        )
        
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        
        # Declare queue
        queue_name = SagaPublisher.QUEUE_CHECK_TABLES
        channel.queue_declare(queue=queue_name, durable=True)
        
        # Set QoS
        channel.basic_qos(prefetch_count=1)
        
        # Start consuming
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=process_tables_check
        )
        
        print(f"\n[SAGA STEP 2] Tables Check Consumer Started")
        print(f"[SAGA STEP 2] Waiting for messages on '{queue_name}'...")
        
        channel.start_consuming()
        
    except KeyboardInterrupt:
        print("\n[SAGA STEP 2] Shutting down...")
        channel.stop_consuming()
        connection.close()
    except Exception as e:
        print(f"[SAGA STEP 2] Failed to start consumer: {e}")
