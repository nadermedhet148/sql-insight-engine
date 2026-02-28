# Graph-RAG Schema Retrieval with Qdrant

## Problem

The current agentic SQL generation loop calls `list_tables` to fetch all table names, then iterates through `describe_table` for each relevant table. For a database with **1,000+ tables**, this causes:

- Massive LLM context from listing all table names
- Multiple round-trip tool calls just to identify which tables are relevant
- High token usage and latency per query
- LLM hallucination risk when overwhelmed with irrelevant schema noise

---

## Proposed Solution: Graph-RAG Schema Retrieval

Instead of letting the LLM discover the schema on its own via tools, we pre-retrieve the exact relevant tables **before** the LLM starts, using a two-stage approach:

1. **Vector Search** — embed the user's question and find the most semantically similar tables in Qdrant
2. **Graph Expansion** — follow foreign key (FK) relationships from those seed tables to pull in JOIN-able neighbors

The LLM receives a focused, pre-assembled schema context (5–15 tables max) instead of the entire database.

---

## Architecture Overview

```
User Question
     │
     ▼
[1] Embed Question (Gemini text-embedding-004)
     │
     ▼
[2] Qdrant Vector Search → Top-K Seed Tables (k=3)
     │
     ▼
[3] Graph Expansion via FK edges (1 hop BFS)
     │      ┌─────────────────────┐
     │      │  Qdrant Payload     │
     │      │  - columns          │
     │      │  - foreign_keys     │
     │      │  - referenced_by    │
     └─────►│  - full DDL text    │
            └─────────────────────┘
     │
     ▼
[4] Assemble Schema Context (resolved tables + schemas)
     │
     ▼
[5] Inject into LLM Prompt (no list_tables / describe_table calls needed)
     │
     ▼
[6] LLM generates SQL with full, accurate context
```

---

## Data Model

### Qdrant Collection: `schema_graph`

Each **point** in Qdrant represents one table.

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Deterministic hash of `account_id + table_name` |
| `vector` | float[] | Embedding of the table's semantic text |
| `payload.account_id` | string | Tenant isolation |
| `payload.table_name` | string | Table name |
| `payload.columns` | list[object] | `[{name, type, nullable, is_pk}]` |
| `payload.foreign_keys` | list[object] | `[{column, referred_table, referred_column}]` |
| `payload.referenced_by` | list[string] | Tables that FK into this table |
| `payload.ddl_text` | string | Human-readable schema (used as vector source) |
| `payload.db_name` | string | Source database name |

### Embedding Source Text (per table)

The vector is generated from a structured text representation of the table:

```
Table: orders
Columns:
  - id: INTEGER (PK, NOT NULL)
  - user_id: INTEGER (NOT NULL)
  - product_id: INTEGER (NOT NULL)
  - total_amount: NUMERIC (NOT NULL)
  - status: VARCHAR (NOT NULL)
  - created_at: TIMESTAMP (NOT NULL)
Foreign Keys:
  - user_id → users(id)
  - product_id → products(id)
Referenced By:
  - order_items.order_id
```

This allows semantic matching on both table purpose AND data relationships.

---

## Indexing Pipeline

Triggered at the same point as the current schema indexing: **when a user saves their DB config** (`POST /users/{user_id}/config`).

```
DB Config Saved
      │
      ▼
For each table in database:
  1. inspector.get_columns(table)
  2. inspector.get_pk_constraint(table)
  3. inspector.get_foreign_keys(table)          ← FK edges (outbound)
  4. Build referenced_by map (inbound FK edges)  ← pass through all tables first
  5. Build ddl_text string
  6. Generate embedding via Gemini text-embedding-004
  7. Upsert point into Qdrant `schema_graph` collection
      with payload: {account_id, table_name, columns, foreign_keys, referenced_by, ddl_text}
```

### Two-Pass Strategy for `referenced_by`

Because SQLAlchemy only gives you outbound FKs (`table A references table B`), you need a reverse pass:

```
Pass 1: For each table, collect all foreign_keys → build global map:
        {referred_table: [source_table, ...]}

Pass 2: For each table, look up its name in the map to get referenced_by list.

Then upsert all points together.
```

---

## Retrieval Pipeline

Called at the start of the query generation step, **before the LLM starts**.

