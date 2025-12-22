"""
Saga Step 5: Format Result

Formats the query result using Gemini LLM and stores final result.
This is the final step in the saga.
"""

import asyncio
import json
import time
from typing import Dict, Any, List
from agentic_sql.saga.messages import (
    QueryExecutedMessage, ResultFormattedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from agentic_sql.saga.state_store import get_saga_state_store
from core.gemini_client import GeminiClient
from core.mcp.client import DatabaseMCPClient, ChromaMCPClient



def run_result_formatting_agentic(message: QueryExecutedMessage) -> tuple[str, str, Dict[str, Any]]:
    """Use Gemini with tools to format results and provide professional insights"""
    chroma_client = ChromaMCPClient()
    
    tools = [
        chroma_client.get_gemini_tool("search_relevant_schema", message=message),
        chroma_client.get_gemini_tool("search_business_knowledge", message=message)
    ]
    agent = GeminiClient(tools=tools)
    
    prompt = f"""
    You are a Senior Business Intelligence Consultant. Your goal is to transform technical database results into a professional executive summary.
    
    USER QUESTION: "{message.question}"
    
    SQL LOGIC USED:
    {message.generated_sql}
    
    RAW DATABASE RESULTS:
    {message.raw_results}
    
    INSTRUCTIONS:
    1. If you need more business context or schema details to explain the results better, use the search tools.
    2. Format the response for an executive: focus on insights, trends, and business impact.
    3. Start with the "Bottom Line" or most important finding.
    4. Use professional domain-specific terminology.
    5. Avoid technical jargon like "SQL", "JOINs", or column names unless necessary for clarity.
    
    REPLY WITH:
    EXECUTIVE SUMMARY: [Your professional response]
    """
    
    try:
        chat = agent.model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(prompt)
        text = response.text
        
        formatted_response = ""
        if "EXECUTIVE SUMMARY:" in text:
            formatted_response = text.split("EXECUTIVE SUMMARY:")[1].strip()
        else:
            formatted_response = text.strip()
            
        usage = {}
        if hasattr(response, "usage_metadata"):
            usage = {
                "prompt_token_count": response.usage_metadata.prompt_token_count,
                "candidates_token_count": response.usage_metadata.candidates_token_count,
                "total_token_count": response.usage_metadata.total_token_count
            }
            
        interaction_history = []
        try:
            from agentic_sql.saga.consumers.query_generator_consumer import sanitize_for_json
            for msg in chat.history:
                role = msg.role
                parts = []
                for part in msg.parts:
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
            interaction_history = sanitize_for_json(interaction_history)
        except Exception as e:
            print(f"[SAGA STEP 5] Warning: Failed to capture interaction history: {e}")
            interaction_history = []
            
        return formatted_response, text, usage, prompt, interaction_history
    except Exception as e:
        print(f"[SAGA STEP 5] Agentic formatting failed: {e}")
        return f"Here are the findings from your data:\n\n{message.raw_results}", str(e), {}, prompt, []

from core.infra.consumer import BaseConsumer

class ResultFormatterConsumer(BaseConsumer):
    def __init__(self, host: str = None):
        super().__init__(queue_name=SagaPublisher.QUEUE_FORMAT_RESULT, host=host)

    def process_message(self, ch, method, properties, body):
        process_result_formatting(ch, method, properties, body)

def process_result_formatting(ch, method, properties, body):
    """Process result formatting step - FINAL STEP"""
    start_time = time.time()
    saga_store = get_saga_state_store()
    
    try:
        # Parse message
        data = json.loads(body)
        message = message_from_dict(data, QueryExecutedMessage)
        
        print(f"\n[SAGA STEP 5] Result Formatting (Agentic) - Saga ID: {message.saga_id}")
        
        # Agentic formatting
        formatted_response, reasoning, llm_usage, llm_prompt, interaction_history = run_result_formatting_agentic(message)
        
        duration_ms = (time.time() - start_time) * 1000
        
        print(f"[SAGA STEP 5] Step Token Usage: {llm_usage}")
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
        
        final_message.call_stack = message.call_stack.copy()
        final_message.add_to_call_stack(
            step_name="format_result_agentic",
            status="success",
            duration_ms=duration_ms,
            response_length=len(formatted_response),
            reasoning=reasoning,
            prompt=llm_prompt,
            usage=llm_usage,
            interaction_history=interaction_history
        )
        
        # Calculate total saga duration and tokens
        total_duration = 0
        total_tokens = 0
        for entry in final_message.call_stack:
            if entry.duration_ms:
                total_duration += entry.duration_ms
            if entry.metadata and "usage" in entry.metadata:
                total_tokens += entry.metadata["usage"].get("total_token_count", 0)
            elif entry.metadata and "total_token_count" in entry.metadata: # Legacy format check
                total_tokens += entry.metadata["total_token_count"]
        
        print(f"[SAGA STEP 5] 🎉 SAGA COMPLETED SUCCESSFULLY!")
        print(f"[SAGA STEP 5] Total duration: {total_duration:.2f}ms")
        print(f"[SAGA STEP 5] Total tokens used: {total_tokens}")
        
        result_dict = {
            "success": True,
            "saga_id": message.saga_id,
            "question": message.question,
            "generated_sql": message.generated_sql,
            "raw_results": message.raw_results,
            "formatted_response": formatted_response,
            "call_stack": [entry.to_dict() for entry in final_message.call_stack],
            "total_duration_ms": total_duration,
            "total_tokens": total_tokens,
            "user_id": message.user_id,
            "account_id": message.account_id
        }
        
        saga_store.store_result(message.saga_id, result_dict)
        
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 5] ✗ Error: {str(e)}")
        
        try:
            from agentic_sql.saga.messages import SagaErrorMessage
            error_message = SagaErrorMessage(
                saga_id=message.saga_id,
                user_id=message.user_id,
                account_id=message.account_id,
                question=message.question,
                error_step="format_result_agentic",
                error_message=str(e),
                error_details={"duration_ms": duration_ms}
            )
            
            message.add_to_call_stack(
                step_name="format_result_agentic",
                status="error",
                duration_ms=duration_ms,
                error=str(e)
            )
            
            error_dict = {
                "success": False,
                "saga_id": message.saga_id,
                "error_step": "format_result_agentic",
                "error_message": str(e),
                "formatted_response": "As your Senior Business Intelligence Consultant, I successfully retrieved the data but encountered an issue while generating the final executive summary.",
                "call_stack": [entry.to_dict() for entry in message.call_stack],
                "user_id": message.user_id,
                "account_id": message.account_id,
                "status": "error"
            }
            saga_store.store_result(message.saga_id, error_dict, status="error")
            
            SagaPublisher().publish_error(error_message)
        except Exception:
            pass
        
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_result_formatter_consumer(host: str = None):
    """Start the result formatter consumer"""
    consumer = ResultFormatterConsumer(host=host)
    consumer.start_consuming()

