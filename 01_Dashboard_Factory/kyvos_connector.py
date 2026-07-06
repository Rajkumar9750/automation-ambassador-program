import pyodbc
from typing import List, Dict, Any


def _get_conn(host: str, port: int, username: str, password: str,
              http_path: str = "kyvos/sql", ssl: bool = True):
    conn_str = (
        f"Driver={{Kyvos ODBC Driver}};"
        f"Host={host};Port={port};"
        f"HTTPPath={http_path};"
        f"AuthMech=3;"
        f"UID={username};PWD={password};"
        f"SSL={'1' if ssl else '0'};"
        f"Locale=en-US"
    )
    return pyodbc.connect(conn_str, timeout=10)


def test_connection(host: str, port: int, username: str, password: str,
                    http_path: str = "kyvos/sql", ssl: bool = True) -> Dict:
    try:
        conn = _get_conn(host, port, username, password, http_path, ssl)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        conn.close()
        return {"success": True, "message": "Connected to Kyvos successfully", "version": "Kyvos ODBC"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def list_schemas(host: str, port: int, username: str, password: str,
                 http_path: str = "kyvos/sql", ssl: bool = True) -> List[str]:
    conn = _get_conn(host, port, username, password, http_path, ssl)
    try:
        cursor = conn.cursor()
        schemas: set = set()
        for row in cursor.tables():
            schem = row.table_schem
            if schem and schem.lower() not in ("information_schema", "sys", "pg_catalog", "pg_toast"):
                schemas.add(schem)
        return sorted(schemas)
    finally:
        conn.close()


def list_tables(host: str, port: int, username: str, password: str,
                http_path: str, ssl: bool, schema: str) -> List[Dict]:
    conn = _get_conn(host, port, username, password, http_path, ssl)
    try:
        cursor = conn.cursor()
        tables = []
        for row in cursor.tables(schema=schema):
            if row.table_type in ("TABLE", "VIEW"):
                tables.append({"name": row.table_name, "type": row.table_type})
        return tables
    finally:
        conn.close()


def validate_sql(host: str, port: int, username: str, password: str,
                 http_path: str, ssl: bool, sql: str) -> Dict:
    conn = _get_conn(host, port, username, password, http_path, ssl)
    try:
        cursor = conn.cursor()
        clean_sql = sql.rstrip().rstrip(";")
        cursor.execute(f"SELECT * FROM ({clean_sql}) __validate__ LIMIT 0")
        cols = [desc[0] for desc in cursor.description] if cursor.description else []
        return {"valid": True, "error": None, "columns": cols, "column_count": len(cols)}
    except Exception as e:
        return {"valid": False, "error": str(e), "columns": [], "column_count": 0}
    finally:
        conn.close()


def check_table_accessible(host: str, port: int, username: str, password: str,
                            http_path: str, ssl: bool, schema: str, table: str) -> Dict:
    try:
        conn = _get_conn(host, port, username, password, http_path, ssl)
        cursor = conn.cursor()
        cursor.execute(f'SELECT 1 FROM "{schema}"."{table}" LIMIT 0')
        conn.close()
        return {"accessible": True, "error": None}
    except Exception as e:
        return {"accessible": False, "error": str(e)}


def get_column_types_for_tables(
    host: str, port: int, username: str, password: str,
    http_path: str, ssl: bool, schema: str, tables: List[str],
    extra_schemas: List[str] = None,
) -> Dict[str, Dict[str, str]]:
    all_schemas = list({schema} | set(extra_schemas or []))
    try:
        conn = _get_conn(host, port, username, password, http_path, ssl)
        try:
            cursor = conn.cursor()
            result: Dict[str, Dict[str, str]] = {}
            for tbl in tables:
                for sch in all_schemas:
                    for row in cursor.columns(table=tbl, schema=sch):
                        if row.table_name not in result:
                            result[row.table_name] = {}
                        result[row.table_name][row.column_name] = row.type_name
            return result
        finally:
            conn.close()
    except Exception:
        return {}


def list_columns(host: str, port: int, username: str, password: str,
                 http_path: str, ssl: bool, schema: str, table: str) -> List[Dict]:
    conn = _get_conn(host, port, username, password, http_path, ssl)
    try:
        cursor = conn.cursor()
        cols = []
        for row in cursor.columns(table=table, schema=schema):
            cols.append({
                "name": row.column_name,
                "type": row.type_name,
                "nullable": row.nullable == 1,
            })
        return cols
    finally:
        conn.close()
