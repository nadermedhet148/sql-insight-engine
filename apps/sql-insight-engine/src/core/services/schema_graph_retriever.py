from typing import List


def retrieve_relevant_tables(question: str, account_id: str, top_k: int = 3) -> str:
    """
    Graph-RAG schema retrieval:
      1. ChromaDB vector search → top-K seed tables (semantic similarity)
      2. Neo4j 1-hop FK expansion → JOIN-able neighbor tables
      3. Fetch DDL for all resolved tables from Neo4j
      4. Return formatted schema string ready for LLM prompt injection

    Returns an empty string if no schema is found (caller should treat as OUT_OF_SCOPE).
    """
    from core.gemini_client import GeminiClient
    from core.infra.chroma_factory import ChromaClientFactory
    from core.infra.neo4j_client import run_query as neo4j_run

    # --- Step 1: ChromaDB vector search ---
    gemini = GeminiClient()
    query_embedding = gemini.get_embedding(question, task_type="retrieval_query")

    if not query_embedding:
        print("[SchemaGraphRetriever] Warning: Empty embedding — falling back to empty schema context")
        return ""

    chroma_client = ChromaClientFactory.get_client()
    try:
        collection = chroma_client.get_collection(name="account_schema_info")
    except Exception:
        print("[SchemaGraphRetriever] Warning: account_schema_info collection not found")
        return ""

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"account_id": account_id},
        )
    except Exception as e:
        print(f"[SchemaGraphRetriever] ChromaDB query failed: {e}")
        return ""

    seed_table_names: List[str] = []
    if results and results.get("metadatas") and results["metadatas"][0]:
        for meta in results["metadatas"][0]:
            table_name = meta.get("table_name")
            if table_name and table_name not in seed_table_names:
                seed_table_names.append(table_name)

    if not seed_table_names:
        print("[SchemaGraphRetriever] No seed tables found in ChromaDB")
        return ""

    print(f"[SchemaGraphRetriever] Seed tables from ChromaDB: {seed_table_names}")

    # --- Step 2: Neo4j 1-hop expansion (all edge types) ---
    neighbor_names: List[str] = []
    try:
        rows = neo4j_run(
            """
            MATCH (s:Table {account_id: $account_id})
            WHERE s.table_name IN $seed_tables
            MATCH (s)-[:FK_TO|INFERRED_FK|LLM_RELATION]-(n:Table {account_id: $account_id})
            WHERE NOT n.table_name IN $seed_tables
            RETURN DISTINCT n.table_name AS table_name
            """,
            {"account_id": account_id, "seed_tables": seed_table_names},
        )
        neighbor_names = [row["table_name"] for row in rows if row.get("table_name")]
        print(f"[SchemaGraphRetriever] FK neighbors from Neo4j: {neighbor_names}")
    except Exception as e:
        print(f"[SchemaGraphRetriever] Warning: Neo4j expansion failed: {e}. Using seeds only.")

    all_table_names = list(dict.fromkeys(seed_table_names + neighbor_names))  # preserve order, dedupe

    # --- Step 3: Fetch DDL for all resolved tables from Neo4j ---
    ddl_map: dict[str, str] = {}
    try:
        rows = neo4j_run(
            """
            MATCH (t:Table {account_id: $account_id})
            WHERE t.table_name IN $table_names
            RETURN t.table_name AS table_name, t.ddl_text AS ddl_text
            """,
            {"account_id": account_id, "table_names": all_table_names},
        )
        for row in rows:
            if row.get("table_name") and row.get("ddl_text"):
                ddl_map[row["table_name"]] = row["ddl_text"]
    except Exception as e:
        print(f"[SchemaGraphRetriever] Warning: Neo4j DDL fetch failed: {e}")

    if not ddl_map:
        print("[SchemaGraphRetriever] No DDL found in Neo4j — schema context will be empty")
        return ""

    # --- Step 4: Format and return ---
    sections = []
    for table_name in all_table_names:
        if table_name in ddl_map:
            sections.append(ddl_map[table_name])

    schema_context = "\n\n".join(sections)
    print(f"[SchemaGraphRetriever] Resolved {len(sections)} tables: {list(ddl_map.keys())}")
    return schema_context
