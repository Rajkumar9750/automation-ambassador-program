import asyncio
import concurrent.futures
import os
import shutil
import tempfile
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from postgres_connector import (
    check_table_accessible as pg_check_table_accessible,
    get_column_types_for_tables as pg_get_column_types_for_tables,
    list_columns as pg_list_columns,
    list_schemas as pg_list_schemas,
    list_tables as pg_list_tables,
    test_connection as pg_test_connection,
    validate_sql as pg_validate_sql,
)
import kyvos_connector as _kyvos
from workbook_generator import generate_twbx, _pg_to_tableau_type
from workbook_parser import parse_column_types_from_metadata, parse_join_tree, parse_twbx

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DEFAULT_WORKBOOK = "/Users/RGaneshan/Downloads/Transaction Management (2).twbx"

for d in (UPLOAD_DIR, OUTPUT_DIR, STATIC_DIR):
    os.makedirs(d, exist_ok=True)

app = FastAPI(title="Dashboard Factory", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory session store  {session_id -> {workbook_path, parsed_info}}
SESSIONS: Dict[str, Dict] = {}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ConnDetails(BaseModel):
    host: str
    port: int = 5432
    database: str = ""
    username: str
    password: str
    sslmode: str = "require"
    conn_type: str = "postgres"        # "postgres" | "kyvos"
    http_path: str = "kyvos/sql"       # Kyvos: HTTP path (e.g. kyvos/sql)
    require_ssl: bool = True           # Kyvos: Require SSL checkbox


# ---------------------------------------------------------------------------
# Connector routing helpers
# ---------------------------------------------------------------------------

def _test_connection(c: "ConnDetails"):
    if c.conn_type == "kyvos":
        return _kyvos.test_connection(c.host, c.port, c.username, c.password, c.http_path, c.require_ssl)
    return pg_test_connection(c.host, c.port, c.database, c.username, c.password, c.sslmode)

def _list_schemas(c: "ConnDetails"):
    if c.conn_type == "kyvos":
        # Kyvos has no enumerate-all-folders REST endpoint.
        # Use the user-supplied catalog/folder as the only schema option.
        if c.database:
            return [c.database]
        # Fall back to auth-check only (returns empty list)
        return _kyvos.list_schemas(c.host, c.port, c.username, c.password, c.http_path, c.require_ssl)
    return pg_list_schemas(c.host, c.port, c.database, c.username, c.password, c.sslmode)

def _list_tables(c: "ConnDetails", schema: str):
    if c.conn_type == "kyvos":
        return _kyvos.list_tables(c.host, c.port, c.username, c.password, c.http_path, c.require_ssl, schema)
    return pg_list_tables(c.host, c.port, c.database, c.username, c.password, c.sslmode, schema)

def _validate_sql(c: "ConnDetails", sql: str):
    if c.conn_type == "kyvos":
        return _kyvos.validate_sql(c.host, c.port, c.username, c.password, c.http_path, c.require_ssl, sql)
    return pg_validate_sql(c.host, c.port, c.database, c.username, c.password, c.sslmode, sql)

def _check_table_accessible(c: "ConnDetails", schema: str, table: str):
    if c.conn_type == "kyvos":
        return _kyvos.check_table_accessible(c.host, c.port, c.username, c.password, c.http_path, c.require_ssl, schema, table)
    return pg_check_table_accessible(c.host, c.port, c.database, c.username, c.password, c.sslmode, schema, table)

def _get_column_types_for_tables(c: "ConnDetails", schema: str, tables: list, extra_schemas: list = None):
    if c.conn_type == "kyvos":
        return _kyvos.get_column_types_for_tables(c.host, c.port, c.username, c.password, c.http_path, c.require_ssl, schema, tables, extra_schemas)
    return pg_get_column_types_for_tables(c.host, c.port, c.database, c.username, c.password, c.sslmode, schema, tables, extra_schemas)

def _list_columns(c: "ConnDetails", schema: str, table: str):
    if c.conn_type == "kyvos":
        return _kyvos.list_columns(c.host, c.port, c.username, c.password, c.http_path, c.require_ssl, schema, table)
    return pg_list_columns(c.host, c.port, c.database, c.username, c.password, c.sslmode, schema, table)


class TableMapping(BaseModel):
    old_schema: str
    old_table: str
    new_schema: str
    new_table: str
    old_connection: Dict[str, Any]
    is_custom_sql: bool = False
    custom_sql_override: Optional[str] = None
    original_sql: Optional[str] = None


class CalcOverride(BaseModel):
    ds_name: str
    field_name: str
    formula: str


class JoinConditionOverride(BaseModel):
    left_table: str
    right_table: str
    left_expr: str            # full Tableau expression — column ref or calculation
    right_expr: str           # full Tableau expression
    join_type: Optional[str] = None   # "inner" | "left" | "right" | "full outer"


class GenerateRequest(BaseModel):
    session_id: str
    client_name: str
    connection: ConnDetails
    table_mappings: List[TableMapping]
    calc_overrides: Optional[List[CalcOverride]] = None
    removed_tables: Optional[List[str]] = None
    join_overrides: Optional[List[JoinConditionOverride]] = None

# ---------------------------------------------------------------------------
# HTML routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

# ---------------------------------------------------------------------------
# Workbook loading
# ---------------------------------------------------------------------------

@app.post("/api/load-default")
async def load_default():
    """Load the bundled reference workbook (Transaction Management.twbx)."""
    if not os.path.exists(DEFAULT_WORKBOOK):
        raise HTTPException(404, detail=f"Default workbook not found at: {DEFAULT_WORKBOOK}")

    session_id = str(uuid.uuid4())
    dest = os.path.join(UPLOAD_DIR, f"{session_id}.twbx")
    shutil.copy(DEFAULT_WORKBOOK, dest)

    try:
        info = parse_twbx(dest)
    except Exception as e:
        os.remove(dest)
        raise HTTPException(422, detail=str(e))

    original_name = os.path.splitext(os.path.basename(DEFAULT_WORKBOOK))[0]
    SESSIONS[session_id] = {"workbook_path": dest, "parsed_info": info, "original_filename": original_name}
    return {"session_id": session_id, "parsed_info": info, "original_filename": original_name}


@app.post("/api/upload")
async def upload_workbook(file: UploadFile = File(...)):
    """Upload a custom .twbx reference workbook."""
    if not file.filename.lower().endswith((".twbx", ".twb")):
        raise HTTPException(400, detail="Only .twbx or .twb files are accepted")

    session_id = str(uuid.uuid4())
    dest = os.path.join(UPLOAD_DIR, f"{session_id}.twbx")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        info = parse_twbx(dest)
    except Exception as e:
        os.remove(dest)
        raise HTTPException(422, detail=str(e))

    original_name = os.path.splitext(file.filename)[0] if file.filename else "Dashboard"
    SESSIONS[session_id] = {"workbook_path": dest, "parsed_info": info, "original_filename": original_name}
    return {"session_id": session_id, "parsed_info": info, "original_filename": original_name}


class FetchFromServerRequest(BaseModel):
    url: str
    email: str
    password: str = ""


# In-memory job store: job_id -> {status, stage, result, error}
FETCH_JOBS: Dict[str, Dict] = {}


@app.post("/api/fetch-from-server")
async def fetch_from_server(req: FetchFromServerRequest):
    """Start a background workbook download and return a job_id for polling."""
    try:
        import requests as _requests
        from tableau_downloader import (
            parse_tableau_url, launch_browser, selenium_login,
            get_tableau_rest_token, download_workbook_rest,
            ui_download_fallback,
        )
    except ImportError as exc:
        raise HTTPException(500, detail=f"Missing dependency: {exc}. "
                            "Run: pip install selenium webdriver-manager requests")

    job_id = str(uuid.uuid4())
    FETCH_JOBS[job_id] = {"status": "running", "stage": "Opening browser…"}

    def _run_download():
        def stage(msg: str):
            FETCH_JOBS[job_id]["stage"] = msg

        try:
            stage("Parsing URL…")
            base_url, site, workbook_id = parse_tableau_url(req.url)
            tmp_dir = Path(tempfile.mkdtemp())

            stage("Opening headless browser…")
            driver = launch_browser(str(tmp_dir), headless=True)
            try:
                stage("Navigating to Tableau Server…")
                selenium_login(driver, req.url, email=req.email,
                               password=req.password, mfa_timeout=90)

                stage("Logged in — obtaining REST token…")
                token, site_id, api_version = None, None, "3.27"
                try:
                    token, site_id, api_version = get_tableau_rest_token(driver, base_url, site)
                except Exception:
                    pass

                def _dl_stage(msg: str):
                    stage(msg)

                if token and site_id:
                    stage("Downloading workbook via REST API…")
                    try:
                        out = download_workbook_rest(base_url, site_id, workbook_id,
                                                     token, tmp_dir, api_version)
                        twbx_path = str(out)
                    except Exception:
                        stage("REST download failed — trying browser UI…")
                        found = ui_download_fallback(driver, base_url, workbook_id, tmp_dir,
                                                     on_progress=_dl_stage)
                        twbx_path = str(found) if found else None
                else:
                    stage("Downloading workbook via browser UI…")
                    found = ui_download_fallback(driver, base_url, workbook_id, tmp_dir,
                                                 on_progress=_dl_stage)
                    twbx_path = str(found) if found else None

                # Last-resort scan: check tmp_dir and ~/Downloads
                if twbx_path is None:
                    search_dirs = [tmp_dir, Path.home() / "Downloads"]
                    for d in search_dirs:
                        for f in (d.iterdir() if d.is_dir() else []):
                            if f.is_file() and f.suffix.lower() in (".twbx", ".twb"):
                                twbx_path = str(f)
                                break
                        if twbx_path:
                            break
                if not twbx_path:
                    raise RuntimeError("Download finished but no .twbx file found.")
            finally:
                driver.quit()

            stage("Parsing workbook…")
            session_id = str(uuid.uuid4())
            dest = os.path.join(UPLOAD_DIR, f"{session_id}.twbx")
            shutil.copy(twbx_path, dest)
            shutil.rmtree(os.path.dirname(twbx_path), ignore_errors=True)

            info = parse_twbx(dest)
            original_name = os.path.splitext(os.path.basename(twbx_path))[0]
            SESSIONS[session_id] = {"workbook_path": dest, "parsed_info": info,
                                    "original_filename": original_name}
            FETCH_JOBS[job_id] = {
                "status": "done",
                "stage": "Complete",
                "result": {"session_id": session_id, "parsed_info": info,
                           "original_filename": original_name},
            }
        except Exception as e:
            FETCH_JOBS[job_id] = {"status": "error", "stage": "Failed",
                                  "error": str(e)}

    concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(_run_download)
    return {"job_id": job_id}


@app.get("/api/health")
async def health():
    """Quick dependency check — hit this to diagnose 500 errors on /api/fetch-from-server."""
    results = {}
    for pkg in ("selenium", "webdriver_manager", "requests"):
        try:
            __import__(pkg)
            results[pkg] = "ok"
        except ImportError as e:
            results[pkg] = f"MISSING: {e}"
    try:
        from tableau_downloader import parse_tableau_url  # noqa: F401
        results["tableau_downloader"] = "ok"
    except Exception as e:
        results["tableau_downloader"] = f"ERROR: {e}"
    return results


@app.get("/api/fetch-status/{job_id}")
async def fetch_status(job_id: str):
    if job_id not in FETCH_JOBS:
        raise HTTPException(404, detail="Job not found")
    return FETCH_JOBS[job_id]


# ---------------------------------------------------------------------------
# Database connectivity
# ---------------------------------------------------------------------------

@app.post("/api/db/test")
async def db_test(conn: ConnDetails):
    return _test_connection(conn)


@app.post("/api/db/schemas")
async def db_schemas(conn: ConnDetails):
    try:
        schemas = _list_schemas(conn)
        return {"schemas": schemas}
    except Exception as e:
        raise HTTPException(400, detail=str(e))


@app.post("/api/db/tables/{schema}")
async def db_tables(schema: str, conn: ConnDetails):
    try:
        tables = _list_tables(conn, schema)
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(400, detail=str(e))


class ValidateSQLRequest(BaseModel):
    sql: str
    connection: ConnDetails

def _normalize_tableau_sql(sql: str) -> str:
    """Convert Tableau's double-operator escaping back to standard SQL for PostgreSQL."""
    import re as _re
    sql = sql.replace("<<=", "<=").replace(">>=", ">=")
    sql = _re.sub(r'<<(?!=)', "<", sql)
    sql = _re.sub(r'>>(?!=)', ">", sql)
    return sql


@app.post("/api/db/validate-sql")
async def db_validate_sql(req: ValidateSQLRequest):
    try:
        return _validate_sql(req.connection, _normalize_tableau_sql(req.sql))
    except Exception as e:
        return {"valid": False, "error": str(e), "columns": [], "column_count": 0}


@app.post("/api/db/columns/{schema}/{table}")
async def db_columns(schema: str, table: str, conn: ConnDetails):
    try:
        cols = _list_columns(conn, schema, table)
        return {"columns": cols}
    except Exception as e:
        raise HTTPException(400, detail=str(e))

# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------

class PreflightRequest(BaseModel):
    connection: ConnDetails
    table_mappings: List[TableMapping]


@app.post("/api/preflight")
async def preflight_check(req: PreflightRequest):
    """
    Validate every table mapping and custom-SQL query against the target DB.
    Returns {ok, issues} where each issue has: index, type, label, target,
    root_cause, fix, similar_tables (for table_not_found).
    """
    issues = []
    c = req.connection

    for i, m in enumerate(req.table_mappings):
        label = f"{m.old_schema}.{m.old_table}" if m.old_schema else m.old_table or f"mapping #{i+1}"

        if m.is_custom_sql:
            sql = (m.custom_sql_override or "").strip()
            if not sql and m.original_sql:
                # Auto-substitute old_schema → new_schema so we can validate the SQL
                import re as _re
                sql = m.original_sql
                if m.old_schema and m.new_schema:
                    sql = _re.sub(rf'\b{_re.escape(m.old_schema)}\.', f'{m.new_schema}.', sql)

            if sql:
                res = _validate_sql(c, sql)
                if not res["valid"]:
                    issues.append({
                        "index": i,
                        "type": "sql_error",
                        "label": label,
                        "target": label,
                        "root_cause": res["error"] or "Unknown SQL error",
                        "similar_tables": [],
                        "fix": "Open the SQL editor for this mapping and correct the query.",
                    })
        else:
            res = _check_table_accessible(c, m.new_schema, m.new_table)
            if not res["accessible"]:
                similar: list = []
                try:
                    all_tables = _list_tables(c, m.new_schema)
                    nt = m.new_table.lower()
                    similar = [
                        t["name"] for t in all_tables
                        if nt in t["name"].lower() or t["name"].lower() in nt
                    ][:5]
                except Exception:
                    pass

                issues.append({
                    "index": i,
                    "type": "table_not_found",
                    "label": label,
                    "target": f"{m.new_schema}.{m.new_table}",
                    "root_cause": res["error"] or "Table not found or not accessible",
                    "similar_tables": similar,
                    "fix": (
                        f"Table '{m.new_schema}.{m.new_table}' could not be queried. "
                        + (f"Similar tables: {', '.join(similar)}." if similar else "Check schema and table name.")
                    ),
                })

    return {"ok": len(issues) == 0, "issues": issues}


@app.get("/api/table-columns/{session_id}")
async def table_column_names(session_id: str):
    """Return column names per table extracted from the reference workbook metadata-records."""
    if session_id not in SESSIONS:
        raise HTTPException(404, detail="Session not found")
    session = SESSIONS[session_id]
    try:
        with zipfile.ZipFile(session["workbook_path"], "r") as z:
            twb_file = next(f for f in z.namelist() if f.endswith(".twb"))
            content = z.read(twb_file).decode("utf-8", errors="replace")
        col_types = parse_column_types_from_metadata(content)
        columns = {table: sorted(cols.keys()) for table, cols in col_types.items()}
        return {"columns": columns}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/api/data-model/{session_id}")
async def data_model(session_id: str):
    """Return the join tree / data model from the reference workbook."""
    if session_id not in SESSIONS:
        raise HTTPException(404, detail="Session not found")
    session = SESSIONS[session_id]
    try:
        with zipfile.ZipFile(session["workbook_path"], "r") as z:
            twb_file = next(f for f in z.namelist() if f.endswith(".twb"))
            content = z.read(twb_file).decode("utf-8", errors="replace")
        return parse_join_tree(content)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ---------------------------------------------------------------------------
# Workbook generation
# ---------------------------------------------------------------------------

@app.post("/api/generate")
async def generate(req: GenerateRequest):
    if req.session_id not in SESSIONS:
        raise HTTPException(404, detail="Session expired. Please reload the reference workbook.")

    session = SESSIONS[req.session_id]
    safe_client   = "".join(c if c.isalnum() or c in "-_" else "_" for c in req.client_name).strip("_")
    safe_db       = "".join(c if c.isalnum() or c in "-_" else "_" for c in req.connection.database).strip("_")
    raw_wb_name   = session.get("original_filename", "Dashboard")
    safe_wb_name  = "".join(c if c.isalnum() or c in "-_" else "_" for c in raw_wb_name).strip("_")
    # Skip database name if it duplicates the client name
    db_part = safe_db if safe_db.lower() != safe_client.lower() else ""
    parts = [p for p in [safe_client, db_part, safe_wb_name] if p]
    output_filename = "_".join(parts) + ".twbx"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    loop = asyncio.get_event_loop()

    def _blocking_generate():
        # ── Type mismatch detection ──────────────────────────────────────────
        type_fixes = []
        client_col_types: Dict[str, Dict[str, str]] = {}
        try:
            with zipfile.ZipFile(session["workbook_path"], "r") as z:
                twb_file = next(f for f in z.namelist() if f.endswith(".twb"))
                ref_content = z.read(twb_file).decode("utf-8", errors="replace")
            ref_col_types = parse_column_types_from_metadata(ref_content)

            non_sql_mappings = [m for m in req.table_mappings if not m.is_custom_sql]
            if non_sql_mappings:
                new_tables  = [m.new_table  for m in non_sql_mappings]
                all_schemas = list({m.new_schema for m in non_sql_mappings if m.new_schema})
                c = req.connection
                client_col_types = _get_column_types_for_tables(
                    c,
                    all_schemas[0] if all_schemas else "",
                    new_tables,
                    extra_schemas=all_schemas[1:],
                )
                if ref_col_types:
                    for m in non_sql_mappings:
                        ref_cols   = ref_col_types.get(m.old_table, {})
                        client_cols = client_col_types.get(m.new_table, {})
                        for col_name, ref_type in ref_cols.items():
                            pg_type = client_cols.get(col_name)
                            if pg_type is None:
                                continue
                            db_type = _pg_to_tableau_type(pg_type)
                            if db_type != ref_type:
                                type_fixes.append({
                                    "column":   col_name,
                                    "old_type": db_type,
                                    "new_type": ref_type,
                                    "pg_type":  pg_type,
                                })
        except Exception as _e:
            print(f"  [type-fix] column-type lookup failed: {_e}")

        _, repair_log = generate_twbx(
            source_twbx=session["workbook_path"],
            client_name=req.client_name,
            new_connection=req.connection.dict(),
            table_mappings=[m.dict() for m in req.table_mappings],
            output_path=output_path,
            calc_overrides=[c.dict() for c in req.calc_overrides] if req.calc_overrides else [],
            type_fixes=type_fixes,
            removed_tables=req.removed_tables or [],
            join_overrides=[j.dict() for j in req.join_overrides] if req.join_overrides else [],
            client_col_types=client_col_types,
        )

        return repair_log

    try:
        repair_log = await loop.run_in_executor(None, _blocking_generate)
    except Exception as e:
        raise HTTPException(500, detail=f"Generation failed: {e}")

    # Persist mappings so the extract endpoint can re-run generate_twbx
    session = SESSIONS[req.session_id]
    session["last_table_mappings"]   = [m.dict() for m in req.table_mappings]
    session["last_calc_overrides"]   = [c.dict() for c in req.calc_overrides] if req.calc_overrides else []
    session["last_removed_tables"]   = req.removed_tables or []
    session["last_join_overrides"]   = [j.dict() for j in req.join_overrides] if req.join_overrides else []

    return {
        "download_url": f"/api/download/{output_filename}",
        "filename": output_filename,
        "repair_log": repair_log,
    }


@app.get("/api/download/{filename}")
async def download(filename: str):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, detail="Generated file not found")
    return FileResponse(path, media_type="application/octet-stream", filename=filename)


