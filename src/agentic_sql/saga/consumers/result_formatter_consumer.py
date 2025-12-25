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
from agentic_sql.saga.utils import sanitize_for_json, update_saga_state, store_saga_error, get_interaction_history



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
        chat = agent.start_chat(enable_automatic_function_calling=True)
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
            
        interaction_history = get_interaction_history(chat)
            
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
        
        print(f"\n[SAGA STEP 3] Result Formatting (Agentic) - Saga ID: {message.saga_id}")
        
        # Agentic formatting
        formatted_response, reasoning, llm_usage, llm_prompt, interaction_history = run_result_formatting_agentic(message)
        
        duration_ms = (time.time() - start_time) * 1000
        
        print(f"[SAGA STEP 3] Step Token Usage: {llm_usage}")
        print(f"[SAGA STEP 3] ✓ Results formatted successfully in {duration_ms:.2f}ms")
        
        # Create final result message
        final_message = ResultFormattedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            generated_sql=message.generated_sql,
            raw_results=message.raw_results,
            reasoning=reasoning,
            formatted_response=formatted_response,
            success=True,
            error=None
        )
        
        final_message.call_stack = message.call_stack.copy()
        final_message._current_tool_calls = message._current_tool_calls.copy()
        message._current_tool_calls = []
        
        final_message.add_to_call_stack(
            step_name="format_result_agentic",
            status="success",
            duration_ms=duration_ms,
            response_length=len(formatted_response),
            reasoning=reasoning,
            prompt=llm_prompt,
            response=formatted_response,
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
        
        print(f"[SAGA STEP 3] 🎉 SAGA COMPLETED SUCCESSFULLY!")
        print(f"[SAGA STEP 3] Total duration: {total_duration:.2f}ms")
        print(f"[SAGA STEP 3] Total tokens used: {total_tokens}")
        
        result_dict = {
            "success": True,
            "saga_id": message.saga_id,
            "question": message.question,
            "generated_sql": message.generated_sql,
            "raw_results": message.raw_results,
            "reasoning": reasoning,
            "formatted_response": formatted_response,
            "call_stack": [entry.to_dict() for entry in final_message.call_stack],
            "total_duration_ms": total_duration,
            "total_tokens": total_tokens,
            "user_id": message.user_id,
            "account_id": message.account_id
        }
        
        update_saga_state(message.saga_id, result_dict, status="completed")
        
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 3] ✗ Error: {str(e)}")
        
        store_saga_error(
            message=message,
            error_step="format_result_agentic",
            error_msg=str(e),
            duration_ms=duration_ms
        )
        
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_result_formatter_consumer(host: str = None):
    """Start the result formatter consumer"""
    consumer = ResultFormatterConsumer(host=host)
    consumer.start_consuming()

