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

    def describe_table(table_name: str) -> str:
        res = run_async(db_client.call_tool("describe_table", {"table_name": table_name}))
        return res.content if res.success else f"Error: {res.error}"

    def list_tables() -> str:
        res = run_async(db_client.call_tool("list_tables", {}))
        return res.content if res.success else f"Error: {res.error}"

    # Setup Gemini with tools
    tools = [search_relevant_schema, describe_table, list_tables]
    agent = GeminiClient(tools=tools)
    
    prompt = f"""You are an Agentic SQL Analyst. Your goal is to write a PostgreSQL query for: "{message.question}"
    
    STRATEGY:
    1. First, list all tables to see what's available.
    2. Then, use search_relevant_schema to find which tables are most likely to contain the data needed.
    3. Use describe_table to get the exact column names and types for the tables you identified.
    4. Finally, generate the SQL query and explain your reasoning.
    
    Once you have enough information, reply with:
    REASONING: [Your explanation]
    SQL: [The final SQL query]
    """
    
    # Start the agentic loop
    chat = agent.model.start_chat(enable_automatic_function_calling=True)
    response = chat.send_message(prompt)
    
    full_text = response.text
    
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
            
    return sql, reasoning, tool_history, prompt, usage

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
        generated_sql, llm_reasoning, tool_history, llm_prompt, llm_usage = run_agentic_sql_generation(message, db_config_dict)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Create next message
        next_message = QueryGeneratedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            schema_context=message.schema_context, # Keep for backward compatibility/logs
            generated_sql=generated_sql,
            db_config=db_config_dict
        )
        
        next_message.call_stack = message.call_stack.copy()
        next_message.add_to_call_stack(
            step_name="generate_query_agentic",
            status="success",
            duration_ms=duration_ms,
            tools_used=tool_history,
            llm_reasoning=llm_reasoning,
            prompt=llm_prompt,
            usage=llm_usage
        )
        
        print(f"[SAGA STEP 3] Reasoning: {llm_reasoning[:200]}...")
        print(f"[SAGA STEP 3] Token Usage: {llm_usage}")
        print(f"[SAGA STEP 3] ✓ SQL generated in {duration_ms:.2f}ms using {len(tool_history)} tools")
        
        publisher = SagaPublisher()
        publisher.publish_query_execution(next_message)
        
        # Update state store
        from agentic_sql.saga.state_store import get_saga_state_store
        saga_store = get_saga_state_store()
        saga_store.update_result(message.saga_id, {
            "call_stack": [entry.to_dict() for entry in next_message.call_stack],
            "generated_sql": generated_sql
        })
        
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 3] ✗ Agentic Error: {str(e)}")
        # Error handling logic...
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

