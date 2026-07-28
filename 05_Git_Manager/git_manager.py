"""
05_Git_Manager/git_manager.py
Personal standalone tool — git push with change tracking.
Port 9100  |  Not user-facing.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Git Manager", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE       = Path(__file__).parent
HTML_FILE  = BASE / "git_manager.html"
CHANGE_LOG = BASE / "change_log.json"

# Resolve repo root dynamically (handles symlinks / nested calls)
def _repo() -> Path:
    out, _, _ = _run(["git", "rev-parse", "--show-toplevel"], cwd=BASE)
    return Path(out) if out else BASE.parent


def _run(cmd: list, cwd=None) -> tuple[str, str, int]:
    r = subprocess.run(cmd, cwd=str(cwd or _repo()), capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def _load_log() -> list:
    if CHANGE_LOG.exists():
        try:
            return json.loads(CHANGE_LOG.read_text())
        except Exception:
            return []
    return []


def _save_log(entries: list):
    CHANGE_LOG.write_text(json.dumps(entries, indent=2))


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(HTML_FILE)


@app.get("/api/status")
async def git_status():
    stdout, _, _ = _run(["git", "status", "--porcelain=v1"])
    branch, _, _ = _run(["git", "branch", "--show-current"])
    remote_url, _, _ = _run(["git", "remote", "get-url", "origin"])

    staged, unstaged, untracked = [], [], []
    STATUS = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied", "U": "unmerged"}

    for line in stdout.splitlines():
        if not line:
            continue
        x, y = line[0], line[1]
        path = line[3:]
        if x == "?" and y == "?":
            untracked.append({"path": path, "status": "untracked"})
        else:
            if x not in (" ", "?"):
                staged.append({"path": path, "status": STATUS.get(x, x)})
            if y not in (" ", "?"):
                unstaged.append({"path": path, "status": STATUS.get(y, y)})

    return {
        "branch": branch,
        "remote": remote_url,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
    }


@app.get("/api/diff")
async def diff(path: str = "", staged: bool = False):
    cmd = ["git", "diff"] + (["--cached"] if staged else [])
    if path:
        cmd += ["--", path]
    out, _, _ = _run(cmd)
    return {"diff": out or "(no changes)"}


@app.get("/api/git-log")
async def git_log(limit: int = 30):
    out, _, _ = _run([
        "git", "log", f"--max-count={limit}",
        "--pretty=format:%H|%h|%s|%an|%ai",
    ])
    commits = []
    for line in out.splitlines():
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append({
                "hash": parts[0], "short": parts[1],
                "message": parts[2], "author": parts[3], "date": parts[4],
            })
    return {"commits": commits}


@app.get("/api/change-log")
async def change_log():
    return {"entries": _load_log()}


# ── Write actions ────────────────────────────────────────────────────────────

class PathsRequest(BaseModel):
    paths: list[str] = []


class PushRequest(BaseModel):
    message: str
    paths: list[str] = []   # empty → stage all tracked changes


@app.post("/api/stage")
async def stage(req: PathsRequest):
    targets = req.paths if req.paths else ["-A"]
    for t in targets:
        _, err, code = _run(["git", "add", t])
        if code != 0:
            raise HTTPException(400, detail=f"git add failed for '{t}': {err}")
    return {"ok": True}


@app.post("/api/unstage")
async def unstage(req: PathsRequest):
    targets = req.paths if req.paths else ["."]
    for t in targets:
        _run(["git", "restore", "--staged", t])
    return {"ok": True}


@app.post("/api/push")
async def push(req: PushRequest):
    if not req.message.strip():
        raise HTTPException(400, detail="Commit message cannot be empty.")

    # Stage requested files (or all if none specified)
    targets = req.paths if req.paths else ["-A"]
    for t in targets:
        _, err, code = _run(["git", "add", t])
        if code != 0:
            raise HTTPException(400, detail=f"Staging failed for '{t}': {err}")

    # Verify there is something staged
    staged_names, _, _ = _run(["git", "diff", "--cached", "--name-only"])
    files = [f for f in staged_names.splitlines() if f]
    if not files:
        raise HTTPException(400, detail="Nothing staged to commit.")

    # Collect full diff stat for the log entry
    diff_stat, _, _ = _run(["git", "diff", "--cached", "--stat"])

    # Commit
    _, err, code = _run(["git", "commit", "-m", req.message])
    if code != 0:
        raise HTTPException(400, detail=f"Commit failed: {err}")

    commit_hash, _, _  = _run(["git", "rev-parse", "HEAD"])
    short_hash, _, _   = _run(["git", "rev-parse", "--short", "HEAD"])
    branch, _, _       = _run(["git", "branch", "--show-current"])

    # Push
    _, push_err, push_code = _run(["git", "push", "origin", branch])
    if push_code != 0:
        raise HTTPException(400, detail=f"Push failed: {push_err}")

    # Persist change log entry
    entry = {
        "id": short_hash,
        "hash": commit_hash,
        "timestamp": datetime.now().isoformat(),
        "branch": branch,
        "message": req.message,
        "files": files,
        "files_count": len(files),
        "diff_stat": diff_stat,
    }
    log = _load_log()
    log.insert(0, entry)
    _save_log(log)

    return {"ok": True, "commit": short_hash, "branch": branch, "entry": entry}
