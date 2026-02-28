import os
import threading
from typing import Any, List, Dict

_driver = None
_driver_lock = threading.Lock()


def get_neo4j_driver():
    """
    Returns a cached Neo4j driver. Reads NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD from env.
    """
    global _driver

    if _driver is not None:
        return _driver

    with _driver_lock:
        if _driver is not None:
            return _driver

        from neo4j import GraphDatabase

        uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")

        print(f"[Neo4j] Connecting to {uri} as {user}")
        _driver = GraphDatabase.driver(uri, auth=(user, password))
        return _driver


def run_query(cypher: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """Execute a Cypher query and return results as a list of dicts."""
    driver = get_neo4j_driver()
    params = params or {}
    with driver.session() as session:
        result = session.run(cypher, params)
        return [record.data() for record in result]


def close_driver():
    """Close the Neo4j driver (call on shutdown)."""
    global _driver
    with _driver_lock:
        if _driver is not None:
            _driver.close()
            _driver = None
