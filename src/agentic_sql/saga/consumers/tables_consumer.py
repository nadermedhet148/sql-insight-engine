"""
Saga Step 2: Check Tables

Retrieves actual table information from user's database.
"""

import pika
import json
import time
from typing import List
from agentic_sql.saga.messages import (
    KnowledgeBaseCheckedMessage, TablesCheckedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from core.services.database_service import database_service
from account.models import User
from core.database.session import get_db


def get_table_names_logic(db_config) -> List[str]:
    """Logic to retrieve table names from user database"""
    print(f"[SAGA STEP 2] Checking available tables in user database...")
    # database_service.get_table_names returns List[str]
    available_tables = database_service.get_table_names(db_config)
    return available_tables


def process_tables_check(ch, method, properties, body):
    """Process tables check step"""
    start_time = time.time()
    
    try:
        # Parse message
        data = json.loads(body)
        message = message_from_dict(data, KnowledgeBaseCheckedMessage)
        
        print(f"\n[SAGA STEP 2] Tables Check - Saga ID: {message.saga_id}")
        
        # Get user's DB config from database
        db = next(get_db())
        try:
            user = db.query(User).filter(User.id == message.user_id).first()
            if not user or not user.db_config:
                raise Exception("User or DB config not found")
            
            db_config = user.db_config
            
            # Logic moved from QueryService
            available_tables = get_table_names_logic(db_config)
            table_schemas = {name: {"name": name} for name in available_tables}
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Create next message
            next_message = TablesCheckedMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                schema_context=message.schema_context,
                available_tables=available_tables,
                table_schemas=table_schemas
            )
            
            # Copy call stack
            next_message.call_stack = message.call_stack.copy()
            
            # Add this step to call stack
            next_message.add_to_call_stack(
                step_name="check_tables",
                status="success",
                duration_ms=duration_ms,
                tables_found=len(available_tables),
                available_tables=available_tables
            )
            
            print(f"[SAGA STEP 2] ✓ Found {len(available_tables)} tables in {duration_ms:.2f}ms")
            
        # Publish to next step
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
            message = message_from_dict(data, KnowledgeBaseCheckedMessage)
            
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
            error_message.add_to_call_stack(
                step_name="check_tables",
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
