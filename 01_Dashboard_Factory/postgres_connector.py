import psycopg2
from typing import List, Dict, Any


def _get_conn(host: str, port: int, database: str, username: str, password: str, sslmode: str = "require"):
    ssl = "disable" if sslmode in ("none", "disable") else sslmode
    return psycopg2.connect(
        host=host,
        port=int(port),
        dbname=database,
        user=username,
        password=password,
        sslmode=ssl,
        connect_timeout=10,
    )


def test_connection(host: str, port: int, database: str, username: str, password: str, sslmode: str = "require") -> Dict:
    try:
        conn = _get_conn(host, port, database, username, password, sslmode)
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
        conn.close()
        return {"success": True, "message": "Connected successfully", "version": version}
    except Exception as e:
        return {"success": False, "message": str(e)}


def list_schemas(host: str, port: int, database: str, username: str, password: str, sslmode: str = "require") -> List[str]:
    conn = _get_conn(host, port, database, username, password, sslmode)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
                  AND schema_name NOT LIKE 'pg_%'
                ORDER BY schema_name
            """)
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def list_tables(host: str, port: int, database: str, username: str, password: str, sslmode: str, schema: str) -> List[Dict]:
    conn = _get_conn(host, port, database, username, password, sslmode)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = %s
                ORDER BY table_type, table_name
            """, (schema,))
            return [{"name": row[0], "type": "VIEW" if row[1] == "VIEW" else "TABLE"} for row in cur.fetchall()]
    finally:
        conn.close()


def validate_sql(host: str, port: int, database: str, username: str, password: str, sslmode: str, sql: str) -> Dict:
    """
    Validate a SQL query by wrapping it in SELECT * FROM (...) LIMIT 0.
    Returns {valid, error, row_description} without fetching any rows.
    """
    conn = _get_conn(host, port, database, username, password, sslmode)
    try:
        with conn.cursor() as cur:
            clean_sql = sql.rstrip().rstrip(";")
            cur.execute(f"SELECT * FROM ({clean_sql}) __validate__ LIMIT 0")
            cols = [desc[0] for desc in cur.description] if cur.description else []
        return {"valid": True, "error": None, "columns": cols, "column_count": len(cols)}
    except Exception as e:
        return {"valid": False, "error": str(e), "columns": [], "column_count": 0}
    finally:
        conn.close()


def check_table_accessible(host: str, port: int, database: str, username: str, password: str, sslmode: str, schema: str, table: str) -> Dict:
    try:
        conn = _get_conn(host, port, database, username, password, sslmode)
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM "{}"."{}" LIMIT 0'.format(schema, table))
        conn.close()
        return {"accessible": True, "error": None}
    except Exception as e:
        return {"accessible": False, "error": str(e)}


def get_column_types_for_tables(
    host: str, port: int, database: str, username: str, password: str,
    sslmode: str, schema: str, tables: List[str],
    extra_schemas: List[str] = None,
) -> Dict[str, Dict[str, str]]:
    """
    Returns {table_name: {column_name: pg_data_type}} for the given tables.
    Queries all schemas in `extra_schemas` (plus `schema`) so multi-schema
    workbooks are handled correctly.
    """
    all_schemas = list({schema} | set(extra_schemas or []))
    try:
        conn = _get_conn(host, port, database, username, password, sslmode)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = ANY(%s) AND table_name = ANY(%s)
                    ORDER BY table_name, ordinal_position
                    """,
                    (all_schemas, tables),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return {}

    result: Dict[str, Dict[str, str]] = {}
    for table_name, column_name, data_type in rows:
        if table_name not in result:
            result[table_name] = {}
        result[table_name][column_name] = data_type
    return result


def list_columns(host: str, port: int, database: str, username: str, password: str, sslmode: str, schema: str, table: str) -> List[Dict]:
    conn = _get_conn(host, port, database, username, password, sslmode)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table))
            return [{"name": row[0], "type": row[1], "nullable": row[2] == "YES"} for row in cur.fetchall()]
    finally:
        conn.close()
