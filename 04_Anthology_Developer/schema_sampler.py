"""
Postgres schema introspection — optimised for speed.

list_tables_fast() — table names only (one SQL query)
sample_tables()    — column names + types only, NO SELECT DISTINCT sampling
"""

import psycopg2
from typing import List, Dict, Optional, Callable


def get_conn(params: dict):
    return psycopg2.connect(
        host=params["host"],
        port=int(params.get("port", 5432)),
        dbname=params["database"],
        user=params["username"],
        password=params["password"],
        sslmode=params.get("sslmode", "require"),
        connect_timeout=15,
    )


def test_connection(params: dict) -> dict:
    try:
        conn = get_conn(params)
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
        conn.close()
        return {"success": True, "message": f"Connected. {version.split(',')[0]}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def list_schemas(params: dict) -> List[str]:
    conn = get_conn(params)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('information_schema','pg_catalog','pg_toast')
              AND schema_name NOT LIKE 'pg_%'
            ORDER BY schema_name
        """)
        schemas = [r[0] for r in cur.fetchall()]
    conn.close()
    return schemas


def list_tables_fast(params: dict, schema: Optional[str]) -> List[Dict]:
    """One query — returns [{schema, name}] with no column data."""
    conn = get_conn(params)
    conn.set_session(autocommit=True)
    with conn.cursor() as cur:
        if schema:
            schemas = [schema]
        else:
            cur.execute("""
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name NOT IN ('information_schema','pg_catalog','pg_toast')
                  AND schema_name NOT LIKE 'pg_%'
            """)
            schemas = [r[0] for r in cur.fetchall()]

        cur.execute("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = ANY(%s)
              AND table_type IN ('BASE TABLE','VIEW')
            ORDER BY table_schema, table_name
        """, (schemas,))
        rows = cur.fetchall()
    conn.close()
    return [{"schema": r[0], "name": r[1]} for r in rows]


def sample_tables(
    params:      dict,
    tables:      List[Dict],
    on_progress: Optional[Callable[[str, int, int], None]] = None,
) -> List[Dict]:
    """
    Fast path: fetch column names + types only via information_schema.
    No SELECT DISTINCT, no per-column queries.
    Row counts come from pg_class estimates (free).
    """
    if not tables:
        return []

    conn = get_conn(params)
    conn.set_session(autocommit=True)

    schema_list = list({t["schema"] for t in tables})
    name_list   = list({t["name"]   for t in tables})
    wanted      = {(t["schema"], t["name"]) for t in tables}

    with conn.cursor() as cur:
        # All column metadata in one query
        cur.execute("""
            SELECT table_schema, table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = ANY(%s) AND table_name = ANY(%s)
            ORDER BY table_schema, table_name, ordinal_position
        """, (schema_list, name_list))
        col_rows = [r for r in cur.fetchall() if (r[0], r[1]) in wanted]

        # Row count estimates from pg_class (no table scan)
        cur.execute("""
            SELECT n.nspname, c.relname, c.reltuples::bigint
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ANY(%s) AND c.relname = ANY(%s)
        """, (schema_list, name_list))
        row_counts = {(r[0], r[1]): max(int(r[2]), 0) for r in cur.fetchall()}

    conn.close()

    # Group columns by table
    col_map: Dict[tuple, list] = {}
    for tschema, tname, col, dtype in col_rows:
        col_map.setdefault((tschema, tname), []).append({
            "name": col, "data_type": dtype,
            "cardinality": 0, "sample_values": [],
        })

    total  = len(tables)
    result = []
    for i, t in enumerate(tables):
        if on_progress:
            on_progress(f'{t["schema"]}.{t["name"]}', i + 1, total)
        key = (t["schema"], t["name"])
        result.append({
            "schema":    t["schema"],
            "name":      t["name"],
            "row_count": row_counts.get(key, 0),
            "columns":   col_map.get(key, []),
        })

    return result


# Backward-compatible wrapper
def explore_schema(params, schema, on_progress=None):
    tables = list_tables_fast(params, schema)
    return sample_tables(params, tables, on_progress=on_progress)
