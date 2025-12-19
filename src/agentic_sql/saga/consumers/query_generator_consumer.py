import asyncio
import pika
import json
import time
from typing import List, Dict, Any
from agentic_sql.saga.messages import (
    TablesCheckedMessage, QueryGeneratedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from core.gemini_client import GeminiClient
from core.mcp.client import DatabaseMCPClient, ChromaMCPClient
from account.models import User
from core.database.session import get_db
from core.database.session import get_db

def sanitize_for_json(obj):
    """Deeply sanitize an object for JSON serialization, handling Gemini specific types like MapComposite"""
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
    """Extract table names from SQL SELECT query"""
    import re
    # Match words after FROM or JOIN, ignoring subqueries and common SQL keywords
    # This is a basic regex-based extraction
    pattern = r'(?:FROM|JOIN)\s+([a-zA-Z0-9_".]+)'
    matches = re.findall(pattern, sql, re.IGNORECASE)
    
    tables = []
    for match in matches:
        # Remove quotes and get the table name (last part of schema.table)
        table = match.strip().strip('"').strip('`').split('.')[-1].strip('"').strip('`')
        if table:
            tables.append(table.lower())
    return list(set(tables))

def run_agentic_sql_generation(message: TablesCheckedMessage, db_config_dict: Dict[str, Any]) -> tuple[str, str, List[Dict]]:
    
    db_url = f"postgresql://{db_config_dict['username']}:{db_config_dict['password']}@{db_config_dict['host']}:{db_config_dict['port'] or 5432}/{db_config_dict['db_name']}"
    db_client = DatabaseMCPClient(db_url)
    chroma_client = ChromaMCPClient()
    
    def search_relevant_schema(query: str) -> str:
        res = run_async(chroma_client.call_tool("search_relevant_schema", {
            "query": query, 
            "account_id": message.account_id
        }))
        return res.content if res.success else f"Error: {res.error}"

    def search_business_knowledge(query: str) -> str:
        res = run_async(chroma_client.call_tool("search_business_knowledge", {
            "query": query, 
            "account_id": message.account_id
        }))
        return res.content if res.success else f"Error: {res.error}"

    def describe_table(table_name: str) -> str:
        res = run_async(db_client.call_tool("describe_table", {"table_name": table_name}))
        return res.content if res.success else f"Error: {res.error}"

    def list_tables() -> str:
        res = run_async(db_client.call_tool("list_tables", {}))
        return res.content if res.success else f"Error: {res.error}"

    # Setup Gemini with tools
    tools = [search_relevant_schema, search_business_knowledge, describe_table, list_tables]
    agent = GeminiClient(tools=tools)
    
    # Format business context if available
    business_context_str = ""
    if hasattr(message, 'business_context') and message.business_context:
        business_context_str = "\nBUSINESS CONTEXT:\n" + "\n".join([f"- {doc}" for doc in message.business_context])

    prompt = f"""You are an Agentic SQL Analyst. Your goal is to write a PostgreSQL query for: "{message.question}"
    {business_context_str}
    
    CRITICAL RULES:
    1. NEVER ASSUME table or column names. 
    2. YOU MUST call `describe_table(table_name)` for EVERY table you include in your SQL. If you don't describe it, your answer will be rejected.
    3. If the question requires data that isn't in any of the available tables, DO NOT invent tables or columns. State clearly that the data is missing.
    4. Only use the tables listed below as "AVAILABLE REAL TABLES".
    
    AVAILABLE REAL TABLES: {", ".join(message.available_tables) if message.available_tables else "NONE"}
    
    STRATEGY:
    1. Identify which tables from the available list are likely relevant.
    2. Use search_relevant_schema and search_business_knowledge to confirm business rules.
    3. CALL describe_table for each relevant table.
    4. Write the final SQL query.
    
    Once you have enough information, reply with:
    REASONING: [Your explanation]
    SQL: [The final SQL query]
    """
    
    # Start the agentic loop
    chat = agent.model.start_chat(enable_automatic_function_calling=True)
    response = chat.send_message(prompt)
    
    full_text = response.text
    
    # Capture full interaction history for debugging
    interaction_history = []
    try:
        for message in chat.history:
            role = message.role
            parts = []
            for part in message.parts:
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
                    # Sanitize response for JSON serialization
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
        print(f"[SAGA STEP 3] Warning: Failed to serialize full interaction history: {e}")
        interaction_history = [{"error": "Serialization failed", "details": str(e)}]

    # Simple parser for the standard output format
    reasoning = "N/A"
    sql = ""
    if "SQL:" in full_text:
        parts = full_text.split("SQL:")
        sql = parts[1].strip()
        reasoning = parts[0].replace("REASONING:", "").strip()
    else:
        sql = full_text.strip()
        
    # Clean SQL
    sql = sql.replace("```sql", "").replace("```", "").strip()
    if sql.endswith(";"): sql = sql[:-1]
    
    # Capture tool calls for the call stack
    tool_history = []
    if response.candidates and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if part.function_call:
                tool_history.append({
                    "tool": part.function_call.name,
                    "args": dict(part.function_call.args)
                })

    # Capture usage metadata if available
    usage = {}
    if hasattr(response, "usage_metadata"):
        usage = {
            "prompt_token_count": response.usage_metadata.prompt_token_count,
            "candidates_token_count": response.usage_metadata.candidates_token_count,
            "total_token_count": response.usage_metadata.total_token_count
        }
            
    return sql, reasoning, tool_history, prompt, usage, interaction_history

def run_async(coro):
    """Helper to run async coroutines in a synchronous context"""
    import nest_asyncio
    nest_asyncio.apply()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

def process_query_generation(ch, method, properties, body):
    """Process query generation step using async agentic loop"""
    start_time = time.time()
    
    try:
        data = json.loads(body)
        message = message_from_dict(data, TablesCheckedMessage)
        
        print(f"\n[SAGA STEP 3] Agentic Query Generation - Saga ID: {message.saga_id}")
        
        # Get DB config
        db_config_dict = {}
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

        # Run the synchronous agentic loop
        generated_sql, llm_reasoning, tool_history, llm_prompt, llm_usage, interaction_history = run_agentic_sql_generation(message, db_config_dict)
        
        # SQL Table Validation
        used_tables = extract_tables_from_sql(generated_sql)
        available_tables_lower = [t.lower() for t in message.available_tables]
        
        # Only validate if we actually have tables in the DB
        invalid_tables = [t for t in used_tables if t not in available_tables_lower]
        
        if invalid_tables and message.available_tables:
            error_msg = f"Hallucination detected! The generated SQL uses tables that do NOT exist in the database: {', '.join(invalid_tables)}. Available tables are: {', '.join(message.available_tables)}"
            print(f"[SAGA STEP 3] 🛑 {error_msg}")
            raise Exception(error_msg)
        
        # If no tables found at all, but SQL was generated, check if it's a dummy/hallucinated query
        if not message.available_tables and used_tables:
            error_msg = "No tables found in your database, but the AI tried to query tables anyway. This usually means the question is irrelevant to your data."
            print(f"[SAGA STEP 3] 🛑 {error_msg}")
            raise Exception(error_msg)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Create next message
        next_message = QueryGeneratedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            schema_context=message.schema_context, # Keep for backward compatibility/logs
            generated_sql=generated_sql,
            db_config=db_config_dict,
            business_context=getattr(message, "business_context", []),
            business_documents_count=getattr(message, "business_documents_count", 0)
        )
        
        next_message.call_stack = message.call_stack.copy()
        # Add this step to call stack
        next_message.add_to_call_stack(
            step_name="generate_query_agentic",
            status="success",
            duration_ms=duration_ms,
            tools_used=sanitize_for_json(tool_history),
            llm_reasoning=llm_reasoning,
            prompt=llm_prompt,
            usage=llm_usage,
            interaction_history=sanitize_for_json(interaction_history)
        )
        
        print(f"[SAGA STEP 3] Reasoning: {llm_reasoning[:200]}...")
        print(f"[SAGA STEP 3] Token Usage: {llm_usage}")
        print(f"[SAGA STEP 3] ✓ SQL generated in {duration_ms:.2f}ms using {len(tool_history)} tools")
        
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
        
        # Log error to state store
        try:
            from agentic_sql.saga.state_store import get_saga_state_store
            saga_store = get_saga_state_store()
            
            # Create a mock message to add to call stack if real one failed early
            error_data = {
                "step_name": "generate_query_agentic",
                "status": "error",
                "duration_ms": duration_ms,
                "error": str(e)
            }
            
            # If we have the original message, we can append to its call stack
            if 'message' in locals():
                message.add_to_call_stack(**error_data)
                saga_store.update_result(message.saga_id, {
                    "call_stack": [entry.to_dict() for entry in message.call_stack],
                    "status": "error",
                    "error_message": str(e)
                })
        except Exception as store_err:
            print(f"[SAGA STEP 3] Failed to log error to store: {store_err}")

        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def start_query_generator_consumer(host: str = None):
    host = host or "localhost"
    try:
        credentials = pika.PlainCredentials('guest', 'guest')
        parameters = pika.ConnectionParameters(host=host, credentials=credentials, heartbeat=600)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        queue_name = SagaPublisher.QUEUE_GENERATE_QUERY
        channel.queue_declare(queue=queue_name, durable=True)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=queue_name, on_message_callback=process_query_generation)
        print(f"\n[SAGA STEP 3] Agentic Query Generator Started")
        channel.start_consuming()
    except Exception as e:
        print(f"[SAGA STEP 3] Failed: {e}")

