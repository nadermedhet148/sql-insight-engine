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
    """Send a single query request synchronously"""
    start_time = time.time()
    
    try:
        payload = {
            "question": QUERY
        }
        
        # Use a session for connection pooling if possible, but for simplicity here we assume
        # requests will use its internal pool or new connections. 
        # For high performance, we should pass a session.
        response = requests.post(
            f"{api_url}/users/{USER_ID}/query/async",
            json=payload,
            timeout=30
        )
        
        duration_ms = (time.time() - start_time) * 1000
        
        try:
            data = response.json()
        except:
            data = response.text
        
        if response.status_code == 200:
            saga_id = data.get("saga_id", "N/A") if isinstance(data, dict) else "N/A"
            return RequestResult(
                request_id=request_id,
                success=True,
                status_code=response.status_code,
                duration_ms=duration_ms,
                saga_id=saga_id
            )
        else:
            return RequestResult(
                request_id=request_id,
                success=False,
                status_code=response.status_code,
                duration_ms=duration_ms,
                error=str(data)[:100]
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
    print(f"SQL Insight Engine Load Test (Threaded)")
    print(f"=" * 60)
    print(f"API URL:      {api_url}")
    print(f"User ID:      {USER_ID}")
    print(f"Target RPS:   {target_rps}")
    print(f"Duration:     {duration_seconds}s")
    print(f"=" * 60)
    print()
    
    start_time = time.time()
    results: List[RequestResult] = []
    request_counter = 0
    futures = []
    
    # Use a large thread pool
    max_workers = min(target_rps * 5, 200) # Cap at 200 to avoid OS limits if RPS is huge
    
    import threading
    stats_lock = threading.Lock()
    success_count = 0
    fail_count = 0
    
    def on_request_complete(f):
        nonlocal success_count, fail_count
        try:
            res = f.result()
            with stats_lock:
                if res.success:
                    success_count += 1
                else:
                    fail_count += 1
        except:
            with stats_lock:
                fail_count += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        
        interval = 1.0  # 1 second intervals
        next_tick = start_time + interval
        
        while (time.time() - start_time) < duration_seconds:
            # simple bursty scheduler
            
            for _ in range(target_rps):
                request_counter += 1
                future = executor.submit(send_query, api_url, request_counter)
                future.add_done_callback(on_request_complete)
                futures.append(future)
            
            now = time.time()
            sleep_time = next_tick - now
            
            with stats_lock:
                current_success = success_count
                current_fail = fail_count

            print(f"  [T+{int(now-start_time)}s] Launched: {request_counter} | Success: {current_success} | Failed: {current_fail}")
            
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                pass # behind schedule
            
            next_tick += interval

        print("Waiting for pending requests to complete...")
        concurrent.futures.wait(futures, timeout=35)
        
        for f in futures:
            if f.done():
                try:
                    results.append(f.result())
                except Exception as e:
                    print(f"Result retrieval failed: {e}")
            else:
                # Cancel pending?
                pass

    total_time = time.time() - start_time
    
    # Analyze results
    print(f"\nProcessing {len(results)} results...")
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    
    durations = [r.duration_ms for r in successful] if successful else [0]
    if durations:
        avg_duration = sum(durations) / len(durations)
        min_duration = min(durations)
        max_duration = max(durations)
    else:
        avg_duration = 0
        min_duration = 0
        max_duration = 0
    
    print()
    print(f"=" * 60)
    print(f"Results Summary")
    print(f"=" * 60)
    print(f"Total Requests (Launched):  {request_counter}")
    print(f"Total Requests (Finished):  {len(results)}")
    print(f"Successful:                 {len(successful)} ({len(successful)/len(results)*100 if results else 0:.1f}%)")
    print(f"Failed:                     {len(failed)} ({len(failed)/len(results)*100 if results else 0:.1f}%)")
    print()
    print(f"Total Test Duration:        {total_time:.2f} s")
    print(f"Actual Throughput:          {len(results)/total_time:.2f} req/s")
    print(f"Avg Response Time:          {avg_duration:.2f} ms")
    print(f"Min Response Time:          {min_duration:.2f} ms")
    print(f"Max Response Time:          {max_duration:.2f} ms")
    print()
    
    if failed:
        print(f"Failed Requests (first 5):")
        for r in failed[:5]:
            print(f"  - Request #{r.request_id}: status={r.status_code} error={r.error}")
    
    print()
    print(f"=" * 60)
    print(f"Check Grafana at http://localhost:4000 for metrics distribution")
    print(f"=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Load Test SQL Insight Engine')
    parser.add_argument('--rps', type=int, default=10000, help='Requests per second (default: 100)')
    parser.add_argument('--duration', type=int, default=600, help='Duration in seconds (default: 600)')
    parser.add_argument('--api-url', type=str, default=DEFAULT_API_URL, help='API Base URL')
    args = parser.parse_args()
    
    run_load_test(args.api_url, args.rps, args.duration)