```python
def retrieve_relevant_schema(question: str, account_id: str, top_k: int = 3, hops: int = 1) -> list[TableSchema]:

    # Step 1: Embed the question
    query_vector = embed(question)

    # Step 2: Vector search in Qdrant
    seed_results = qdrant.search(
        collection_name="schema_graph",
        query_vector=query_vector,
        query_filter=Filter(must=[FieldCondition(key="account_id", match=MatchValue(value=account_id))]),
        limit=top_k
    )
    seed_table_names = [r.payload["table_name"] for r in seed_results]

    # Step 3: Graph expansion (BFS, 1 hop)
    neighbor_names = set()
    for result in seed_results:
        for fk in result.payload["foreign_keys"]:
            neighbor_names.add(fk["referred_table"])
        for ref in result.payload["referenced_by"]:
            neighbor_names.add(ref)

    # Step 4: Fetch neighbor points from Qdrant by table name
    all_table_names = set(seed_table_names) | neighbor_names
    neighbor_points = qdrant.scroll(
        collection_name="schema_graph",
        scroll_filter=Filter(must=[
            FieldCondition(key="account_id", match=MatchValue(value=account_id)),
            FieldCondition(key="table_name", match=MatchAny(any=list(neighbor_names)))
        ]),
        with_payload=True
    )

    # Step 5: Assemble and return
    all_points = seed_results + neighbor_points[0]
    return [point.payload for point in all_points]
```

---

## Integration into Query Generation

### Current flow (LLM tool calls every query)

```
LLM → list_tables (returns ALL table names)
LLM → search_relevant_schema (ChromaDB fuzzy match)
LLM → describe_table("orders")
LLM → describe_table("users")
LLM → describe_table("products")
LLM → generate SQL
```

### New flow with Graph-RAG (pre-fetched, no LLM discovery loop)

```
Before LLM starts:
  retrieve_relevant_schema(question, account_id)
  → returns [orders, users, products, order_items] with full schemas

LLM receives prompt with:
  "Available Schema:\n<full DDL for 4 tables>\n\nQuestion: ..."

LLM → generate SQL (single pass, no tool calls for schema discovery)
```

The LLM still retains `run_query` for execution and `search_business_knowledge` for domain rules. Schema discovery is no longer a tool — it is pre-resolved infrastructure.

---

## New Components Required

### 1. `packages/mcp-qdrant/` — Schema Graph MCP Service

A new MCP service exposing a single tool to the LLM:

| Tool | Description |
|---|---|
| `retrieve_schema_graph` | Given a question + account_id, return relevant table schemas via Graph-RAG |

Internally calls the retrieval pipeline above. Returns structured DDL text ready for the prompt.

### 2. `src/core/infra/qdrant_client.py` — Qdrant Client

Thin wrapper for the `qdrant-client` Python SDK. Handles:
- Collection creation with cosine similarity
- Upsert with payload
- Filtered vector search
- Filtered scroll for payload fetch

### 3. `src/core/services/schema_indexer.py` — Schema Graph Indexer

Service called from `account/api.py` on DB config save. Replaces the current ChromaDB schema indexing. Implements the two-pass indexing pipeline described above.

### 4. Docker: `qdrant` service

```yaml
qdrant:
  image: qdrant/qdrant:latest
  ports:
    - "6333:6333"
  volumes:
    - qdrant_data:/qdrant/storage
  networks:
    - insight_network
```

---

## Collection Configuration

```python
from qdrant_client.models import Distance, VectorParams

qdrant.recreate_collection(
    collection_name="schema_graph",
    vectors_config=VectorParams(
        size=768,          # Gemini text-embedding-004 dimension
        distance=Distance.COSINE
    )
)
```

---

## Retrieval Tuning Parameters

| Parameter | Default | Notes |
|---|---|---|
| `top_k` | 3 | Seed tables from vector search |
| `hops` | 1 | FK graph expansion depth |
| Max tables returned | ~15 | top_k + their direct FK neighbors |
| Embedding model | `text-embedding-004` | Same as existing knowledge base |

For databases with deep FK chains (e.g., `orders → order_items → order_line → product_variant → product`), `hops=1` is sufficient because the most central tables in the question will naturally be the seeds, and their immediate neighbors cover the JOIN path.

---

## Benefits Over Current Approach

| Metric | Current (LLM tool loop) | Graph-RAG |
|---|---|---|
| LLM tool calls per query | 4–8 (for a 3-table query) | 0 for schema discovery |
| Context size with 1000 tables | `list_tables` returns all 1000 names | 5–15 tables max |
| Accuracy of table selection | LLM guesses based on names | Vector similarity + FK structure |
| Latency | Multiple MCP round-trips | Single Qdrant call pre-LLM |
| Hallucination risk | High (LLM picks tables from memory) | Low (schema is ground truth in Qdrant) |

---

## Re-indexing Triggers

| Event | Action |
|---|---|
| User adds DB config | Full index of all tables |
| User updates DB config | Re-index all tables (upsert by ID) |
| User deletes DB config | Delete all points where `account_id = X` |
| Schema migration detected | Re-index affected tables (future: via webhook or periodic diff) |
