#!/usr/bin/env python3
"""
Load Testing Script for SQL Insight Engine
Runs sequential requests to test load balancing across MCP replicas
"""

import asyncio
import aiohttp
import time
import json
from dataclasses import dataclass
from typing import List

# Configuration
API_BASE_URL = "http://localhost:8005"
USER_ID = 5  # User ID for account 'testxxxxxwwq'
QUERY = "What is my total revenue?"
TOTAL_REQUESTS = 30
DELAY_BETWEEN_REQUESTS = 0.1  # seconds

@dataclass
class RequestResult:
    request_id: int
    success: bool
    status_code: int
    duration_ms: float
    saga_id: str = None
    error: str = None

async def send_query(session: aiohttp.ClientSession, request_id: int) -> RequestResult:
    """Send a single query request"""
    start_time = time.time()
    
    try:
        payload = {
            "question": QUERY
        }
        
        async with session.post(
            f"{API_BASE_URL}/users/{USER_ID}/query/async",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            duration_ms = (time.time() - start_time) * 1000
            
            try:
                data = await response.json()
            except:
                data = await response.text()
            
            if response.status == 200:
                saga_id = data.get("saga_id", "N/A") if isinstance(data, dict) else "N/A"
                return RequestResult(
                    request_id=request_id,
                    success=True,
                    status_code=response.status,
                    duration_ms=duration_ms,
                    saga_id=saga_id
                )
            else:
                return RequestResult(
                    request_id=request_id,
                    success=False,
                    status_code=response.status,
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

async def run_load_test():
    """Run sequential load test"""
    print(f"=" * 60)
    print(f"SQL Insight Engine Load Test (Sequential)")
    print(f"=" * 60)
    print(f"API URL: {API_BASE_URL}")
    print(f"User ID: {USER_ID}")
    print(f"Query: {QUERY}")
    print(f"Total Requests: {TOTAL_REQUESTS}")
    print(f"=" * 60)
    print()
    
    start_time = time.time()
    results: List[RequestResult] = []
    
    async with aiohttp.ClientSession() as session:
        for i in range(TOTAL_REQUESTS):
            result = await send_query(session, i + 1)
            results.append(result)
            
            status = "✓" if result.success else "✗"
            saga_display = result.saga_id[:8] if result.saga_id and result.saga_id != "N/A" else (result.error[:30] if result.error else "unknown")
            print(f"  [{i+1:2}/{TOTAL_REQUESTS}] {status} {result.duration_ms:.0f}ms - {saga_display}")
            
            if i < TOTAL_REQUESTS - 1:
                await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
    
    total_duration = (time.time() - start_time) * 1000
    
    # Analyze results
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    
    durations = [r.duration_ms for r in successful] if successful else [0]
    avg_duration = sum(durations) / len(durations)
    min_duration = min(durations)
    max_duration = max(durations)
    
    print()
    print(f"=" * 60)
    print(f"Results Summary")
    print(f"=" * 60)
    print(f"Total Requests:     {len(results)}")
    print(f"Successful:         {len(successful)} ({len(successful)/len(results)*100:.1f}%)")
    print(f"Failed:             {len(failed)} ({len(failed)/len(results)*100:.1f}%)")
    print()
    print(f"Total Time:         {total_duration/1000:.2f} s")
    print(f"Avg Response Time:  {avg_duration:.2f} ms")
    print(f"Min Response Time:  {min_duration:.2f} ms")
    print(f"Max Response Time:  {max_duration:.2f} ms")
    print()
    
    if failed:
        print(f"Failed Requests (first 5):")
        for r in failed[:5]:
            print(f"  - Request #{r.request_id}: status={r.status_code}")
    
    print()
    print(f"=" * 60)
    print(f"Check Grafana at http://localhost:4000 for metrics distribution")
    print(f"=" * 60)

if __name__ == "__main__":
    asyncio.run(run_load_test())
