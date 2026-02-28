import json
from typing import Any

from sqlalchemy import create_engine, inspect


def _detect_heuristic_fks(table_data: dict) -> list[dict]:
    """
    Detect implicit FK relationships via column naming conventions.
    If a column ends with '_id' and the stripped name matches a table in the schema,
    create an INFERRED_FK edge (only when no explicit FK_TO already covers it).

    Returns: [{src_table, src_column, tgt_table, tgt_column}]
    """
    all_table_names = set(table_data.keys())
    inferred = []

    for table_name, data in table_data.items():
        for col in data["columns"]:
            col_name = col["name"]
            if not col_name.endswith("_id"):
                continue

            candidate = col_name[:-3]  # strip "_id"
            for tgt in [candidate, candidate + "s", candidate + "es"]:
                if tgt in all_table_names and tgt != table_name:
                    already_explicit = any(
                        fk["referred_table"] == tgt for fk in data["fks"]
                    )
                    if not already_explicit:
                        inferred.append({
                            "src_table": table_name,
                            "src_column": col_name,
                            "tgt_table": tgt,
                            "tgt_column": "id",
                        })
                    break

    return inferred


def _infer_relations_with_llm(table_data: dict, existing_edges: set) -> list[dict]:
    """
    Use Gemini to infer JOIN relationships not already captured by FK constraints
    or heuristic detection. Makes a single structured text call at indexing time.

    existing_edges: set of (src_table, tgt_table) tuples already detected
    Returns: [{src_table, src_column, tgt_table, tgt_column}]
    """
    from core.gemini_client import GeminiClient

    schema_lines = []
    for table_name, data in table_data.items():
        col_names = [col["name"] for col in data["columns"]]
        schema_lines.append(f"- {table_name}: {', '.join(col_names)}")

    schema_summary = "\n".join(schema_lines)
    detected_str = "\n".join(f"- {s} → {t}" for s, t in existing_edges) or "None"

    prompt = f"""You are a database analyst. Given the following database schema, identify JOIN relationships between tables that are NOT already captured.

SCHEMA:
{schema_summary}

ALREADY DETECTED RELATIONSHIPS (do NOT repeat these):
{detected_str}

Return ONLY a JSON array. Each element must have exactly these keys:
  "src_table": source table name (must exist in schema above)
  "src_column": source column name (must exist in that table)
  "tgt_table": target table name (must exist in schema above)
  "tgt_column": target column name

Return [] if no additional relationships can be inferred.
Return ONLY valid JSON with no explanation or markdown."""

    client = GeminiClient(tools=None)
    response = client.generate_content(prompt)
    if not response or not getattr(response, "text", None):
        return []

    try:
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        relations = json.loads(text.strip())
        # Validate each item has required keys and references real tables
        valid = []
        for r in relations:
            if all(k in r for k in ("src_table", "src_column", "tgt_table", "tgt_column")):
                if r["src_table"] in table_data and r["tgt_table"] in table_data:
                    valid.append(r)
        return valid
    except Exception as e:
        print(f"[SchemaGraphIndexer] LLM relation parse failed: {e}")
        return []


def _build_db_url(db_config: Any) -> str:
    db_type = getattr(db_config, "db_type", "postgresql") or "postgresql"
    port = db_config.port or 5432
    if db_type == "mysql":
        return f"mysql+pymysql://{db_config.username}:{db_config.password}@{db_config.host}:{port}/{db_config.db_name}"
    elif db_type == "mssql":
        return f"mssql+pymssql://{db_config.username}:{db_config.password}@{db_config.host}:{port}/{db_config.db_name}"
    return f"postgresql://{db_config.username}:{db_config.password}@{db_config.host}:{port}/{db_config.db_name}"


def _build_ddl_text(table_name: str, columns: list, pk: dict, fks: list) -> str:
    """Build human-readable DDL text identical to describe_table output."""
    text = f"## Table: {table_name}\n\n### Columns:\n"
    pk_cols = set(pk.get("constrained_columns", []))
    for col in columns:
        nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
        is_pk = " (PK)" if col["name"] in pk_cols else ""
        text += f"- **{col['name']}**: {col['type']} ({nullable}){is_pk}\n"

    if pk_cols:
        text += f"\n### Primary Key: {', '.join(pk_cols)}\n"

    if fks:
        text += "\n### Foreign Keys:\n"
        for fk in fks:
            from_cols = ", ".join(fk["constrained_columns"])
            to_cols = ", ".join(fk["referred_columns"])
            text += f"- {from_cols} → {fk['referred_table']}({to_cols})\n"

    return text


