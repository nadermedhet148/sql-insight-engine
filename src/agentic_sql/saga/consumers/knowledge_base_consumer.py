"""
Saga Step 1: Check Knowledge Base

Retrieves relevant schema context from ChromaDB knowledge base.
"""

import pika
import json
import time
from typing import List
from agentic_sql.saga.messages import (
    QueryInitiatedMessage, KnowledgeBaseCheckedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from core.gemini_client import GeminiClient
from core.infra.chroma_factory import ChromaClientFactory

# Initialize clients
gemini_client = GeminiClient()

def get_chroma_client():
    return ChromaClientFactory.get_client()

def retrieve_schema_context(account_id: str, question: str, collection_name: str = "account_schema_info") -> List[str]:
    """Retrieve schema information from ChromaDB"""
    try:
        chroma_client = get_chroma_client()
        
        # Get or create collection
        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        
        # Generate embedding for the question
        query_embedding = gemini_client.get_embedding(question, task_type="retrieval_query")
        
        # Query ChromaDB for relevant schema information
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=5,
            where={"account_id": account_id}
        )
        
        # Extract documents
        if results and results.get('documents') and len(results['documents']) > 0:
            context_docs = results['documents'][0]
            print(f"[SAGA STEP 1] Retrieved {len(context_docs)} schema documents")
            return context_docs
        else:
            print("[SAGA STEP 1] No schema context found")
            return []
            
    except Exception as e:
        print(f"[SAGA STEP 1] Error retrieving schema context: {e}")
        return []

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
        schema_context = retrieve_schema_context(message.account_id, message.question)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Create next message
        next_message = KnowledgeBaseCheckedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            schema_context=schema_context,
            schema_documents_count=len(schema_context)
        )
        
        # Copy call stack
        next_message.call_stack = message.call_stack.copy()
        
        # Add this step to call stack
        next_message.add_to_call_stack(
            step_name="check_knowledge_base",
            status="success",
            duration_ms=duration_ms,
            documents_retrieved=len(schema_context),
            has_context=len(schema_context) > 0
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

