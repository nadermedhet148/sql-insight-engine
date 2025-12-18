"""
Saga Step 3: Generate SQL Query

Generates SQL query using Gemini LLM based on context.
"""

import pika
import json
import time
from typing import List
from core.saga.messages import (
    TablesCheckedMessage, QueryGeneratedMessage,
    SagaErrorMessage, message_from_dict
)
from core.saga.publisher import SagaPublisher
from core.gemini_client import GeminiClient
from account.models import User
from core.database.session import get_db

# Initialize client
gemini_client = GeminiClient()

def generate_sql_query_logic(question: str, schema_context: List[str]) -> tuple[str, str]:
    """Logic to generate SQL query using LLM. Returns (sql, reasoning)"""
    try:
        # Build context string
        if schema_context:
            context_str = "\n\n".join(schema_context)
        else:
            context_str = "No specific schema information available."
        
        # Create prompt for SQL generation
        prompt = f"""You are an expert SQL query generator. Your task is to generate a valid SQL query based on a natural language question and database schema information.

                    Database Schema Information:
                    {context_str}

                    Natural Language Question: "{question}"

                    Instructions:
                    1. First, explain your reasoning for why this query structure is correct.
                    2. Then, provide the final valid PostgreSQL SELECT query.
                    
                    Use only the tables and columns mentioned in the schema.
                    Include appropriate JOINs if multiple tables are needed.
                    Add ORDER BY and LIMIT clauses when appropriate.
                    
                    Format your response exactly like this:
                    REASONING: [Your reasoning here]
                    SQL: [The SQL query here]
                    """
        
        full_response = gemini_client.generate_content(prompt)
        
        # Parse reasoning and SQL
        reasoning = ""
        sql_query = ""
        
        if "REASONING:" in full_response and "SQL:" in full_response:
            parts = full_response.split("SQL:")
            reasoning = parts[0].replace("REASONING:", "").strip()
            sql_query = parts[1].strip()
        else:
            # Fallback if format is not perfectly followed
            sql_query = full_response.strip()
            reasoning = "LLM generated query based on provided schema context."
        
        # Clean up the SQL query
        clean_query = sql_query.strip()
        if clean_query.startswith("```sql"):
            clean_query = clean_query[6:]
        if clean_query.startswith("```"):
            clean_query = clean_query[3:]
        if clean_query.endswith("```"):
            clean_query = clean_query[:-3]
        clean_query = clean_query.strip()
        if clean_query.endswith(";"):
            clean_query = clean_query[:-1].strip()
        
        return clean_query, reasoning
        
    except Exception as e:
        print(f"[SAGA STEP 3] Error generating SQL: {e}")
        raise Exception(f"Failed to generate SQL query: {str(e)}")


def process_query_generation(ch, method, properties, body):
    """Process query generation step"""
    start_time = time.time()
    
    try:
        # Parse message
        data = json.loads(body)
        message = message_from_dict(data, TablesCheckedMessage)
        
        print(f"\n[SAGA STEP 3] Query Generation - Saga ID: {message.saga_id}")
        
        # Logic moved from QueryService
        generated_sql, llm_reasoning = generate_sql_query_logic(message.question, message.schema_context)
        
        if not generated_sql:
            raise Exception("Failed to generate SQL query")
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Get user's DB config for next step
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
        
        # Create next message
        next_message = QueryGeneratedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            schema_context=message.schema_context,
            generated_sql=generated_sql,
            db_config=db_config_dict
        )
        
        # Copy call stack
        next_message.call_stack = message.call_stack.copy()
        
        # Add this step to call stack
        next_message.add_to_call_stack(
            step_name="generate_query",
            status="success",
            duration_ms=duration_ms,
            sql_length=len(generated_sql),
            llm_reasoning=llm_reasoning
        )
        
        print(f"[SAGA STEP 3] ✓ SQL generated in {duration_ms:.2f}ms")
        
        # Publish to next step
        publisher = SagaPublisher()
        publisher.publish_query_execution(next_message)
        
        # Update progress in store
        from core.saga.state_store import get_saga_state_store
        saga_store = get_saga_state_store()
        saga_store.update_result(message.saga_id, {
            "call_stack": [entry.to_dict() for entry in next_message.call_stack],
            "generated_sql": generated_sql
        })
        
        # Acknowledge message
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 3] ✗ Error: {str(e)}")
        
        # Create error message
        try:
            data = json.loads(body)
            message = message_from_dict(data, TablesCheckedMessage)
            
            error_message = SagaErrorMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                error_step="generate_query",
                error_message=str(e),
                error_details={"duration_ms": duration_ms}
            )
            
            error_message.call_stack = message.call_stack.copy()
            error_message.add_to_call_stack(
                step_name="generate_query",
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


def start_query_generator_consumer(host: str = None):
    """Start the query generator consumer"""
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
        queue_name = SagaPublisher.QUEUE_GENERATE_QUERY
        channel.queue_declare(queue=queue_name, durable=True)
        
        # Set QoS
        channel.basic_qos(prefetch_count=1)
        
        # Start consuming
        channel.basic_consume(
            queue=queue_name,
            on_message_callback=process_query_generation
        )
        
        print(f"\n[SAGA STEP 3] Query Generator Consumer Started")
        print(f"[SAGA STEP 3] Waiting for messages on '{queue_name}'...")
        
        channel.start_consuming()
        
    except KeyboardInterrupt:
        print("\n[SAGA STEP 3] Shutting down...")
        channel.stop_consuming()
        connection.close()
    except Exception as e:
        print(f"[SAGA STEP 3] Failed to start consumer: {e}")