def index_schema_to_graph(account_id: str, db_config: Any) -> None:
    """
    Index the full schema of a user's database into:
      - ChromaDB collection "account_schema_info" (vector search)
      - Neo4j graph (FK relationship traversal)

    Uses SQLAlchemy inspector directly — no MCP round-trip needed.

    Two-pass strategy:
      Pass 1: Collect columns, PK, FKs for every table + build reverse FK map
      Pass 2: Write ChromaDB embeddings and Neo4j nodes/edges
    """
    from core.gemini_client import GeminiClient
    from core.infra.chroma_factory import ChromaClientFactory
    from core.infra.neo4j_client import run_query as neo4j_run

    db_url = _build_db_url(db_config)
    engine = create_engine(db_url, pool_pre_ping=True)
    inspector = inspect(engine)

    dialect = engine.dialect.name
    if dialect == "postgresql":
        schema = "public"
    elif dialect == "mssql":
        schema = "dbo"
    else:
        schema = None

    table_names = inspector.get_table_names(schema=schema)
    if not table_names:
        print(f"[SchemaGraphIndexer] No tables found in {db_config.db_name}")
        return

    print(f"[SchemaGraphIndexer] Collecting schema for {len(table_names)} tables...")

    # --- Pass 1: Collect raw data ---
    table_data = {}
    reverse_fk_map: dict[str, list[str]] = {}  # referred_table → [source_tables]

    for table_name in table_names:
        try:
            columns = inspector.get_columns(table_name, schema=schema)
            pk = inspector.get_pk_constraint(table_name, schema=schema)
            fks = inspector.get_foreign_keys(table_name, schema=schema)
        except Exception as e:
            print(f"[SchemaGraphIndexer] Warning: Could not inspect {table_name}: {e}")
            continue

        table_data[table_name] = {
            "columns": columns,
            "pk": pk,
            "fks": fks,
            "ddl_text": _build_ddl_text(table_name, columns, pk, fks),
        }

        for fk in fks:
            referred = fk["referred_table"]
            reverse_fk_map.setdefault(referred, [])
            if table_name not in reverse_fk_map[referred]:
                reverse_fk_map[referred].append(table_name)

    # --- Pass 2: Write to ChromaDB and Neo4j ---
    gemini = GeminiClient()
    chroma_client = ChromaClientFactory.get_client()
    collection = chroma_client.get_or_create_collection(name="account_schema_info")

    chroma_ids = []
    chroma_docs = []
    chroma_embeddings = []
    chroma_metadatas = []

    for table_name, data in table_data.items():
        ddl_text = data["ddl_text"]
        embedding = gemini.get_embedding(ddl_text, task_type="retrieval_document")
        if not embedding:
            print(f"[SchemaGraphIndexer] Warning: Empty embedding for {table_name}, skipping")
            continue

        doc_id = f"{account_id}_{db_config.db_name}_{table_name}"
        chroma_ids.append(doc_id)
        chroma_docs.append(ddl_text)
        chroma_embeddings.append(embedding)
        chroma_metadatas.append({
            "account_id": account_id,
            "table_name": table_name,
            "db_name": db_config.db_name,
            "filename": f"table_{db_config.db_name}_{table_name}.md",
        })

    # Upsert to ChromaDB (delete existing first for clean re-index)
    try:
        existing = collection.get(where={"account_id": account_id})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    if chroma_ids:
        collection.add(
            ids=chroma_ids,
            documents=chroma_docs,
            embeddings=chroma_embeddings,
            metadatas=chroma_metadatas,
        )
        print(f"[SchemaGraphIndexer] ChromaDB: indexed {len(chroma_ids)} tables for account {account_id}")

    # Write to Neo4j
    try:
        # Remove existing nodes for this account (clean re-index)
        neo4j_run(
            "MATCH (t:Table {account_id: $account_id}) DETACH DELETE t",
            {"account_id": account_id},
        )

        # Create table nodes
        for table_name, data in table_data.items():
            columns_json = json.dumps([
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "is_pk": col["name"] in set(data["pk"].get("constrained_columns", [])),
                }
                for col in data["columns"]
            ])
            referenced_by = reverse_fk_map.get(table_name, [])

            neo4j_run(
                """
                MERGE (t:Table {account_id: $account_id, table_name: $table_name})
                SET t.db_name = $db_name,
                    t.ddl_text = $ddl_text,
                    t.columns_json = $columns_json,
                    t.referenced_by = $referenced_by
                """,
                {
                    "account_id": account_id,
                    "table_name": table_name,
                    "db_name": db_config.db_name,
                    "ddl_text": data["ddl_text"],
                    "columns_json": columns_json,
                    "referenced_by": referenced_by,
                },
            )

        # --- Explicit FK_TO relationships ---
        explicit_edges: set[tuple[str, str]] = set()
        for table_name, data in table_data.items():
            for fk in data["fks"]:
                referred_table = fk["referred_table"]
                if referred_table not in table_data:
                    continue
                neo4j_run(
                    """
                    MATCH (src:Table {account_id: $account_id, table_name: $src})
                    MATCH (tgt:Table {account_id: $account_id, table_name: $tgt})
                    MERGE (src)-[r:FK_TO]->(tgt)
                    SET r.from_column = $from_col,
                        r.to_column = $to_col
                    """,
                    {
                        "account_id": account_id,
                        "src": table_name,
                        "tgt": referred_table,
                        "from_col": ", ".join(fk["constrained_columns"]),
                        "to_col": ", ".join(fk["referred_columns"]),
                    },
                )
                explicit_edges.add((table_name, referred_table))

        # --- Heuristic INFERRED_FK relationships ---
        heuristic_rels = _detect_heuristic_fks(table_data)
        heuristic_edges: set[tuple[str, str]] = set()
        for rel in heuristic_rels:
            neo4j_run(
                """
                MATCH (src:Table {account_id: $account_id, table_name: $src})
                MATCH (tgt:Table {account_id: $account_id, table_name: $tgt})
                MERGE (src)-[r:INFERRED_FK]->(tgt)
                SET r.from_column = $from_col,
                    r.to_column = $to_col
                """,
                {
                    "account_id": account_id,
                    "src": rel["src_table"],
                    "tgt": rel["tgt_table"],
                    "from_col": rel["src_column"],
                    "to_col": rel["tgt_column"],
                },
            )
            heuristic_edges.add((rel["src_table"], rel["tgt_table"]))
        print(f"[SchemaGraphIndexer] Heuristic FKs detected: {len(heuristic_rels)}")

        # --- LLM-inferred LLM_RELATION relationships ---
        existing_edges = explicit_edges | heuristic_edges
        llm_rels = _infer_relations_with_llm(table_data, existing_edges)
        for rel in llm_rels:
            neo4j_run(
                """
                MATCH (src:Table {account_id: $account_id, table_name: $src})
                MATCH (tgt:Table {account_id: $account_id, table_name: $tgt})
                MERGE (src)-[r:LLM_RELATION]->(tgt)
                SET r.from_column = $from_col,
                    r.to_column = $to_col
                """,
                {
                    "account_id": account_id,
                    "src": rel["src_table"],
                    "tgt": rel["tgt_table"],
                    "from_col": rel["src_column"],
                    "to_col": rel["tgt_column"],
                },
            )
        print(f"[SchemaGraphIndexer] LLM relations inferred: {len(llm_rels)}")

        print(f"[SchemaGraphIndexer] Neo4j: indexed {len(table_data)} nodes, "
              f"{len(explicit_edges)} FK_TO + {len(heuristic_edges)} INFERRED_FK + {len(llm_rels)} LLM_RELATION edges")

    except Exception as e:
        print(f"[SchemaGraphIndexer] Warning: Neo4j indexing failed: {e}. ChromaDB indexing succeeded.")

    engine.dispose()


def delete_schema_from_graph(account_id: str) -> None:
    """Remove all schema data for an account from both ChromaDB and Neo4j."""
    from core.infra.chroma_factory import ChromaClientFactory
    from core.infra.neo4j_client import run_query as neo4j_run

    # ChromaDB cleanup
    try:
        chroma_client = ChromaClientFactory.get_client()
        collection = chroma_client.get_or_create_collection(name="account_schema_info")
        existing = collection.get(where={"account_id": account_id})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
            print(f"[SchemaGraphIndexer] ChromaDB: removed {len(existing['ids'])} entries for account {account_id}")
    except Exception as e:
        print(f"[SchemaGraphIndexer] Warning: ChromaDB cleanup failed: {e}")

    # Neo4j cleanup
    try:
        neo4j_run(
            "MATCH (t:Table {account_id: $account_id}) DETACH DELETE t",
            {"account_id": account_id},
        )
        print(f"[SchemaGraphIndexer] Neo4j: removed all nodes for account {account_id}")
    except Exception as e:
        print(f"[SchemaGraphIndexer] Warning: Neo4j cleanup failed: {e}")
