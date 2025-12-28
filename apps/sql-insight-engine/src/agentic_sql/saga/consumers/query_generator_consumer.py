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
from core.mcp.client import initialize_mcp, get_discovered_tools
from account.models import User
from agentic_sql.saga.utils import sanitize_for_json, update_saga_state, store_saga_error, get_interaction_history

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

def run_agentic_sql_generation(message: QueryInitiatedMessage, db_config_dict: Dict[str, Any]) -> tuple[str, str, str, Dict, List, bool]:
    
    db_url = f"postgresql://{db_config_dict['username']}:{db_config_dict['password']}@{db_config_dict['host']}:{db_config_dict['port'] or 5432}/{db_config_dict['db_name']}"
    tools = get_discovered_tools(message=message, context={"db_url": db_url, "account_id": message.account_id})
    agent = GeminiClient(tools=tools)
    
    prompt = f"""You are a Senior SQL Analyst and Gatekeeper. Your goal is to write a PostgreSQL query for: "{message.question}"
    
    DATABASE CONNECTION INFO:
    Use this db_url for any database tools: postgresql://{db_config_dict['username']}:{db_config_dict['password']}@{db_config_dict['host']}:{db_config_dict['port'] or 5432}/{db_config_dict['db_name']}

    CRITICAL RULES:
    1. FIRST, use `list_tables(db_url=...)` to see which tables exist.
    2. Then, use `search_relevant_schema(query=..., account_id=..., n_results=...)` to identify relevant tables.
    3. YOU MUST call `describe_table(table_name=..., db_url=...)` for EVERY table you include in your SQL to get the exact column names.
    4. If the question is NOT related to the available database schema or business scope, state clearly that it is "OUT_OF_SCOPE" and explain why.
    5. Return a list of used table names.
    
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
    print(f"[TRACE] Starting Gemini chat for saga {message.saga_id}")
    chat = agent.start_chat(enable_automatic_function_calling=True)
    print(f"[TRACE] Sending message to Gemini for saga {message.saga_id}")
    response = chat.send_message(prompt)
    print(f"[TRACE] Received response from Gemini for saga {message.saga_id}")
    try:
        full_text = response.text or ""
    except (ValueError, AttributeError):
        full_text = ""
    
    if not full_text:
        # Check if it was a function call only
        print(f"[TRACE] Gemini response has no text, checking for function calls...")
        # Since enable_automatic_function_calling=True, Gemini might have called the tools.
        # If it still has no text after tools, we might need a follow-up or just assume it's thinking.
        # But usually at the end of automatic calling it should provide text.
        pass
    
    interaction_history = get_interaction_history(chat)

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
        
        print(f"\n[SAGA STEP 1] Merged Agentic Query Check & Generation - Saga ID: {message.saga_id}")
        
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
            print(f"[SAGA STEP 1] 🛑 Question is OUT OF SCOPE: {llm_reasoning[:100]}...")
            
            store_saga_error(
                message=message,
                error_step="generate_query_agentic",
                error_msg=llm_reasoning,
                duration_ms=duration_ms,
                formatted_response=f"As your Senior Business Intelligence Consultant, I've determined that this inquiry falls outside our current business focus and database scope. {llm_reasoning}",
                is_out_of_scope=True
            )
            
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
            reasoning=llm_reasoning,
            db_config=db_config_dict,
            business_context=getattr(message, "business_context", []),
            business_documents_count=getattr(message, "business_documents_count", 0)
        )
        
        next_message.call_stack = message.call_stack.copy()
        next_message.all_tool_calls = message.all_tool_calls.copy()
        next_message._current_tool_calls = message._current_tool_calls.copy()
        message._current_tool_calls = []
        
        next_message.add_to_call_stack(
            step_name="generate_query_agentic",
            status="success",
            duration_ms=duration_ms,
            reasoning=llm_reasoning,
            prompt=llm_prompt,
            response=llm_reasoning,
            usage=llm_usage,
            tools_used=sanitize_for_json(next_message._current_tool_calls.copy()),
            interaction_history=interaction_history
        )
        
        print(f"[SAGA STEP 1] Reasoning: {llm_reasoning[:200]}...")
        print(f"[SAGA STEP 1] Token Usage: {llm_usage}")
        print(f"[SAGA STEP 1] ✓ SQL generated in {duration_ms:.2f}ms")
        
        publisher = SagaPublisher()
        publisher.publish_query_execution(next_message)
        
        update_saga_state(message.saga_id, next_message.to_dict())
        
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 1] ✗ Agentic Error: {str(e)}")
        
        store_saga_error(
            message=message,
            error_step="generate_query_agentic",
            error_msg=str(e),
            duration_ms=duration_ms
        )

        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def start_query_generator_consumer(host: str = None):
    consumer = QueryGeneratorConsumer(host=host)
    consumer.start_consuming()

