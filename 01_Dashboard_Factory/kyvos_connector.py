"""Kyvos connector via REST API — no ODBC driver required.

Uses the Kyvos Manager REST API instead of pyodbc so this works on Linux
(Docker) or any machine without the proprietary Kyvos ODBC driver installed.

Auth flow (empirically verified against dal.cbre.com):
  1. POST /login with form-encoded username / password / tokenTimeOut=60
     → 200 {"RESPONSE": {"SUCCESS": "<sessionid>"}}
  2. All subsequent calls carry header: sessionid: <token>
  3. Sessions are also cookie-backed (JSESSIONID + AWS ALB stickiness).
     A long-lived httpx.Client is used per operation block so cookies
     persist across the retry sequence.
  4. On first 401 after login: retry with the same sessionid (AWS ALB
     stickiness cookies take a moment to propagate to the backend pod).
  5. On second 401: re-authenticate once and retry.
  6. On third 401: give up — credentials or permissions are invalid.

IMPORTANT — account lockout safety: Kyvos locks accounts on repeated
failed LOGIN attempts. Failed QUERY calls (POST /export/query) are safe
to retry without re-authenticating; only /login failures risk lockout.
"""
from __future__ import annotations

import logging
import threading
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------

def _kyvos_to_tableau_type(kyvos_type: str) -> str:
    """Map a Kyvos column type string to a Tableau local-type string."""
    t = (kyvos_type or "").upper().strip()
    if t in ("INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT", "SHORT"):
        return "integer"
    if t in ("DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC", "NUMBER"):
        return "real"
    if t in ("BOOLEAN", "BOOL", "BIT"):
        return "boolean"
    if "TIMESTAMP" in t or "DATETIME" in t:
        return "datetime"
    if t == "DATE":
        return "date"
    return "string"


# ---------------------------------------------------------------------------
# Internal REST client
# ---------------------------------------------------------------------------

def _build_base_url(host: str, port: int, ssl: bool) -> str:
    """Build the Kyvos Manager REST base URL from connection parameters.

    The REST endpoint lives at /kyvos/rest on the same host as the
    Tableau ODBC endpoint (e.g. dal-pilot.cbre.com → base URL is
    https://dal-pilot.cbre.com/kyvos/rest).
    """
    scheme = "https" if ssl else "http"
    standard_port = (ssl and port == 443) or (not ssl and port == 80)
    if standard_port:
        return f"{scheme}://{host}/kyvos/rest"
    return f"{scheme}://{host}:{port}/kyvos/rest"


