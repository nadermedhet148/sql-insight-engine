import asyncio
import pika
import json
import time
import socket
from typing import List, Dict, Any
from agentic_sql.saga.messages import (
    QueryInitiatedMessage, QueryGeneratedMessage,
    SagaErrorMessage, message_from_dict
)
from agentic_sql.saga.publisher import SagaPublisher
from core.gemini_client import GeminiClient
from core.mcp.client import initialize_mcp, get_discovered_tools
from account.models import User
from agentic_sql.saga.utils import (
    sanitize_for_json, update_saga_state, store_saga_error,
    get_interaction_history, parse_llm_response, extract_response_metadata
)
from agentic_sql.saga.consumers.metrics import (
    INSTANCE_ID, SAGA_CONSUMER_MESSAGES, SAGA_CONSUMER_DURATION,
    LLM_TOKENS, LLM_TOOL_CALLS, LLM_REQUESTS
)
from core.langfuse_client import get_langfuse

def extract_tables_from_sql(sql: str) -> List[str]:
    import re
    pattern = r'(?:FROM|JOIN)\s+([a-zA-Z0-9_".]+)'
    matches = re.findall(pattern, sql, re.IGNORECASE)

    tables = []
    for match in matches:
        # Remove quotes and get the table name (last part of schema.table)
        table = match.strip().strip('"').strip('`').split('.')[-1].strip('"').strip('`')
        if table:
            tables.append(table.lower())
    return list(set(tables))

