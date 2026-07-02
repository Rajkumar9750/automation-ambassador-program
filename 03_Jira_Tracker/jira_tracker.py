import asyncio
import os
import base64
from typing import Optional, List

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "jira_static")
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="Jira Activity Tracker", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class JiraCredentials(BaseModel):
    base_url: str
    email: str        # email for Cloud, username for Server
    api_token: str    # API token for Cloud, PAT for Server
    server_type: str = "cloud"  # "cloud" or "server"


class SearchRequest(BaseModel):
    credentials: JiraCredentials
    jql: str
    max_results: int = 50
    start_at: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_headers(creds: JiraCredentials) -> dict:
    if creds.server_type == "server":
        # Jira Server / Data Center: Personal Access Token (Bearer)
        auth = f"Bearer {creds.api_token}"
    else:
        # Jira Cloud: Basic auth with email:api_token
        auth = "Basic " + base64.b64encode(f"{creds.email}:{creds.api_token}".encode()).decode()
    return {
        "Authorization": auth,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _base(creds: JiraCredentials) -> str:
    return creds.base_url.rstrip("/")

def _api(creds: JiraCredentials) -> str:
    version = "2" if creds.server_type == "server" else "3"
    return f"{_base(creds)}/rest/api/{version}"

def _extract_adf_text(node) -> str:
    """Recursively extract plain text from Atlassian Document Format."""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        parts = [_extract_adf_text(child) for child in node.get("content", [])]
        return " ".join(p for p in parts if p)
    return ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/connect")
async def test_connection(creds: JiraCredentials):
    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.get(
            f"{_api(creds)}/myself",
            headers=_auth_headers(creds),
            timeout=10,
        )
    if resp.status_code == 200:
        data = resp.json()
        return {"ok": True, "display_name": data.get("displayName"), "email": data.get("emailAddress")}
    return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}


@app.post("/api/projects")
async def list_projects(creds: JiraCredentials):
    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.get(
            f"{_api(creds)}/project",
            headers=_auth_headers(creds),
            timeout=15,
        )
    if resp.status_code != 200:
        raise HTTPException(400, detail=f"Jira error: {resp.text[:300]}")
    projects = resp.json()
    return {"projects": [{"key": p["key"], "name": p["name"]} for p in projects]}