class _KyvosClient:
    """Short-lived REST client for one Dashboard Factory API call.

    Always use as a context manager so the underlying httpx.Client is
    closed promptly:

        with _KyvosClient(host, port, username, password, ssl) as c:
            models = c.list_semantic_models("myschema")

    The long-lived httpx.Client inside preserves JSESSIONID cookies across
    the login + catalog/query sequence, which is required by the AWS ALB
    sticky-session setup in front of production Kyvos.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        ssl: bool,
        *,
        timeout: float = 30.0,
    ):
        self.base_url = _build_base_url(host, port, ssl)
        self.username = username
        self.password = password
        self._sessionid: Optional[str] = None
        # Lock prevents concurrent workers (preflight checks) from firing
        # parallel /login calls — Kyvos locks accounts on repeated failures.
        self._auth_lock = threading.Lock()
        self._http = httpx.Client(
            verify=ssl,
            timeout=timeout,
            follow_redirects=False,
        )

    def __enter__(self) -> "_KyvosClient":
        self._authenticate()
        return self

    def __exit__(self, *_) -> None:
        self._http.close()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _authenticate(self) -> None:
        """POST /login. Stores sessionid on success; raises on failure."""
        r = self._http.post(
            f"{self.base_url}/login",
            content=urllib.parse.urlencode({
                "username": self.username,
                "password": self.password,
                # tokenTimeOut is in MINUTES — 60 min covers full retargets
                "tokenTimeOut": "60",
            }).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if r.status_code != 200:
            raise KyvosConnectionError(
                f"Login failed (HTTP {r.status_code}): {r.text[:200]}"
            )
        try:
            sid = r.json()["RESPONSE"]["SUCCESS"]
        except (KeyError, ValueError) as exc:
            raise KyvosConnectionError(
                f"Login response missing RESPONSE.SUCCESS: {r.text[:200]}"
            ) from exc
        self._sessionid = sid
        logger.debug("Kyvos auth OK (sid ***%s)", sid[-6:])

    # ------------------------------------------------------------------
    # HTTP helpers with ALB-stickiness retry
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict] = None) -> dict:
        """GET with 3-tier 401 handling (warmup → re-auth → give up)."""
        url = f"{self.base_url}{path}"
        for attempt in range(3):
            r = self._http.get(
                url,
                params=params or {},
                headers={"sessionid": self._sessionid or "", "Accept": "application/json"},
            )
            if r.status_code == 401:
                if attempt == 0:
                    logger.debug("Kyvos GET 401 (ALB warmup) — retrying same session")
                    continue
                if attempt == 1:
                    logger.debug("Kyvos GET 401 second time — re-authenticating")
                    with self._auth_lock:
                        if not self._sessionid:
                            self._authenticate()
                        else:
                            self._sessionid = None
                            self._authenticate()
                    continue
                raise KyvosConnectionError(
                    f"GET {path}: three consecutive 401s — credentials invalid"
                )
            if r.status_code != 200:
                raise KyvosConnectionError(
                    f"GET {path}: HTTP {r.status_code}: {r.text[:200]}"
                )
            return r.json()
        raise KyvosConnectionError(f"GET {path}: exhausted retries")

    def _query(self, sql: str, max_rows: int = 1, max_columns: int = 1000) -> dict:
        """POST /export/query (form-encoded). Retries on 401/Unauthorized."""
        body = {
            "queryType": "SQL",
            "query": sql,
            "outputFormat": "json",
            "maxRows": str(max_rows),
            "maxColumns": str(max_columns),
            "includeHeader": "true",
            "zipped": "false",
            "keepMeasureFormatting": "false",
        }
        url = f"{self.base_url}/export/query"
        for attempt in range(3):
            r = self._http.post(
                url,
                data=body,
                headers={
                    "sessionid": self._sessionid or "",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            unauthorized = (
                r.status_code == 401 or "Unauthorized access" in r.text
            )
            if unauthorized:
                if attempt == 0:
                    logger.debug("Kyvos query 401 (ALB warmup) — retrying same session")
                    continue
                if attempt == 1:
                    # Retry a QUERY with same session is lockout-safe;
                    # only failed LOGINS lock Kyvos accounts.
                    logger.debug("Kyvos query 401 second time — re-authenticating")
                    with self._auth_lock:
                        self._sessionid = None
                        self._authenticate()
                    continue
                raise KyvosConnectionError(
                    "Query: three consecutive 401s — credentials invalid"
                )
            if r.status_code != 200:
                raise KyvosConnectionError(
                    f"Query failed (HTTP {r.status_code}): {r.text[:200]}"
                )
            return r.json()
        raise KyvosConnectionError("Query: exhausted retries")

    # ------------------------------------------------------------------
    # Catalog operations
    # ------------------------------------------------------------------

    def list_semantic_models(self, folder: str) -> List[Dict[str, str]]:
        """Return all semantic models (cubes) in a Kyvos folder.

        `folder` maps to what Tableau calls `schema` — the catalog name
        assigned to a client (e.g. "bicdemo", "akima", "ametek").

        Only `queryableModelsOnly=false` is sent — adding the optional
        COUNT / fetchProcessedStatus params triggers a 401 on production.
        """
        data = self._get(
            f"/smodels/folder/{folder}",
            params={"queryableModelsOnly": "false"},
        )
        cubes = data.get("RESPONSE", {}).get("CUBES", []) or []
        return [
            {
                "name": c.get("NAME") or "",
                "description": c.get("DESC") or "",
                "owner": c.get("OWNER") or "",
                "last_build_status": c.get("LAST_BUILD_STATUS") or "",
            }
            for c in cubes
            if c.get("NAME")
        ]

    def describe_columns(self, schema: str, cube: str) -> List[Dict[str, str]]:
        """Return column metadata for a cube via SELECT * LIMIT 1.

        Kyvos NPEs on LIMIT 0 — use LIMIT 1 with includeHeader=true
        so we get column metadata without transferring meaningful data.
        Backtick quoting is required; double-quote identifiers 500.
        """
        sql = f"SELECT * FROM `{schema}`.`{cube}` LIMIT 1"
        data = self._query(sql, max_rows=1, max_columns=1000)
        columns = data.get("metadata", {}).get("columns", []) or []
        if not columns:
            raise KyvosConnectionError(
                f"Cube '{cube}' returned no column metadata"
            )
        return [
            {"name": c.get("caption") or "", "type": c.get("type") or ""}
            for c in columns
        ]

    def probe_sql(self, sql: str) -> Dict[str, Any]:
        """Validate arbitrary SQL against Kyvos. Returns {valid, error, columns}."""
        clean = sql.rstrip().rstrip(";")
        probe = f"SELECT * FROM ({clean}) __validate__ LIMIT 1"
        try:
            data = self._query(probe, max_rows=1)
            cols = [
                c.get("caption") or ""
                for c in (data.get("metadata", {}).get("columns", []) or [])
            ]
            return {"valid": True, "error": None, "columns": cols, "column_count": len(cols)}
        except KyvosConnectionError as exc:
            return {"valid": False, "error": str(exc), "columns": [], "column_count": 0}


class KyvosConnectionError(Exception):
    """Wraps any failure surfaced from the Kyvos REST API."""


# ---------------------------------------------------------------------------
# Public API — same signatures as the old pyodbc kyvos_connector so
# app.py needs zero changes.
# ---------------------------------------------------------------------------

def test_connection(
    host: str, port: int, username: str, password: str,
    http_path: str = "kyvos/sql", ssl: bool = True,
) -> Dict:
    """Verify credentials by completing a REST login.

    `http_path` is accepted for backward-compatibility but ignored —
    the REST endpoint path is always /kyvos/rest.
    """
    try:
        with _KyvosClient(host, port, username, password, ssl):
            pass  # __enter__ authenticates; success = credentials valid
        return {
            "success": True,
            "message": "Connected to Kyvos successfully (REST API)",
            "version": "Kyvos REST",
        }
    except (KyvosConnectionError, httpx.HTTPError, OSError) as exc:
        return {"success": False, "message": str(exc)}


def list_schemas(
    host: str, port: int, username: str, password: str,
    http_path: str = "kyvos/sql", ssl: bool = True,
) -> List[str]:
    """Authenticate and return an empty list.

    Kyvos REST has no enumerate-all-folders endpoint. The folder name
    (= schema in Tableau) is a tenant-assigned value the user enters
    manually in the connection form. We still call /login here so the
    UI can surface auth errors early.
    """
    try:
        with _KyvosClient(host, port, username, password, ssl):
            pass
    except (KyvosConnectionError, httpx.HTTPError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc
    return []  # Caller (UI) must prompt user to enter the folder name


def list_tables(
    host: str, port: int, username: str, password: str,
    http_path: str, ssl: bool, schema: str,
) -> List[Dict]:
    """List semantic models in `schema` (= Kyvos folder / tenant catalog)."""
    with _KyvosClient(host, port, username, password, ssl) as c:
        models = c.list_semantic_models(schema)
    return [{"name": m["name"], "type": "TABLE"} for m in models]


def validate_sql(
    host: str, port: int, username: str, password: str,
    http_path: str, ssl: bool, sql: str,
) -> Dict:
    """Validate a SQL query against Kyvos via a LIMIT-1 probe."""
    with _KyvosClient(host, port, username, password, ssl) as c:
        return c.probe_sql(sql)


def check_table_accessible(
    host: str, port: int, username: str, password: str,
    http_path: str, ssl: bool, schema: str, table: str,
) -> Dict:
    """Return {accessible, error} for a cube by describing its columns."""
    try:
        with _KyvosClient(host, port, username, password, ssl) as c:
            c.describe_columns(schema, table)
        return {"accessible": True, "error": None}
    except (KyvosConnectionError, httpx.HTTPError, OSError) as exc:
        return {"accessible": False, "error": str(exc)}


def get_column_types_for_tables(
    host: str, port: int, username: str, password: str,
    http_path: str, ssl: bool, schema: str,
    tables: List[str], extra_schemas: Optional[List[str]] = None,
) -> Dict[str, Dict[str, str]]:
    """Return {table: {column: tableau_type}} for a list of cubes.

    `extra_schemas` is accepted for API compatibility with the postgres
    connector but ignored — all Kyvos cubes share the same `schema` folder.
    """
    result: Dict[str, Dict[str, str]] = {}
    try:
        with _KyvosClient(host, port, username, password, ssl) as c:
            for table in tables:
                try:
                    cols = c.describe_columns(schema, table)
                    result[table] = {
                        col["name"]: _kyvos_to_tableau_type(col["type"])
                        for col in cols
                        if col.get("name")
                    }
                except Exception as exc:
                    logger.warning("get_column_types: skipping cube %r: %s", table, exc)
    except (KyvosConnectionError, httpx.HTTPError, OSError) as exc:
        logger.error("get_column_types: connection failed: %s", exc)
    return result


def list_columns(
    host: str, port: int, username: str, password: str,
    http_path: str, ssl: bool, schema: str, table: str,
) -> List[Dict]:
    """Return [{name, type, nullable}] for every column in a cube."""
    with _KyvosClient(host, port, username, password, ssl) as c:
        cols = c.describe_columns(schema, table)
    return [
        {
            "name": col["name"],
            "type": _kyvos_to_tableau_type(col["type"]),
            "nullable": True,  # Kyvos REST does not expose nullability metadata
        }
        for col in cols
        if col.get("name")
    ]