# ---------------------------------------------------------------------------
# Extract endpoint — embeds .hyper files into the generated workbook
# ---------------------------------------------------------------------------

class ExtractRequest(BaseModel):
    session_id: str
    filename: str
    connection: ConnDetails


def _sanitise_extract_block(extract_block: str) -> str:
    """
    Prepare the injected <extract> block for a multi-table hyper file.

    Two issues from copying the reference block verbatim:
    1. schema='Extract' tablename='Extract' on the <connection class='hyper'> tells
       Tableau to look for a single Extract.Extract table.  Our hyper has multiple
       named tables, so Tableau can't find that table and falls back to live,
       triggering a new extract.  Strip both attributes.
    2. dbname must start with './' so Tableau resolves it relative to the temp dir
       where the .twbx is unpacked.
    """
    import re

    def _fix_hyper_conn(m: "re.Match") -> str:
        tag = m.group(0)
        tag = re.sub(r"\s+schema='[^']*'", "", tag)
        tag = re.sub(r"\s+tablename='[^']*'", "", tag)
        # Ensure dbname starts with ./
        tag = re.sub(
            r"(dbname=')(?!\./)",
            r"\1./",
            tag,
        )
        return tag

    return re.sub(r"<connection\b[^>]*class='hyper'[^>]*>", _fix_hyper_conn, extract_block)


