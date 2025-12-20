"""
Saga Step 1: Check Knowledge Base

Retrieves relevant schema context from ChromaDB knowledge base.
"""

import pika
import json
import time
from typing import List, Any
from agentic_sql.saga.messages import (
    QueryInitiatedMessage, KnowledgeBaseCheckedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from core.gemini_client import GeminiClient
from core.infra.chroma_factory import ChromaClientFactory

# Initialize clients
gemini_client = GeminiClient()

def run_async(coro):
    """Helper to run async coroutines in a synchronous context"""
    import asyncio
    import nest_asyncio
    nest_asyncio.apply()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

def retrieve_knowledge_context(account_id: str, question: str, message: Any = None):
    """Retrieve both schema and business context using MCP tools"""
    from core.mcp.client import ChromaMCPClient
    
    chroma_mcp = ChromaMCPClient()
    
    # 1. Retrieve Schema Context
    schema_args = {"query": question, "account_id": account_id, "n_results": 2}
    res_schema = run_async(chroma_mcp.call_tool("search_relevant_schema", schema_args, message=message))
    
    schema_context = [res_schema.content] if res_schema.success else []
    
    # 2. Retrieve Business Context
    # First extract keywords for better search
    kw_prompt = f"Extract 2-3 key business entities or concepts from this question for semantic search: '{question}'. Return only the keywords separated by spaces."
    kw_response = gemini_client.generate_content(kw_prompt)
    keywords = kw_response.text.strip() if kw_response else ""
    search_query = f"{question} {keywords}"
    
    biz_args = {"query": search_query, "account_id": account_id, "n_results": 1}
    res_biz = run_async(chroma_mcp.call_tool("search_business_knowledge", biz_args, message=message))
    
    business_context = [res_biz.content] if res_biz.success else []
    
    return schema_context, business_context, kw_prompt

def process_knowledge_base_check(ch, method, properties, body):
    """Process knowledge base check step"""
    start_time = time.time()
    
    try:
        # Parse message
        data = json.loads(body)
        message = message_from_dict(data, QueryInitiatedMessage)
        
        print(f"\n[SAGA STEP 1] Knowledge Base Check - Saga ID: {message.saga_id}")
        print(f"[SAGA STEP 1] Question: '{message.question}'")
        
        # Logic moved from QueryService
        schema_context, business_context, kw_prompt = retrieve_knowledge_context(message.account_id, message.question, message=message)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Create next message
        next_message = KnowledgeBaseCheckedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            schema_context=schema_context,
            schema_documents_count=len(schema_context),
            business_context=business_context,
            business_documents_count=len(business_context)
        )
        
        # Copy call stack and pending tool calls
        next_message.call_stack = message.call_stack.copy()
        next_message._current_tool_calls = message._current_tool_calls.copy()
        message._current_tool_calls = []
        
        # Add this step to call stack - will automatically pick up mcp tools from _current_tool_calls
        next_message.add_to_call_stack(
            step_name="check_knowledge_base",
            status="success",
            duration_ms=duration_ms,
            documents_retrieved=len(schema_context) + len(business_context),
            has_schema=len(schema_context) > 0,
            has_business=len(business_context) > 0,
            prompt=kw_prompt
        )
        
        print(f"[SAGA STEP 1] ✓ Step completed in {duration_ms:.2f}ms")
        
        # Publish to next step
        publisher = SagaPublisher()
        publisher.publish_tables_check(next_message)
        
        # Update progress in store
        from agentic_sql.saga.state_store import get_saga_state_store
        saga_store = get_saga_state_store()
        saga_store.update_result(message.saga_id, {
            "call_stack": [entry.to_dict() for entry in next_message.call_stack]
        })
        
        # Acknowledge message
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 1] ✗ Error: {str(e)}")
        
        # Create error message
        try:
            data = json.loads(body)
            message = message_from_dict(data, QueryInitiatedMessage)
            
            error_message = SagaErrorMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                error_step="check_knowledge_base",
                error_message=str(e),
                error_details={"duration_ms": duration_ms}
            )
            
            error_message.call_stack = message.call_stack.copy()
            error_message._current_tool_calls = message._current_tool_calls.copy()
            error_message.add_to_call_stack(
                step_name="check_knowledge_base",
                status="error",
                duration_ms=duration_ms,
                error=str(e)
            )
            
            # Publish error
            publisher = SagaPublisher()
            publisher.publish_error(error_message)
        except:
            pass
        
        # Negative acknowledgment - don't requeue
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_knowledge_base_consumer(host: str = None):
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
        queue_name = SagaPublisher.QUEUE_KNOWLEDGE_BASE
        channel.queue_declare(queue=queue_name, durable=True)
        
        # Set QoS - process one message at a time
        channel.basic_qos(prefetch_count=1)
        
        # Start consuming
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=process_knowledge_base_check
        )
        
        print(f"\n[SAGA STEP 1] Knowledge Base Consumer Started")
        print(f"[SAGA STEP 1] Waiting for messages on '{queue_name}'...")
        
        channel.start_consuming()
        
    except KeyboardInterrupt:
        print("\n[SAGA STEP 1] Shutting down...")
        channel.stop_consuming()
        connection.close()
    except Exception as e:
        print(f"[SAGA STEP 1] Failed to start consumer: {e}")