def run_agentic_sql_generation(message: QueryInitiatedMessage, db_config_dict: Dict[str, Any]) -> tuple[str, str, str, Dict, List, bool]:
    from core.services.schema_graph_retriever import retrieve_relevant_tables

    # Pre-fetch relevant schema via Graph-RAG (ChromaDB vector search + Neo4j FK expansion)
    print(f"[SAGA STEP 1] Retrieving schema via Graph-RAG for saga {message.saga_id}")
    schema_context = retrieve_relevant_tables(
        question=message.question,
        account_id=str(message.account_id),
        top_k=3,
    )

    db_url = f"postgresql://{db_config_dict['username']}:{db_config_dict['password']}@{db_config_dict['host']}:{db_config_dict['port'] or 5432}/{db_config_dict['db_name']}"

    # Give the LLM: business knowledge search + db tools as fallback (no search_relevant_schema)
    all_tools = get_discovered_tools(message=message, context={"db_url": db_url, "account_id": message.account_id})
    tools = [
        t for t in all_tools
        if t.__name__ in ("search_relevant_knowledgebase", "list_tables", "describe_table")
    ]

    agent = GeminiClient(tools=tools)

    schema_section = schema_context if schema_context else "Schema retrieval returned no results."

    prompt = f"""You are a Senior SQL Analyst and Gatekeeper. Your goal is to write a PostgreSQL query for: "{message.question}"

DATABASE CONNECTION:
db_url: postgresql://{db_config_dict['username']}:{db_config_dict['password']}@{db_config_dict['host']}:{db_config_dict['port'] or 5432}/{db_config_dict['db_name']}

PRE-RETRIEVED SCHEMA (use this first — it was selected for relevance to your question):
{schema_section}

RULES:
1. Prefer the pre-retrieved schema above. It already contains the most relevant tables.
2. If a table or column you need is missing from the schema above, use list_tables and describe_table to look it up.
3. Use search_relevant_knowledgebase to look up business rules or domain definitions when needed (e.g. "churn", "active user").
4. If the question cannot be answered from the available schema, respond with DECISION: OUT_OF_SCOPE.

RESPONSE FORMAT (STRICT):
DECISION: [RELEVANT / OUT_OF_SCOPE]
REASONING: [Your explanation]
SQL: [The final raw PostgreSQL query (no markdown code blocks) if RELEVANT, otherwise NONE]
"""

    # Create Langfuse trace and generation
    lf = get_langfuse()
    generation = None
    if lf:
        trace = lf.trace(
            id=str(message.saga_id),
            name="sql-query-saga",
            user_id=str(message.user_id),
            input={"question": message.question},
            metadata={"account_id": str(message.account_id)},
        )
        generation = trace.generation(
            name="sql-generation",
            model="gemini-2.0-flash",
            input=[{"role": "user", "content": prompt}],
        )

    print(f"[TRACE] Starting Gemini chat for saga {message.saga_id}")
    chat = agent.start_chat(enable_automatic_function_calling=True)
    print(f"[TRACE] Sending message to Gemini for saga {message.saga_id}")
    response = chat.send_message(prompt)
    print(f"[TRACE] Received response from Gemini for saga {message.saga_id}")
    try:
        full_text = response.text or ""
    except (ValueError, AttributeError):
        full_text = str(response)

    interaction_history = get_interaction_history(chat)
    parsed = parse_llm_response(full_text, tags=["DECISION", "REASONING", "SQL"])
    print(f"[TRACE] Parsed generator response for {message.saga_id}: {parsed}")

    decision = str(parsed.get("DECISION", "")).upper()
    reasoning = parsed.get("REASONING", "N/A")
    sql = parsed.get("SQL", "")

    # 1. Primary check: Explicitly tagged decision
    is_out_of_scope = "OUT_OF_SCOPE" in decision or "IRRELEVANT" in decision

    # 2. Secondary check: If SQL is NONE or empty, and it's not RELEVANT, treat as out of scope
    if not is_out_of_scope and (not sql or sql.upper() == "NONE"):
        # Most likely out of scope if no SQL was generated
        is_out_of_scope = True
        if reasoning == "N/A":
             # Use the whole text as reasoning if we haven't found any
             reasoning = full_text.strip()

    # 3. Text keywords fallback (in case tags failed completely)
    out_of_scope_keywords = [
        "out of your business scope", "out of you bussiness scope",
        "not related to the", "cannot answer", "missing data",
        "not related to any available tables", "out of scope",
        "does not exist", "unable to find the table"
    ]
    if not is_out_of_scope and any(kw in full_text.lower() for kw in out_of_scope_keywords):
        # We only force out_of_scope if no SQL was found or if it clearly says it can't do it
        if not sql or sql.upper() == "NONE" or "cannot answer" in full_text.lower():
            is_out_of_scope = True
            if reasoning == "N/A": reasoning = full_text.strip()

    usage = extract_response_metadata(response)

    if generation:
        generation.end(
            output=full_text,
            usage={
                "input": usage.get("prompt_token_count", 0),
                "output": usage.get("candidates_token_count", 0),
            },
        )

    return sql, reasoning, prompt, usage, interaction_history, is_out_of_scope


from core.infra.consumer import BaseConsumer

class QueryGeneratorConsumer(BaseConsumer):
    def __init__(self, host: str = None):
        super().__init__(queue_name=SagaPublisher.QUEUE_GENERATE_QUERY, host=host, prefetch_count=10)

    def process_message(self, ch, method, properties, body):
        process_query_generation(ch, method, properties, body)

