"""
Saga Step 4: Execute SQL Query

Executes the generated SQL query on user's database.
"""

import pika
import json
import time
from agentic_sql.saga.messages import (
    QueryGeneratedMessage, QueryExecutedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from core.services.database_service import database_service
from account.models import UserDBConfig


def process_query_execution(ch, method, properties, body):
    """Process query execution step"""
    start_time = time.time()
    
    try:
        # Parse message
        data = json.loads(body)
        message = message_from_dict(data, QueryGeneratedMessage)
        
        print(f"\n[SAGA STEP 4] Query Execution - Saga ID: {message.saga_id}")
        
        # Reconstruct DB config object
        db_config = UserDBConfig(
            host=message.db_config.get("host"),
            port=message.db_config.get("port"),
            db_name=message.db_config.get("db_name"),
            username=message.db_config.get("username"),
            password=message.db_config.get("password"),
            db_type=message.db_config.get("db_type", "postgresql")
        )
        
        # Logic calling database_service (no QueryService needed)
        print(f"[SAGA STEP 4] Executing SQL on user database...")
        execution_result = database_service.execute_query(db_config, message.generated_sql)
        
        duration_ms = (time.time() - start_time) * 1000
        
        if not execution_result.success:
            print(f"[SAGA STEP 4] ✗ Query execution failed: {execution_result.error}")
            
            error_message = SagaErrorMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                error_step="execute_query",
                error_message=execution_result.error,
                error_details={
                    "duration_ms": duration_ms,
                    "sql": message.generated_sql
                }
            )
            
            error_message.call_stack = message.call_stack.copy()
            error_message.add_to_call_stack(
                step_name="execute_query",
                status="error",
                duration_ms=duration_ms,
                error=execution_result.error
            )
            
            publisher = SagaPublisher()
            publisher.publish_error(error_message)
            
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return
        
        # Success
        raw_results = execution_result.data
        result_lines = raw_results.split('\n') if raw_results else []
        
        print(f"[SAGA STEP 4] ✓ Query executed successfully in {duration_ms:.2f}ms")
        
        # Create next message
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
        
        # Copy call stack
        next_message.call_stack = message.call_stack.copy()
        
        # Add this step to call stack
        next_message.add_to_call_stack(
            step_name="execute_query",
            status="success",
            duration_ms=duration_ms,
            result_lines=len(result_lines)
        )
        
        # Publish to next step
        publisher = SagaPublisher()
        publisher.publish_result_formatting(next_message)
        
        # Update progress in store
        from agentic_sql.saga.state_store import get_saga_state_store
        saga_store = get_saga_state_store()
        saga_store.update_result(message.saga_id, {
            "call_stack": [entry.to_dict() for entry in next_message.call_stack],
            "raw_results": raw_results
        })
        
        # Acknowledge message
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 4] ✗ Error: {str(e)}")
        
        # Create error message
        try:
            data = json.loads(body)
            message = message_from_dict(data, QueryGeneratedMessage)
            
            error_message = SagaErrorMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                error_step="execute_query",
                error_message=str(e),
                error_details={"duration_ms": duration_ms}
            )
            
            error_message.call_stack = message.call_stack.copy()
            error_message.add_to_call_stack(
                step_name="execute_query",
                status="error",
                duration_ms=duration_ms,
                error=str(e)
            )
            
            # Publish error
            publisher = SagaPublisher()
            publisher.publish_error(error_message)
        except:
            pass
        
        # Negative acknowledgment
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_query_executor_consumer(host: str = None):
    """Start the query executor consumer"""
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
        queue_name = SagaPublisher.QUEUE_EXECUTE_QUERY
        channel.queue_declare(queue=queue_name, durable=True)
        
        # Set QoS
        channel.basic_qos(prefetch_count=1)
        
        # Start consuming
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=process_query_execution
        )
        
        print(f"\n[SAGA STEP 4] Query Executor Consumer Started")
        print(f"[SAGA STEP 4] Waiting for messages on '{queue_name}'...")
        
        channel.start_consuming()
        
    except KeyboardInterrupt:
        print("\n[SAGA STEP 4] Shutting down...")
        channel.stop_consuming()
        connection.close()
    except Exception as e:
        print(f"[SAGA STEP 4] Failed to start consumer: {e}")

