"""
Centralized Prometheus metrics for saga consumers.
This module should be imported by all consumers to avoid duplicate metric registration.
"""
import socket
from prometheus_client import Counter, Histogram

INSTANCE_ID = socket.gethostname()

# Consumer Metrics
SAGA_CONSUMER_MESSAGES = Counter(
    'saga_consumer_messages_total',
    'Total messages processed by saga consumers',
    ['consumer', 'status', 'instance']
)
SAGA_CONSUMER_DURATION = Histogram(
    'saga_consumer_duration_seconds',
    'Consumer processing time',
    ['consumer'],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]
)

# LLM Metrics
LLM_TOKENS = Counter(
    'llm_tokens_total',
    'Total tokens used by LLM',
    ['consumer', 'type']
)
LLM_TOOL_CALLS = Counter(
    'llm_tool_calls_total',
    'Tool calls made per LLM request',
    ['consumer']
)
LLM_REQUESTS = Counter(
    'llm_requests_total',
    'Total LLM API requests',
    ['consumer', 'model']
)
