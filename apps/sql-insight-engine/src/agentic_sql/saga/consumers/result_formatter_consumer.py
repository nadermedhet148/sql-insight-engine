"""
Saga Step 5: Format Result

Formats the query result using Gemini LLM and stores final result.
This is the final step in the saga.
"""

import asyncio
import json
import time
import socket
from typing import Dict, Any, List
from agentic_sql.saga.messages import (
    QueryExecutedMessage, ResultFormattedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from agentic_sql.saga.state_store import get_saga_state_store
from core.gemini_client import GeminiClient
from core.mcp.client import get_discovered_tools
from agentic_sql.saga.utils import (
    sanitize_for_json, update_saga_state, store_saga_error, 
    get_interaction_history, parse_llm_response, extract_response_metadata
)
from agentic_sql.saga.consumers.metrics import (
    INSTANCE_ID, SAGA_CONSUMER_MESSAGES, SAGA_CONSUMER_DURATION,
    LLM_TOKENS, LLM_REQUESTS
)



def run_result_formatting_agentic(message: QueryExecutedMessage) -> tuple[str, str, Dict[str, Any]]:
    """Use Gemini with tools to format results and provide professional insights"""
    all_tools = get_discovered_tools(message=message, context={"account_id": message.account_id})
    # Formatter should NOT have run_query
    tools = [t for t in all_tools if t.__name__ != "run_query"]
    agent = GeminiClient(tools=tools)
    
    prompt = f"""
    You are a Senior Business Intelligence Consultant. Your goal is to transform technical database results into a professional executive summary.
    
    USER QUESTION: "{message.question}"
    
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
        try:
            text = response.text or ""
        except (ValueError, AttributeError):
            text = str(response)
        
        interaction_history = get_interaction_history(chat)
        parsed = parse_llm_response(text, tags=["EXECUTIVE SUMMARY"])

        formatted_response = parsed.get("EXECUTIVE SUMMARY", text.strip())
        usage = extract_response_metadata(response)
            
        return formatted_response, text, usage, prompt, interaction_history
    except Exception as e:
        print(f"[SAGA STEP 5] Agentic formatting failed: {e}")
        return f"Here are the findings from your data:\n\n{message.raw_results}", str(e), {}, prompt, []

from core.infra.consumer import BaseConsumer

class ResultFormatterConsumer(BaseConsumer):
    def __init__(self, host: str = None):
        super().__init__(queue_name=SagaPublisher.QUEUE_FORMAT_RESULT, host=host, prefetch_count=10)

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
        
        # Record LLM metrics
        LLM_REQUESTS.labels(consumer='result_formatter', model='gemini').inc()
        if llm_usage:
            LLM_TOKENS.labels(consumer='result_formatter', type='input').inc(llm_usage.get('prompt_token_count', 0))
            LLM_TOKENS.labels(consumer='result_formatter', type='output').inc(llm_usage.get('candidates_token_count', 0))
        
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
        final_message.all_tool_calls = message.all_tool_calls.copy()
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
            tools_used=sanitize_for_json(final_message._current_tool_calls.copy()),
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
        
        result_dict = final_message.to_dict()
        result_dict.update({
            "success": True,
            "total_duration_ms": total_duration,
            "total_tokens": total_tokens
        })
        
        update_saga_state(message.saga_id, result_dict, status="completed")
        
        # Record success metrics
        SAGA_CONSUMER_MESSAGES.labels(consumer='result_formatter', status='success', instance=INSTANCE_ID).inc()
        SAGA_CONSUMER_DURATION.labels(consumer='result_formatter').observe(duration_ms / 1000)
        
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        print(f"[SAGA STEP 3] ✗ Error: {str(e)}")
        
        # Record error metrics
        SAGA_CONSUMER_MESSAGES.labels(consumer='result_formatter', status='error', instance=INSTANCE_ID).inc()
        SAGA_CONSUMER_DURATION.labels(consumer='result_formatter').observe(duration_ms / 1000)
        
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

