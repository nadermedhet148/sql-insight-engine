
import json
import redis
import os
from typing import Dict, Optional
from datetime import datetime, timedelta

class SagaStateStore:
    
    def __init__(self, host: str = None, port: int = 6379, db: int = 0):
        host = host or os.getenv("REDIS_HOST", "localhost")
        self._redis = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self._ttl_seconds = 3600  # 1 hour TTL
    
    def store_result(self, saga_id: str, result: dict, status: Optional[str] = None):
        data = {
            "result": result,
            "timestamp": datetime.utcnow().isoformat(),
            "status": status if status else ("completed" if result.get("success", False) else "error")
        }
        self._redis.setex(f"saga:{saga_id}", self._ttl_seconds, json.dumps(data))
        print(f"[STATE STORE] Stored result for saga {saga_id}")
    
    def get_result(self, saga_id: str) -> Optional[dict]:
        data_str = self._redis.get(f"saga:{saga_id}")
        if not data_str:
            return None
        
        data = json.loads(data_str)
        return data.get("result")
    
    def get_status(self, saga_id: str) -> str:
        data_str = self._redis.get(f"saga:{saga_id}")
        if not data_str:
            return "pending"
        
        data = json.loads(data_str)
        return data.get("status", "pending")
    
    def mark_pending(self, saga_id: str, initial_data: dict = None):
        data = {
            "result": initial_data or {},
            "timestamp": datetime.utcnow().isoformat(),
            "status": "pending"
        }
        self._redis.setex(f"saga:{saga_id}", self._ttl_seconds, json.dumps(data))
        print(f"[STATE STORE] Marked saga {saga_id} as pending")
            
    def update_result(self, saga_id: str, result_update: dict, status: Optional[str] = None):
        data_str = self._redis.get(f"saga:{saga_id}")
        if data_str:
            data = json.loads(data_str)
            data["result"].update(result_update)
            data["timestamp"] = datetime.utcnow().isoformat()
            if status:
                data["status"] = status
            # Save back with same TTL
            self._redis.setex(f"saga:{saga_id}", self._ttl_seconds, json.dumps(data))
            print(f"[STATE STORE] Updated progress for saga {saga_id}")
    
    def clear_result(self, saga_id: str):
        self._redis.delete(f"saga:{saga_id}")
        print(f"[STATE STORE] Cleared result for saga {saga_id}")

# Singleton instance
_state_store = SagaStateStore()

def get_saga_state_store() -> SagaStateStore:
    return _state_store
