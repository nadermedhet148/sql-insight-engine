"""
Saga Message Schemas for Query Processing

Each step in the saga publishes a message to the next step.
Messages include call_stack to track the processing flow.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
import json


@dataclass
class CallStackEntry:
    step_name: str
    timestamp: str
    duration_ms: Optional[float] = None
    status: str = "success"  # success, error, pending
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "step_name": self.step_name,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "metadata": self.metadata
        }


@dataclass
class SagaBaseMessage:
    saga_id: str  # UUID for tracking the entire saga
    user_id: int
    account_id: str
    question: str
    call_stack: List[CallStackEntry] = field(default_factory=list)
    _current_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    all_tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    def add_tool_call(self, tool: str, args: Dict[str, Any], response: Any, duration_ms: float = 0, status: str = "success"):
        """Track an MCP tool call to be included in the next call stack entry and persisted"""
        from agentic_sql.saga.utils import sanitize_for_json
        call_data = {
            "tool": tool,
            "args": sanitize_for_json(args),
            "response": sanitize_for_json(response),
            "duration_ms": duration_ms,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
        self._current_tool_calls.append(call_data)
        self.all_tool_calls.append(call_data)

    def add_to_call_stack(self, step_name: str, status: str = "success", 
                          duration_ms: Optional[float] = None, **metadata):
        from agentic_sql.saga.utils import sanitize_for_json
        
        # Auto-include any tracked tool calls if not explicitly provided
        if self._current_tool_calls and "tools_used" not in metadata:
            metadata["tools_used"] = self._current_tool_calls.copy()
            self._current_tool_calls = []

        # Sanitize all metadata before storing
        sanitized_metadata = sanitize_for_json(metadata)

        entry = CallStackEntry(
            step_name=step_name,
            timestamp=datetime.utcnow().isoformat(),
            duration_ms=duration_ms,
            status=status,
            metadata=sanitized_metadata
        )
        self.call_stack.append(entry)
    
    def to_dict(self) -> dict:
        return {
            "saga_id": self.saga_id,
            "user_id": self.user_id,
            "account_id": self.account_id,
            "question": self.question,
            "call_stack": [entry.to_dict() for entry in self.call_stack],
            "all_tool_calls": self.all_tool_calls
        }


@dataclass
class QueryInitiatedMessage(SagaBaseMessage):
    db_config: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["db_config"] = self.db_config
        return data


@dataclass
class TablesCheckedMessage(SagaBaseMessage):
    schema_context: List[str] = field(default_factory=list)
    available_tables: List[str] = field(default_factory=list)
    table_schemas: Dict[str, Any] = field(default_factory=dict)
    business_context: List[str] = field(default_factory=list)
    business_documents_count: int = 0
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["schema_context"] = self.schema_context
        data["available_tables"] = self.available_tables
        data["table_schemas"] = self.table_schemas
        data["business_context"] = self.business_context
        data["business_documents_count"] = self.business_documents_count
        return data


@dataclass
class QueryGeneratedMessage(SagaBaseMessage):
    schema_context: List[str] = field(default_factory=list)
    generated_sql: str = ""
    reasoning: str = ""
    db_config: dict = field(default_factory=dict)
    business_context: List[str] = field(default_factory=list)
    business_documents_count: int = 0
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["schema_context"] = self.schema_context
        data["generated_sql"] = self.generated_sql
        data["reasoning"] = self.reasoning
        data["db_config"] = self.db_config
        data["business_context"] = self.business_context
        data["business_documents_count"] = self.business_documents_count
        return data


@dataclass
class QueryExecutedMessage(SagaBaseMessage):
    generated_sql: str = ""
    raw_results: str = ""
    reasoning: str = ""
    execution_success: bool = True
    execution_error: Optional[str] = None
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["generated_sql"] = self.generated_sql
        data["raw_results"] = self.raw_results
        data["reasoning"] = self.reasoning
        data["execution_success"] = self.execution_success
        data["execution_error"] = self.execution_error
        return data


@dataclass
class ResultFormattedMessage(SagaBaseMessage):
    generated_sql: str = ""
    raw_results: str = ""
    reasoning: str = ""
    formatted_response: str = ""
    success: bool = True
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["generated_sql"] = self.generated_sql
        data["raw_results"] = self.raw_results
        data["reasoning"] = self.reasoning
        data["formatted_response"] = self.formatted_response
        data["success"] = self.success
        data["error"] = self.error
        return data


@dataclass
class SagaErrorMessage(SagaBaseMessage):
    error_step: str = ""
    error_message: str = ""
    error_details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        data = super().to_dict()
        data["error_step"] = self.error_step
        data["error_message"] = self.error_message
        data["error_details"] = self.error_details
        return data


def message_to_json(message: SagaBaseMessage) -> str:
    from agentic_sql.saga.utils import sanitize_for_json
    return json.dumps(sanitize_for_json(message.to_dict()))


def message_from_dict(data: dict, message_class) -> SagaBaseMessage:
    # Reconstruct call stack
    call_stack = []
    for entry_dict in data.get("call_stack", []):
        entry = CallStackEntry(
            step_name=entry_dict["step_name"],
            timestamp=entry_dict["timestamp"],
            duration_ms=entry_dict.get("duration_ms"),
            status=entry_dict.get("status", "success"),
            metadata=entry_dict.get("metadata", {})
        )
        call_stack.append(entry)
    
    # Remove call_stack from data for class initialization
    data_copy = data.copy()
    data_copy.pop("call_stack", None)
    
    # Create message instance
    message = message_class(**data_copy)
    message.call_stack = call_stack
    message.all_tool_calls = data.get("all_tool_calls", [])
    
    return message
