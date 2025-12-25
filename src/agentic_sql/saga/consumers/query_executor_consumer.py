import asyncio
import json
import time
from typing import Dict, Any, List
from agentic_sql.saga.messages import (
    QueryGeneratedMessage, QueryExecutedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from core.gemini_client import GeminiClient
from core.mcp.client import DatabaseMCPClient
from agentic_sql.saga.utils import sanitize_for_json, update_saga_state, store_saga_error, get_interaction_history



def run_query_agentic(message: QueryGeneratedMessage, db_config_dict: Dict[str, Any]) -> tuple[bool, str, str, List[Dict[str, Any]]]:
    db_url = f"postgresql://{db_config_dict['username']}:{db_config_dict['password']}@{db_config_dict['host']}:{db_config_dict['port'] or 5432}/{db_config_dict['db_name']}"
    db_client = DatabaseMCPClient(db_url)
    
    tools = [db_client.get_gemini_tool("run_query", message=message)]
    agent = GeminiClient(tools=tools)
    
    prompt = f"""
    You are a Database Operations Agent. Your task is to execute the following SQL query and return the results.
    
    SQL QUERY:
    {message.generated_sql}
    
    INSTRUCTIONS:
    1. Call the `run_query` tool with the provided SQL.
    2. If the query is successful, return the exact raw results.
    3. If the query fails with an error, explain the error clearly.
    
    RESPONSE FORMAT:
    STATUS: [SUCCESS/FAILED]
    RESULTS: [The raw table results or the error message]
    """
    
    try:
        chat = agent.model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(prompt)
        text = response.text
        
        success = "STATUS: SUCCESS" in text
        results = ""
        if "RESULTS:" in text:
            results = text.split("RESULTS:")[1].strip()
            
        interaction_history = get_interaction_history(chat)
        return success, results, text, interaction_history
    except Exception as e:
        print(f"[SAGA STEP 4] Agentic query execution failed: {e}")
        return False, str(e), "Execution error", []

from core.infra.consumer import BaseConsumer

class QueryExecutorConsumer(BaseConsumer):
    def __init__(self, host: str = None):
        super().__init__(queue_name=SagaPublisher.QUEUE_EXECUTE_QUERY, host=host)

    def process_message(self, ch, method, properties, body):
        process_query_execution(ch, method, properties, body)

def process_query_execution(ch, method, properties, body):
    """Process query execution step"""
    start_time = time.time()
    
    try:
        # Parse message
        data = json.loads(body)
        message = message_from_dict(data, QueryGeneratedMessage)
        
        print(f"\n[SAGA STEP 4] Query Execution (Agentic) - Saga ID: {message.saga_id}")
        
        # db_config_dict for MCP client
        db_config_dict = message.db_config
        
        # Agentic query execution
        success, raw_results, reasoning, interaction_history = run_query_agentic(message, db_config_dict)
        
        duration_ms = (time.time() - start_time) * 1000
        
        if not success:
            print(f"[SAGA STEP 4] ✗ Agentic execution failed: {raw_results[:100]}...")
            
            store_saga_error(
                message=message,
                error_step="execute_query_agentic",
                error_msg=raw_results,
                duration_ms=duration_ms,
                reasoning=reasoning,
                sql=message.generated_sql
            )
            
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return
        
        result_lines = raw_results.split('\n') if raw_results else []
        print(f"[SAGA STEP 4] ✓ Query executed successfully in {duration_ms:.2f}ms")
        
        next_message = QueryExecutedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            generated_sql=message.generated_sql,
            raw_results=raw_results,
            execution_success=True,
            execution_error=None
        )
        
        next_message.call_stack = message.call_stack.copy()
        next_message._current_tool_calls = message._current_tool_calls.copy()
        message._current_tool_calls = []
        
        next_message.add_to_call_stack(
            step_name="execute_query_agentic",
            status="success",
            duration_ms=duration_ms,
            result_lines=len(result_lines),
            sql=message.generated_sql,
            reasoning=reasoning,
            interaction_history=interaction_history
        )
        
        # Publish to next step
        publisher = SagaPublisher()
        publisher.publish_result_formatting(next_message)
        
        update_saga_state(message.saga_id, {
            "call_stack": [entry.to_dict() for entry in next_message.call_stack],
            "raw_results": raw_results
        })
        
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 4] ✗ Error: {str(e)}")
        
        store_saga_error(
            message=message,
            error_step="execute_query_agentic",
            error_msg=str(e),
            duration_ms=duration_ms
        )
        
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_query_executor_consumer(host: str = None):
    consumer = QueryExecutorConsumer(host=host)
    consumer.start_consuming()

