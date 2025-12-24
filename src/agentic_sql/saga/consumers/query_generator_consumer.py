import asyncio
import pika
import json
import time
from typing import List, Dict, Any
from agentic_sql.saga.messages import (
    QueryInitiatedMessage, QueryGeneratedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from core.gemini_client import GeminiClient
from core.mcp.client import DatabaseMCPClient, ChromaMCPClient
from account.models import User
from core.database.session import get_db

def sanitize_for_json(obj):
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

def extract_tables_from_sql(sql: str) -> List[str]:
    import re
    pattern = r'(?:FROM|JOIN)\s+([a-zA-Z0-9_".]+)'
    matches = re.findall(pattern, sql, re.IGNORECASE)
    
    tables = []
    for match in matches:
        # Remove quotes and get the table name (last part of schema.table)
        table = match.strip().strip('"').strip('`').split('.')[-1].strip('"').strip('`')
        if table:
            tables.append(table.lower())
    return list(set(tables))

def run_agentic_sql_generation(message: QueryInitiatedMessage, db_config_dict: Dict[str, Any]) -> tuple[str, str, List[Dict]]:
    
    db_url = f"postgresql://{db_config_dict['username']}:{db_config_dict['password']}@{db_config_dict['host']}:{db_config_dict['port'] or 5432}/{db_config_dict['db_name']}"
    db_client = DatabaseMCPClient(db_url)
    chroma_client = ChromaMCPClient()
    
    # Setup Gemini with tools
    tools = [
        db_client.get_gemini_tool("list_tables", message=message),
        db_client.get_gemini_tool("describe_table", message=message),
        chroma_client.get_gemini_tool("search_relevant_schema", message=message),
        chroma_client.get_gemini_tool("search_business_knowledge", message=message)
    ]
    agent = GeminiClient(tools=tools)
    
    prompt = f"""You are a Senior SQL Analyst and Gatekeeper. Your goal is to write a PostgreSQL query for: "{message.question}"
    
    CRITICAL RULES:
    1. FIRST, use `list_tables` to see which tables exist.
    2. Then, use `search_relevant_schema` and `search_business_knowledge` to identify relevant tables and understand business rules.
    3. YOU MUST call `describe_table(table_name)` for EVERY table you include in your SQL to get the exact final column names.
    4. If the question is NOT related to the available database schema or business scope, state clearly that it is "OUT_OF_SCOPE" and explain why.
    5. If NO tables exist in the database, the answer is "OUT_OF_SCOPE".
    6. Return a list of used table names.
    
    STRATEGY:
    - Determine if the question is RELEVANT or OUT_OF_SCOPE.
    - If RELEVANT, formulate the exact PostgreSQL query.
    - If OUT_OF_SCOPE, provide a professional explanation.
    
    RESPONSE FORMAT (STRICT):
    DECISION: [RELEVANT / OUT_OF_SCOPE]
    REASONING: [Your explanation of the decision and the data found]
    SQL: [The final SQL query if RELEVANT, otherwise NONE]
    USED_TABLES: [Comma separated list of tables used in the SQL, or NONE]
    """
    
    chat = agent.model.start_chat(enable_automatic_function_calling=True)
    response = chat.send_message(prompt)
    
    full_text = response.text
    
    interaction_history = []
    try:
        for m in chat.history:
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
                    resp = part.function_response.response
                    if not isinstance(resp, (str, int, float, bool, list, dict, type(None))):
                        resp = str(resp)
                    
                    parts.append({
                        "function_response": {
                            "name": part.function_response.name,
                            "response": resp
                        }
                    })
            interaction_history.append({"role": role, "parts": parts})
    except Exception as e:
        print(f"[SAGA STEP 2/3] Warning: Failed to serialize full interaction history: {e}")
        interaction_history = [{"error": "Serialization failed", "details": str(e)}]

    is_out_of_scope = "DECISION: OUT_OF_SCOPE" in full_text or "DECISION: IRRELEVANT" in full_text
    
    reasoning = "N/A"
    if "REASONING:" in full_text:
        parts = full_text.split("REASONING:")
        if len(parts) > 1:
            reasoning = parts[1].split("SQL:")[0].strip()

    sql = ""
    if "SQL:" in full_text:
        sql_part = full_text.split("SQL:")[1].split("USED_TABLES:")[0].strip()
        if sql_part.upper() != "NONE":
            sql = sql_part
            
    sql = sql.replace("```sql", "").replace("```", "").strip()
    if sql.endswith(";"): sql = sql[:-1]

    # Double check out of scope keywords if decision wasn't explicitly caught
    out_of_scope_keywords = ["out of your business scope", "out of you bussiness scope", "not related to the", "cannot answer", "missing data", "not related to any available tables", "out of scope"]
    if not is_out_of_scope and not sql and any(kw in full_text.lower() for kw in out_of_scope_keywords):
        is_out_of_scope = True
        if reasoning == "N/A": reasoning = full_text.strip()
    
    # Capture usage metadata
    usage = {}
    if hasattr(response, "usage_metadata"):
        usage = {
            "prompt_token_count": response.usage_metadata.prompt_token_count,
            "candidates_token_count": response.usage_metadata.candidates_token_count,
            "total_token_count": response.usage_metadata.total_token_count
        }
            
    return sql, reasoning, prompt, usage, interaction_history, is_out_of_scope


from core.infra.consumer import BaseConsumer

class QueryGeneratorConsumer(BaseConsumer):
    def __init__(self, host: str = None):
        super().__init__(queue_name=SagaPublisher.QUEUE_GENERATE_QUERY, host=host)

    def process_message(self, ch, method, properties, body):
        process_query_generation(ch, method, properties, body)

def process_query_generation(ch, method, properties, body):
    start_time = time.time()
    
    try:
        data = json.loads(body)
        # Note: Now receiving QueryInitiatedMessage instead of TablesCheckedMessage
        message = message_from_dict(data, QueryInitiatedMessage)
        
        print(f"\n[SAGA STEP 2+3] Merged Agentic Query Check & Generation - Saga ID: {message.saga_id}")
        
        # Get DB config
        db_config_dict = {}
        from core.database.session import get_db
        from account.models import User
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
                "db_type": user.db_config.db_type
            }
        finally:
            db.close()

        generated_sql, llm_reasoning, llm_prompt, llm_usage, interaction_history, is_out_of_scope = run_agentic_sql_generation(message, db_config_dict)
        
        if is_out_of_scope:
            duration_ms = (time.time() - start_time) * 1000
            print(f"[SAGA STEP 2+3] 🛑 Question is OUT OF SCOPE: {llm_reasoning[:100]}...")
            
            # Update call stack
            message.add_to_call_stack(
                step_name="generate_query_agentic",
                status="failed",
                duration_ms=duration_ms,
                reason=llm_reasoning,
                is_out_of_scope=True
            )
            
            # Store final result as "Irrelevant" and stop
            from agentic_sql.saga.state_store import get_saga_state_store
            saga_store = get_saga_state_store()
            
            result_dict = {
                "success": False,
                "saga_id": message.saga_id,
                "question": message.question,
                "error_message": "Out of DB Context",
                "formatted_response": f"As your Senior Business Intelligence Consultant, I've determined that this inquiry falls outside our current business focus and database scope. {llm_reasoning}",
                "call_stack": [entry.to_dict() for entry in message.call_stack],
                "status": "error",
                "is_irrelevant": True
            }
            saga_store.store_result(message.saga_id, result_dict, status="error")
            
            # Acknowledge and stop saga
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return
        
        duration_ms = (time.time() - start_time) * 1000
        
        next_message = QueryGeneratedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            generated_sql=generated_sql,
            db_config=db_config_dict,
            business_context=getattr(message, "business_context", []),
            business_documents_count=getattr(message, "business_documents_count", 0)
        )
        
        next_message.call_stack = message.call_stack.copy()
        next_message._current_tool_calls = message._current_tool_calls.copy()
        message._current_tool_calls = []
        
        next_message.add_to_call_stack(
            step_name="generate_query_agentic",
            status="success",
            duration_ms=duration_ms,
            llm_reasoning=llm_reasoning,
            prompt=llm_prompt,
            usage=llm_usage,
            interaction_history=sanitize_for_json(interaction_history)
        )
        
        print(f"[SAGA STEP 2+3] Reasoning: {llm_reasoning[:200]}...")
        print(f"[SAGA STEP 2+3] Token Usage: {llm_usage}")
        print(f"[SAGA STEP 2+3] ✓ SQL generated in {duration_ms:.2f}ms")
        
        publisher = SagaPublisher()
        publisher.publish_query_execution(next_message)
        
        # Update state store
        from agentic_sql.saga.state_store import get_saga_state_store
        saga_store = get_saga_state_store()
        
        # Prepare result for storage, sanitizing any complex types
        result_update = {
            "call_stack": [entry.to_dict() for entry in next_message.call_stack],
            "generated_sql": generated_sql
        }
        
        saga_store.update_result(message.saga_id, sanitize_for_json(result_update))
        
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 3] ✗ Agentic Error: {str(e)}")
        
        try:
            from agentic_sql.saga.state_store import get_saga_state_store
            saga_store = get_saga_state_store()
            
            error_data = {
                "step_name": "generate_query_agentic",
                "status": "error",
                "duration_ms": duration_ms,
                "error": str(e)
            }
            
            if 'message' in locals():
                message.add_to_call_stack(**error_data)
                saga_store.update_result(message.saga_id, {
                    "call_stack": [entry.to_dict() for entry in message.call_stack],
                    "status": "error",
                    "error_message": str(e),
                    "formatted_response": "As your Senior Business Intelligence Consultant, I've encountered a challenge while trying to formulate a response to your question. This might be due to the complexity of the query or a transient technical issue. Please try rephrasing or submitting again."
                })
        except Exception as store_err:
            print(f"[SAGA STEP 3] Failed to log error to store: {store_err}")

        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def start_query_generator_consumer(host: str = None):
    consumer = QueryGeneratorConsumer(host=host)
    consumer.start_consuming()

