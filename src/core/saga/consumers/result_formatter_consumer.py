"""
Saga Step 5: Format Result

Formats the query result using Gemini LLM and stores final result.
This is the final step in the saga.
"""

import pika
import json
import time
from core.saga.messages import (
    QueryExecutedMessage, ResultFormattedMessage,
    SagaErrorMessage, message_from_dict
)
from core.saga.publisher import SagaPublisher
from core.saga.state_store import get_saga_state_store
from core.gemini_client import GeminiClient

# Initialize client
gemini_client = GeminiClient()

def format_results_logic(question: str, sql_query: str, raw_results: str) -> str:
    """Logic to format results using Gemini LLM"""
    try:
        prompt = f"""You are a data analyst assistant. Format the following query results into a clear, natural language response.

        Original Question: "{question}"

        SQL Query Executed:
        {sql_query}

        Query Results:
        {raw_results}

        Instructions:
        - Provide a clear, concise answer to the original question
        - If the results contain numeric data, highlight the key insights
        - If it's a list, summarize the top items
        - If there are no results, explain that clearly
        - Keep the response conversational and easy to understand
        - Do not include technical jargon unless necessary

        Response:"""
        
        formatted_response = gemini_client.generate_content(prompt)
        return formatted_response.strip()
        
    except Exception as e:
        print(f"[SAGA STEP 5] Error formatting results: {e}")
        return f"Here are the results:\n\n{raw_results}"


def process_result_formatting(ch, method, properties, body):
    """Process result formatting step - FINAL STEP"""
    start_time = time.time()
    saga_store = get_saga_state_store()
    
    try:
        # Parse message
        data = json.loads(body)
        message = message_from_dict(data, QueryExecutedMessage)
        
        print(f"\n[SAGA STEP 5] Result Formatting - Saga ID: {message.saga_id}")
        
        # Logic moved from QueryService
        print(f"[SAGA STEP 5] Formatting results using Gemini LLM...")
        formatted_response = format_results_logic(
            message.question,
            message.generated_sql,
            message.raw_results
        )
        
        duration_ms = (time.time() - start_time) * 1000
        
        print(f"[SAGA STEP 5] ✓ Results formatted successfully in {duration_ms:.2f}ms")
        
        # Create final result message
        final_message = ResultFormattedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            generated_sql=message.generated_sql,
            raw_results=message.raw_results,
            formatted_response=formatted_response,
            success=True,
            error=None
        )
        
        # Copy call stack
        final_message.call_stack = message.call_stack.copy()
        
        # Add this step to call stack
        final_message.add_to_call_stack(
            step_name="format_result",
            status="success",
            duration_ms=duration_ms,
            response_length=len(formatted_response)
        )
        
        # Calculate total saga duration
        total_duration = 0
        for entry in final_message.call_stack:
            if entry.duration_ms:
                total_duration += entry.duration_ms
        
        print(f"[SAGA STEP 5] 🎉 SAGA COMPLETED SUCCESSFULLY!")
        print(f"[SAGA STEP 5] Total duration: {total_duration:.2f}ms")
        
        # Store final result in result store
        result_dict = {
            "success": True,
            "saga_id": message.saga_id,
            "question": message.question,
            "generated_sql": message.generated_sql,
            "raw_results": message.raw_results,
            "formatted_response": formatted_response,
            "call_stack": [entry.to_dict() for entry in final_message.call_stack],
            "total_duration_ms": total_duration,
            "user_id": message.user_id,
            "account_id": message.account_id
        }
        
        saga_store.store_result(message.saga_id, result_dict)
        
        # Acknowledge message
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 5] ✗ Error: {str(e)}")
        
        # Create error message
        try:
            data = json.loads(body)
            message = message_from_dict(data, QueryExecutedMessage)
            
            error_message = SagaErrorMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                error_step="format_result",
                error_message=str(e),
                error_details={"duration_ms": duration_ms}
            )
            
            error_message.call_stack = message.call_stack.copy()
            error_message.add_to_call_stack(
                step_name="format_result",
                status="error",
                duration_ms=duration_ms,
                error=str(e)
            )
            
            # Store error result
            error_dict = {
                "success": False,
                "saga_id": message.saga_id,
                "error_step": "format_result",
                "error_message": str(e),
                "call_stack": [entry.to_dict() for entry in error_message.call_stack],
                "user_id": message.user_id,
                "account_id": message.account_id
            }
            
            saga_store.store_result(message.saga_id, error_dict)
            
            # Publish error
            publisher = SagaPublisher()
            publisher.publish_error(error_message)
        except:
            pass
        
        # Negative acknowledgment
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_result_formatter_consumer(host: str = None):
    """Start the result formatter consumer"""
    from core.saga.publisher import SagaPublisher
    
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
        queue_name = SagaPublisher.QUEUE_FORMAT_RESULT
        channel.queue_declare(queue=queue_name, durable=True)
        
        # Set QoS
        channel.basic_qos(prefetch_count=1)
        
        # Start consuming
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=process_result_formatting
        )
        
        print(f"\n[SAGA STEP 5] Result Formatter Consumer Started")
        print(f"[SAGA STEP 5] Waiting for messages on '{queue_name}'...")
        
        channel.start_consuming()
        
    except KeyboardInterrupt:
        print("\n[SAGA STEP 5] Shutting down...")
        channel.stop_consuming()
        connection.close()
    except Exception as e:
        print(f"[SAGA STEP 5] Failed to start consumer: {e}")