def _inject_extract_blocks(gen_twb: str, ref_twb: str) -> str:
    """Copy <extract> blocks from the reference TWB into the generated TWB.

    Tableau enforces strict element ordering inside <datasource>. The <extract>
    element must appear before <layout> and <style> — inserting at end of the
    datasource block causes schema validation errors (D2E8DA72).
    """
    import re

    # Collect extract blocks from reference, keyed by datasource name
    ref_extracts: Dict[str, str] = {}
    for m in re.finditer(r"<datasource\b([^>]*)>", ref_twb):
        name_m = re.search(r"name='([^']*)'", m.group(1))
        if not name_m:
            continue
        ds_name = name_m.group(1)
        ds_start = m.start()
        ds_end = ref_twb.find("</datasource>", ds_start)
        if ds_end == -1:
            continue
        block = ref_twb[ds_start:ds_end + len("</datasource>")]
        ext_m = re.search(r"<extract\b.*?</extract>", block, re.DOTALL)
        if ext_m:
            ref_extracts[ds_name] = _sanitise_extract_block(ext_m.group(0))

    if not ref_extracts:
        return gen_twb

    result = gen_twb
    for ds_name, extract_block in ref_extracts.items():
        # Find the datasource block in the generated TWB
        ds_pat = re.compile(
            r"<datasource\b[^>]*name='" + re.escape(ds_name) + r"'[^>]*>.*?</datasource>",
            re.DOTALL,
        )
        ds_m = ds_pat.search(result)
        if not ds_m:
            continue

        ds_block = ds_m.group(0)

        # Insert before <layout>, <style>, or </datasource> — whichever comes first.
        # This preserves the element ordering Tableau requires.
        anchor = re.search(r"<layout\b|<style\b|</datasource>", ds_block)
        if anchor:
            insert_pos = ds_m.start() + anchor.start()
            result = result[:insert_pos] + extract_block + "\n" + result[insert_pos:]

    return result