@app.post("/api/search")
async def search_issues(req: SearchRequest):
    fields = "summary,status,priority,assignee,duedate,updated,created,reporter,issuetype,labels,comment"
    params = {
        "jql": req.jql,
        "fields": fields,
        "maxResults": req.max_results,
        "startAt": req.start_at,
    }
    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.get(
            f"{_api(req.credentials)}/search/jql",
            headers=_auth_headers(req.credentials),
            params=params,
            timeout=30,
        )
    if resp.status_code != 200:
        raise HTTPException(400, detail=f"Jira error: {resp.text[:300]}")
    data = resp.json()
    issues = []
    for issue in data.get("issues", []):
        f = issue.get("fields", {})
        issues.append({
            "key": issue["key"],
            "summary": f.get("summary", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "status_category": (f.get("status") or {}).get("statusCategory", {}).get("key", ""),
            "priority": (f.get("priority") or {}).get("name", ""),
            "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
            "reporter": (f.get("reporter") or {}).get("displayName", ""),
            "issue_type": (f.get("issuetype") or {}).get("name", ""),
            "labels": f.get("labels", []),
            "created": f.get("created", ""),
            "updated": f.get("updated", ""),
            "due_date": f.get("duedate", ""),
            "comment_count": (f.get("comment") or {}).get("total", 0),
        })
    return {
        "issues": issues,
        "total": data.get("total", 0),
        "start_at": data.get("startAt", 0),
        "max_results": data.get("maxResults", 50),
    }


@app.post("/api/fields/search")
async def search_fields(req: JiraCredentials):
    """Return all custom fields so the frontend can detect 'APAC Assigned Resource'."""
    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.get(
            f"{_api(req)}/field",
            headers=_auth_headers(req),
            timeout=15,
        )
    if resp.status_code != 200:
        raise HTTPException(400, detail=f"Jira error: {resp.text[:300]}")
    fields = resp.json()
    # Return all non-system fields (custom fields) with their key/name/schema
    custom = [
        {
            "id":     f["id"],
            "key":    f.get("key", f["id"]),
            "name":   f["name"],
            "type":   f.get("schema", {}).get("type", ""),
            "custom": f.get("custom", False),
        }
        for f in fields
        if f.get("custom", False)
    ]
    return {"fields": custom}


class CountsRequest(BaseModel):
    base_url: str
    email: str
    api_token: str
    server_type: str = "cloud"
    past_assignments: bool = False
    include_reporter: bool = False
    project: str = ""


@app.post("/api/counts")
async def get_counts(req: CountsRequest):
    creds = JiraCredentials(
        base_url=req.base_url, email=req.email,
        api_token=req.api_token, server_type=req.server_type
    )
    who_parts = ["assignee was currentUser()" if req.past_assignments else "assignee = currentUser()"]
    if req.include_reporter:
        who_parts.append("reporter = currentUser()")
    who = f"({' OR '.join(who_parts)})" if len(who_parts) > 1 else who_parts[0]
    proj = f'AND project = "{req.project}"' if req.project else ""

    queries = {
        "todo":        f'{who} {proj} AND statusCategory = "To Do"',
        "in_progress": f'{who} {proj} AND statusCategory = "In Progress"',
        "done":        f'{who} {proj} AND statusCategory = "Done"',
        "overdue":     f'{who} {proj} AND statusCategory != "Done" AND duedate < now()',
    }
    async with httpx.AsyncClient(verify=False) as client:
        responses = await asyncio.gather(*[
            client.get(
                f"{_api(creds)}/search/jql",
                headers=_auth_headers(creds),
                params={"jql": jql, "maxResults": 0},
                timeout=15,
            )
            for jql in queries.values()
        ])
    counts = {}
    for key, resp in zip(queries.keys(), responses):
        counts[key] = resp.json().get("total", 0) if resp.status_code == 200 else 0
    return counts


@app.post("/api/activity/{issue_key}")
async def get_activity(issue_key: str, creds: JiraCredentials):
    async with httpx.AsyncClient(verify=False) as client:
        changelog_resp, comment_resp = await asyncio.gather(
            client.get(
                f"{_api(creds)}/issue/{issue_key}/changelog",
                headers=_auth_headers(creds),
                timeout=15,
            ),
            client.get(
                f"{_api(creds)}/issue/{issue_key}/comment",
                params={"orderBy": "created"},
                headers=_auth_headers(creds),
                timeout=15,
            ),
        )

    if changelog_resp.status_code == 401 or comment_resp.status_code == 401:
        raise HTTPException(401, detail="Jira returned 401 — check your credentials or token permissions.")

    events = []

    if changelog_resp.status_code == 200:
        # Cloud (v3) returns {values:[...]}, Server (v2) returns {histories:[...]} or {values:[...]}
        cl_data = changelog_resp.json()
        entries = cl_data.get("values") or cl_data.get("histories") or []
        for entry in entries:
            author = (entry.get("author") or {}).get("displayName", "Unknown")
            created = entry.get("created", "")
            for item in entry.get("items", []):
                field = item.get("field", "")
                if field in ("status", "assignee", "priority", "duedate", "summary", "labels"):
                    events.append({
                        "type": "change",
                        "field": field,
                        "from": item.get("fromString", ""),
                        "to": item.get("toString", ""),
                        "author": author,
                        "timestamp": created,
                    })

    if comment_resp.status_code == 200:
        for comment in comment_resp.json().get("comments", []):
            author = (comment.get("author") or {}).get("displayName", "Unknown")
            body = comment.get("body", {})
            # v3 returns ADF dict; v2 returns a plain string
            text = body if isinstance(body, str) else _extract_adf_text(body)
            events.append({
                "type": "comment",
                "text": text,
                "author": author,
                "timestamp": comment.get("created", ""),
            })

    events.sort(key=lambda e: e["timestamp"], reverse=True)
    return {"events": events}


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("jira_tracker:app", host="0.0.0.0", port=8081, reload=True)