def process_query_generation(ch, method, properties, body):
    start_time = time.time()

    try:
        data = json.loads(body)
        # Note: Now receiving QueryInitiatedMessage instead of TablesCheckedMessage
        message = message_from_dict(data, QueryInitiatedMessage)

        print(f"\n[SAGA STEP 1] Merged Agentic Query Check & Generation - Saga ID: {message.saga_id}")

        # Get DB config
        db_config_dict = {}
        from core.database.session import get_db
        from account.models import User
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

        generated_sql, llm_reasoning, llm_prompt, llm_usage, interaction_history, is_out_of_scope = run_agentic_sql_generation(message, db_config_dict)

        # Push in_scope evaluation score
        lf = get_langfuse()
        if lf:
            trace = lf.trace(id=str(message.saga_id))
            trace.score(
                name="in_scope",
                value=0 if is_out_of_scope else 1,
                comment=llm_reasoning[:200] if llm_reasoning else None,
            )

        # Record LLM metrics
        LLM_REQUESTS.labels(consumer='query_generator', model='gemini').inc()
        if llm_usage:
            LLM_TOKENS.labels(consumer='query_generator', type='input').inc(llm_usage.get('prompt_token_count', 0))
            LLM_TOKENS.labels(consumer='query_generator', type='output').inc(llm_usage.get('candidates_token_count', 0))
            tool_count = llm_usage.get('tool_calls', 0)
            if tool_count:
                LLM_TOOL_CALLS.labels(consumer='query_generator').inc(tool_count)

        if is_out_of_scope:
            duration_ms = (time.time() - start_time) * 1000
            duration_sec = duration_ms / 1000
            print(f"[SAGA STEP 1] 🛑 Question is OUT OF SCOPE: {llm_reasoning[:100]}...")

            # Record metrics
            SAGA_CONSUMER_MESSAGES.labels(consumer='query_generator', status='out_of_scope', instance=INSTANCE_ID).inc()
            SAGA_CONSUMER_DURATION.labels(consumer='query_generator').observe(duration_sec)

            store_saga_error(
                message=message,
                error_step="generate_query_agentic",
                error_msg=llm_reasoning,
                duration_ms=duration_ms,
                formatted_response=f"As your Senior Business Intelligence Consultant, I've determined that this inquiry falls outside our current business focus and database scope. {llm_reasoning}",
                is_out_of_scope=True
            )

            # Acknowledge and stop saga
            ch.basic_ack(delivery_tag=method.delivery_tag)
            return

        duration_ms = (time.time() - start_time) * 1000
        duration_sec = duration_ms / 1000

        next_message = QueryGeneratedMessage(
            saga_id=message.saga_id,
            user_id=message.user_id,
            account_id=message.account_id,
            question=message.question,
            generated_sql=generated_sql,
            reasoning=llm_reasoning,
            db_config=db_config_dict,
            business_context=getattr(message, "business_context", []),
            business_documents_count=getattr(message, "business_documents_count", 0)
        )

        next_message.call_stack = message.call_stack.copy()
        next_message.all_tool_calls = message.all_tool_calls.copy()
        next_message._current_tool_calls = message._current_tool_calls.copy()
        message._current_tool_calls = []

        next_message.add_to_call_stack(
            step_name="generate_query_agentic",
            status="success",
            duration_ms=duration_ms,
            reasoning=llm_reasoning,
            prompt=llm_prompt,
            response=llm_reasoning,
            usage=llm_usage,
            tools_used=sanitize_for_json(next_message._current_tool_calls.copy()),
            interaction_history=interaction_history
        )

        print(f"[SAGA STEP 1] Reasoning: {llm_reasoning[:200]}...")
        print(f"[SAGA STEP 1] Token Usage: {llm_usage}")
        print(f"[SAGA STEP 1] ✓ SQL generated in {duration_ms:.2f}ms")

        # Record success metrics
        SAGA_CONSUMER_MESSAGES.labels(consumer='query_generator', status='success', instance=INSTANCE_ID).inc()
        SAGA_CONSUMER_DURATION.labels(consumer='query_generator').observe(duration_sec)

        publisher = SagaPublisher()
        publisher.publish_query_execution(next_message)

        update_saga_state(message.saga_id, next_message.to_dict())

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        duration_sec = duration_ms / 1000
        print(f"[SAGA STEP 1] ✗ Agentic Error: {str(e)}")

        # Record error metrics
        SAGA_CONSUMER_MESSAGES.labels(consumer='query_generator', status='error', instance=INSTANCE_ID).inc()
        SAGA_CONSUMER_DURATION.labels(consumer='query_generator').observe(duration_sec)

        store_saga_error(
            message=message,
            error_step="generate_query_agentic",
            error_msg=str(e),
            duration_ms=duration_ms
        )

        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def start_query_generator_consumer(host: str = None):
    consumer = QueryGeneratorConsumer(host=host)
    consumer.start_consuming()