@app.post("/api/extract")
async def build_extract(req: ExtractRequest):
    if req.session_id not in SESSIONS:
        raise HTTPException(404, detail="Session expired. Please reload the reference workbook.")

    session = SESSIONS[req.session_id]
    generated_path = os.path.join(OUTPUT_DIR, req.filename)
    if not os.path.exists(generated_path):
        raise HTTPException(404, detail="Generated workbook not found. Please generate first.")

    loop = asyncio.get_event_loop()

    def _blocking_extract():
        from extract_builder import build_extracts

        pg_params = {
            "host":     req.connection.host,
            "port":     req.connection.port,
            "database": req.connection.database,
            "username": req.connection.username,
            "password": req.connection.password,
            "sslmode":  req.connection.sslmode,
        }

        base = req.filename.replace(".twbx", "")
        extract_filename = f"{base}_extract.twbx"
        extract_path = os.path.join(OUTPUT_DIR, extract_filename)

        # Re-run generate_twbx with preserve_extract=True so the <extract> block
        # stays in its original position (where Tableau placed it) rather than being
        # re-injected by regex. The old .hyper files are kept in the ZIP as placeholders;
        # build_extracts() will overwrite them in-place with fresh data.
        from workbook_generator import generate_twbx as _gen

        # Rebuild the same mappings used in the original generate call.
        # We read them from the already-generated .twbx TWB + session data.
        with zipfile.ZipFile(generated_path) as z:
            twb_name = next(f for f in z.namelist() if f.endswith(".twb"))
            gen_twb_content = z.read(twb_name).decode("utf-8", errors="replace")

        # generate_twbx writes to a file; use a temp path then rebuild hypers on top
        with tempfile.TemporaryDirectory() as tmp_gen:
            interim_path = os.path.join(tmp_gen, "interim.twbx")
            _gen(
                source_twbx=session["workbook_path"],
                client_name=req.session_id,          # placeholder, not used in output
                new_connection=pg_params,
                table_mappings=session.get("last_table_mappings", []),
                output_path=interim_path,
                calc_overrides=session.get("last_calc_overrides", []),
                type_fixes=[],
                removed_tables=session.get("last_removed_tables", []),
                join_overrides=session.get("last_join_overrides", []),
                preserve_extract=True,
            )

            # Now read the interim TWB (has extract block preserved) and build hypers
            with zipfile.ZipFile(interim_path) as z:
                twb_name = next(f for f in z.namelist() if f.endswith(".twb"))
                interim_twb = z.read(twb_name).decode("utf-8", errors="replace")
                all_items = {name: z.read(name) for name in z.namelist()}

            extracts_dir = os.path.join(tmp_gen, "extracts")
            os.makedirs(extracts_dir, exist_ok=True)
            modified_twb, repair_log = build_extracts(interim_twb, pg_params, extracts_dir)

            # Collect hyper paths referenced in TWB so we use the exact dbname paths
            import re as _re
            hyper_refs = _re.findall(r"dbname='([^']*\.hyper)'", modified_twb)

            with zipfile.ZipFile(extract_path, "w", zipfile.ZIP_DEFLATED) as dst:
                for name, data in all_items.items():
                    if name.endswith(".twb"):
                        dst.writestr(name, modified_twb.encode("utf-8"))
                    elif name.endswith(".hyper"):
                        pass   # replaced below with fresh hypers
                    else:
                        dst.writestr(name, data)

                for hyper_file in os.listdir(extracts_dir):
                    if not hyper_file.endswith(".hyper"):
                        continue
                    src_path = os.path.join(extracts_dir, hyper_file)
                    # Use exact dbname path from TWB so Tableau can locate the file
                    zip_path = next(
                        (r for r in hyper_refs if r.endswith(hyper_file)),
                        f"Data/Extracts/{hyper_file}",
                    )
                    dst.write(src_path, zip_path)

        return extract_filename, repair_log

    try:
        extract_filename, repair_log = await loop.run_in_executor(None, _blocking_extract)
    except Exception as e:
        raise HTTPException(500, detail=f"Extract build failed: {e}")

    return {
        "download_url": f"/api/download/{extract_filename}",
        "filename": extract_filename,
        "repair_log": repair_log,
    }

# ---------------------------------------------------------------------------
# Static files (mounted last so it doesn't shadow API routes)
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
