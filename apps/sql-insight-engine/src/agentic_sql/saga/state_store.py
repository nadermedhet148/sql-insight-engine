import json
import redis
from redis import ConnectionPool
import os
from typing import Dict, Optional
from datetime import datetime, timedelta
from prometheus_client import Counter, Histogram

# Global Redis connection pool for better performance
_redis_pool: Optional[ConnectionPool] = None

def _get_redis_pool(host: str, port: int, db: int) -> ConnectionPool:
    """Get or create a global Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = ConnectionPool(
            host=host,
            port=port,
            db=db,
            max_connections=100,  # Allow up to 100 concurrent connections
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_pool

# Defining Metrics
SAGA_COMPLETION_TOTAL = Counter(
    "saga_completion_total",
    "Total number of completed sagas by status",
    ["status"]
)
SAGA_DURATION_SECONDS = Histogram(
    "saga_duration_seconds",
    "Duration of completed sagas in seconds",
    ["status"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
)

class SagaStateStore:

    def __init__(self, host: str = None, port: int = 6379, db: int = 0):
        host = host or os.getenv("REDIS_HOST", "localhost")
        pool = _get_redis_pool(host, port, db)
        self._redis = redis.Redis(connection_pool=pool)
        self._ttl_seconds = 3600  # 1 hour TTL
    
    def _record_metrics(self, status: str, started_at_iso: Optional[str]):
        if status in ["completed", "success", "error", "failed"]:
            metric_status = "success" if status in ["completed", "success"] else "failed"
            SAGA_COMPLETION_TOTAL.labels(status=metric_status).inc()
            
            if started_at_iso:
                try:
                    start_dt = datetime.fromisoformat(started_at_iso)
                    duration = (datetime.utcnow() - start_dt).total_seconds()
                    SAGA_DURATION_SECONDS.labels(status=metric_status).observe(duration)
                    print(f"[STATE STORE] Recorded duration {duration:.2f}s for status {status}")
                except Exception as e:
                    print(f"[STATE STORE] Failed to record duration: {e}")

    def store_result(self, saga_id: str, result: dict, status: Optional[str] = None):
        final_status = status if status else ("completed" if result.get("success", False) else "error")
        
        # Try to retrieve existing start time
        existing_data_str = self._redis.get(f"saga:{saga_id}")
        started_at = None
        if existing_data_str:
            try:
                existing = json.loads(existing_data_str)
                started_at = existing.get("started_at")
            except:
                pass
        
        data = {
            "result": result,
            "timestamp": datetime.utcnow().isoformat(),
            "status": final_status
        }
        if started_at:
            data["started_at"] = started_at
            
        self._redis.setex(f"saga:{saga_id}", self._ttl_seconds, json.dumps(data))
        print(f"[STATE STORE] Stored result for saga {saga_id}")
        
        self._record_metrics(final_status, started_at)
    
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
        now_iso = datetime.utcnow().isoformat()
        data = {
            "result": initial_data or {},
            "timestamp": now_iso,
            "started_at": now_iso,
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
                self._record_metrics(status, data.get("started_at"))

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
