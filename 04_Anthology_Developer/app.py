"""
Anthology Developer — FastAPI server.
Upload a Tableau workbook → detect domain → map its tables to client DB using Claude.
"""

import json
import os
import shutil
import uuid
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from workbook_extractor import extract_tables
from schema_sampler import list_tables_fast, sample_tables, test_connection, list_schemas
from domain_detector import detect_domain, filter_target_tables
from llm_matcher import match_tables, to_dashboard_factory_export

# ---------------------------------------------------------------------------
BASE_DIR   = Path(__file__).parent

# Read API key from environment so the UI field can be pre-filled / optional
_ENV_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"
for d in (UPLOAD_DIR, OUTPUT_DIR, STATIC_DIR):
    d.mkdir(exist_ok=True)

app = FastAPI(title="Anthology Developer", version="2.1.0")

SESSIONS: Dict[str, dict] = {}
JOBS:     Dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DBParams(BaseModel):
    host:     str
    port:     int  = 5432
    database: str
    username: str
    password: str
    sslmode:  str  = "require"
    schema:   Optional[str] = None


class TestConnRequest(BaseModel):
    target: DBParams


class DiscoverRequest(BaseModel):
    session_id:   str
    target:       DBParams
    alias_prefix: Optional[str] = None   # user-confirmed prefix (e.g. "fm_")


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def get_config():
    """Tell the frontend whether a server-side API key is available."""
    return {"has_server_key": bool(_ENV_API_KEY)}


# ---------------------------------------------------------------------------
# Workbook upload + domain detection
# ---------------------------------------------------------------------------

@app.post("/api/upload-workbook")
async def upload_workbook(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".twbx", ".twb")):
        raise HTTPException(400, detail="Only .twbx or .twb files are accepted.")

    session_id = str(uuid.uuid4())
    dest = UPLOAD_DIR / f"{session_id}{Path(file.filename).suffix.lower()}"

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        tables   = extract_tables(str(dest))
        filename = file.filename
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, detail=f"Could not parse workbook: {e}")

    SESSIONS[session_id] = {
        "workbook_path": str(dest),
        "tables":        tables,
        "filename":      filename,
    }

    table_names = [t["table"] for t in tables]
    ds_names    = []   # extracted later if needed

    return {
        "session_id":  session_id,
        "filename":    filename,
        "table_count": len(tables),
        "tables":      [{"schema": t["schema"], "table": t["table"],
                         "is_custom_sql": t["is_custom_sql"]} for t in tables],
        "table_names": table_names,
    }


@app.post("/api/detect-domain")
async def detect_domain_endpoint(req: dict):
    """
    Detect dashboard domain from workbook metadata.
    Body: {session_id}
    Returns: {domain, alias_prefix, confidence, reasoning}
    """
    sid = req.get("session_id", "")

    if sid not in SESSIONS:
        raise HTTPException(404, detail="Session not found")

    session = SESSIONS[sid]
    tables  = session["tables"]

    result = detect_domain(
        workbook_name=session["filename"],
        table_names=[t["table"] for t in tables],
        ds_names=[],
    )
    return result


# ---------------------------------------------------------------------------
# DB connectivity
# ---------------------------------------------------------------------------

@app.post("/api/connections/test")
async def test_conn(req: TestConnRequest):
    return {"target": test_connection(req.target.dict())}


@app.post("/api/db/schemas")
async def db_schemas(params: DBParams):
    try:
        return {"schemas": list_schemas(params.dict())}
    except Exception as e:
        raise HTTPException(400, detail=str(e))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

@app.post("/api/discover")
async def start_discovery(req: DiscoverRequest):
    if req.session_id not in SESSIONS:
        raise HTTPException(404, detail="Session not found. Please re-upload the workbook.")

    session   = SESSIONS[req.session_id]
    wb_tables = session["tables"]
    job_id    = str(uuid.uuid4())
    JOBS[job_id] = {"status": "running", "stage": "Starting…", "progress": 0.0,
                    "alias_prefix": req.alias_prefix or ""}

    def _run():
        def upd(stage: str, pct: float):
            JOBS[job_id]["stage"]    = stage
            JOBS[job_id]["progress"] = round(pct, 2)

        try:
            alias = (req.alias_prefix or "").strip()

            # 1. List ALL table names fast (no sampling yet)
            upd("Connecting to Target DB…", 0.02)
            all_table_names = list_tables_fast(req.target.dict(), req.target.schema)
            upd(f"{len(all_table_names)} tables found in target DB", 0.12)

            # 2. Filter by alias prefix BEFORE any expensive sampling
            if alias:
                filtered_names = filter_target_tables(all_table_names, alias)
                upd(f'Filtered to {len(filtered_names)} "{alias}*" tables — now sampling…', 0.17)
            else:
                filtered_names = all_table_names
                upd(f"No prefix filter — sampling all {len(all_table_names)} tables…", 0.17)

            # 3. Sample ONLY the filtered tables
            tgt_tables = sample_tables(
                req.target.dict(),
                filtered_names,
                on_progress=lambda s, i, n: upd(f"Sampling {s.split('.')[-1]}", 0.18 + 0.42 * i / max(n, 1)),
            )
            upd(f"Sampled {len(tgt_tables)} tables", 0.61)

            # 4. LLM matching
            upd("Claude is analysing schemas…", 0.63)
            results = match_tables(
                wb_tables,
                tgt_tables,
                on_progress=lambda s, i, n: upd(s, 0.63 + 0.35 * i / max(n, 1)),
            )

            JOBS[job_id] = {
                "status":   "done",
                "stage":    "Complete",
                "progress": 1.0,
                "alias_prefix": alias,
                "result": {
                    "results":          results,
                    "workbook_tables":   len(wb_tables),
                    "target_tables":     len(tgt_tables),
                    "all_target_tables": len(all_table_names),
                    "alias_prefix":     alias,
                    "filename":         session["filename"],
                },
            }

        except Exception as e:
            JOBS[job_id] = {
                "status": "error", "stage": "Failed",
                "progress": 0.0, "error": str(e),
            }

    concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(_run)
    return {"job_id": job_id}


@app.get("/api/discover/status/{job_id}")
async def discover_status(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, detail="Job not found")
    j = JOBS[job_id]
    return {"status": j["status"], "stage": j["stage"],
            "progress": j["progress"], "error": j.get("error")}


@app.get("/api/results/{job_id}")
async def get_results(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, detail="Job not found")
    j = JOBS[job_id]
    if j["status"] == "running": raise HTTPException(425, detail="Still running")
    if j["status"] == "error":   raise HTTPException(500, detail=j.get("error"))
    return j["result"]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class ExportRequest(BaseModel):
    job_id:   str
    tgt_conn: dict


@app.post("/api/export/{job_id}")
async def export_mappings(job_id: str, req: ExportRequest):
    if job_id not in JOBS:
        raise HTTPException(404, detail="Job not found")
    j = JOBS[job_id]
    if j["status"] != "done":
        raise HTTPException(400, detail="Job not complete")

    export   = to_dashboard_factory_export(j["result"]["results"], req.tgt_conn)
    filename = f"anthology_{job_id[:8]}.json"
    out_path = OUTPUT_DIR / filename
    with open(out_path, "w") as f:
        json.dump(export, f, indent=2)

    return {
        "download_url":  f"/api/download/{filename}",
        "filename":      filename,
        "mapping_count": export["mapping_count"],
        "skipped_count": export["skipped_count"],
    }


@app.get("/api/download/{filename}")
async def download(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, detail="File not found")
    return FileResponse(str(path), media_type="application/json", filename=filename)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8083, reload=True)
