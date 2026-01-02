#!/usr/bin/env python3
"""
Load Testing Script for SQL Insight Engine (High Throughput)
Runs concurrent requests to test load balancing across MCP replicas
(Uses threading + requests to avoid async dependency issues)
"""

import time
import json
import argparse
import requests
import concurrent.futures
from dataclasses import dataclass
from typing import List

import os

# Configuration
# Can be overridden by --api-url arg
DEFAULT_API_URL = "http://localhost:8005"
USER_ID = 5
QUERY = "What is my total revenue?"

@dataclass
class RequestResult:
    request_id: int
    success: bool
    status_code: int
    duration_ms: float
    saga_id: str = None
    error: str = None

def send_query(api_url: str, request_id: int) -> RequestResult:
    """Send a single query request synchronously but with timeout to act as fire-and-forget"""
    start_time = time.time()
    
    try:
        payload = {
            "question": QUERY
        }
        
        # We use a very short timeout because we don't assume we want to wait for the answer.
        # User said "don't wait to any reposonse" which likely means "load generator should just blast".
        # However, to log 400/500 errors, we ideally need the server to accept the connection.
        # If we set timeout too short (e.g. 0.001), we might not even send the request.
        # A reasonable compromise for "fire and forget but verify receipt" is a small read timeout.
        try:
            response = requests.post(
                f"{api_url}/users/{USER_ID}/query/async",
                json=payload,
                timeout=0.5 
            )
            status_code = response.status_code
            error_msg = None
            success = 200 <= status_code < 300
            if not success:
                error_msg = f"HTTP {status_code}"
                
        except requests.exceptions.ReadTimeout:
            # We treat ReadTimeout as "Sent successfully" if the goal is just to blast
            # But usually load tests count this as failure or partial success.
            # Given "don't wait to any reposonse", we can mark this as success-in-delivery
            # IF we assume the server received it. 
            # For logging purposes, let's treat it as status 0 (unknown) but delivered.
            status_code = 0 
            success = True 
            error_msg = "Timeout (Fire & Forget)"
        except requests.exceptions.ConnectTimeout:
             return RequestResult(request_id, False, 0, (time.time() - start_time) * 1000, error="Connect Timeout")
        except requests.exceptions.ConnectionError:
             return RequestResult(request_id, False, 0, (time.time() - start_time) * 1000, error="Connection Error")

        duration_ms = (time.time() - start_time) * 1000
        
        return RequestResult(
            request_id=request_id,
            success=success,
            status_code=status_code,
            duration_ms=duration_ms,
            error=error_msg
        )
                
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        return RequestResult(
            request_id=request_id,
            success=False,
            status_code=0,
            duration_ms=duration_ms,
            error=str(e)[:100]
        )

def run_load_test(api_url: str, target_rps: int, duration_seconds: int):
    """Run concurrent load test"""
    print(f"=" * 60)
    print(f"SQL Insight Engine Load Test (Fire & Forget Mode)")
    print(f"=" * 60)
    print(f"API URL:      {api_url}")
    print(f"User ID:      {USER_ID}")
    print(f"Target RPS:   {target_rps}")
    print(f"Duration:     {duration_seconds}s")
    print(f"=" * 60)
    print()
    
    start_time = time.time()
    
    # Use a large thread pool
    max_workers = min(target_rps * 2, 500) 
    
    import threading
    from collections import defaultdict
    stats_lock = threading.Lock()
    stats = defaultdict(int)
    
    def on_request_complete(f):
        try:
            res = f.result()
            with stats_lock:
                stats["total_finished"] += 1
                if res.success:
                    stats["success"] += 1
                else:
                    stats["failed"] += 1
                
                if res.status_code > 0:
                    stats[f"status_{res.status_code}"] += 1
                elif res.error:
                     stats[f"err_{res.error}"] += 1
        except Exception:
            with stats_lock:
                stats["failed"] += 1
                stats["err_future_exception"] += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        
        interval = 1.0  # 1 second intervals
        next_tick = start_time + interval
        request_counter = 0
        
        while (time.time() - start_time) < duration_seconds:
            # Burst loop
            now = time.time()
            # Calculate how many to allow based on time elapsed to maintain RPS
            # Simple approach: just launch target_rps every second
            
            for _ in range(target_rps):
                request_counter += 1
                future = executor.submit(send_query, api_url, request_counter)
                future.add_done_callback(on_request_complete)
            
            now_after_submit = time.time()
            sleep_time = next_tick - now_after_submit
            
            with stats_lock:
                s_counts = dict(stats)

            # Build status string
            status_str = f"Success: {s_counts.get('success',0)} | Failed: {s_counts.get('failed',0)}"
            
            # Add specific codes if prominent
            codes = [k for k in s_counts.keys() if str(k).startswith("status_") and s_counts[k] > 0]
            if codes:
                code_summary = ", ".join([f"{k.replace('status_', '')}: {s_counts[k]}" for k in codes])
                status_str += f" | Codes: [{code_summary}]"

            print(f"  [T+{int(now-start_time)}s] Launched: {request_counter} | {status_str}")
            
            if sleep_time > 0:
                time.sleep(sleep_time)
            
            next_tick += interval

    total_time = time.time() - start_time
    
    print()
    print(f"=" * 60)
    print(f"Results Summary")
    print(f"=" * 60)
    print(f"Total Requests (Launched):  {request_counter}")
    print(f"Total Requests (Finished):  {stats['total_finished']}")
    print(f"Successful:                 {stats['success']}")
    print(f"Failed:                     {stats['failed']}")
    print(f"Actual Throughput:          {stats['total_finished']/total_time:.2f} req/s")
    print("-" * 30)
    print("Status Code Breakdown:")
    for k, v in sorted(stats.items()):
        if k.startswith("status_"):
            print(f"  HTTP {k.replace('status_', '')}: {v}")
    
    print("-" * 30)
    print("Error Breakdown:")
    for k, v in sorted(stats.items()):
        if k.startswith("err_"):
             print(f"  {k.replace('err_', '')}: {v}")
    print(f"=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Load Test SQL Insight Engine')
    parser.add_argument('--rps', type=int, default=20, help='Requests per second (default: 20)')
    parser.add_argument('--duration', type=int, default=6000, help='Duration in seconds (default: 600)')
    parser.add_argument('--api-url', type=str, default=DEFAULT_API_URL, help='API Base URL')
    args = parser.parse_args()
    
    run_load_test(args.api_url, args.rps, args.duration)
