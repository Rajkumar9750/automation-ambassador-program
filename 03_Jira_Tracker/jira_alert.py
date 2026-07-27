import asyncio
import base64
import json
import os
import sys
from datetime import date, datetime, timedelta

import httpx
import schedule
import time

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "alert_config.json")

PRIORITY_COLOR = {
    "Highest": "FF0000",
    "High":    "FF6600",
    "Medium":  "FFC000",
    "Low":     "00B0F0",
    "Lowest":  "808080",
}

PRIORITY_EMOJI = {
    "Highest": "🔴",
    "High":    "🟠",
    "Medium":  "🟡",
    "Low":     "🔵",
    "Lowest":  "⚪",
}


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Config file not found: {CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


# ── Jira ──────────────────────────────────────────────────────────────────────

def _auth_headers(cfg: dict) -> dict:
    j = cfg["jira"]
    if j.get("server_type", "cloud") == "server":
        auth = f"Bearer {j['api_token']}"
    else:
        token = base64.b64encode(f"{j['email']}:{j['api_token']}".encode()).decode()
        auth = f"Basic {token}"
    return {
        "Authorization":  auth,
        "Accept":         "application/json",
        "Content-Type":   "application/json",
    }

def _api_base(cfg: dict) -> str:
    j = cfg["jira"]
    version = "2" if j.get("server_type") == "server" else "3"
    return f"{j['base_url'].rstrip('/')}/rest/api/{version}"


def _parse_issue(issue: dict, cfg: dict) -> dict:
    f = issue.get("fields", {})
    return {
        "key":      issue["key"],
        "summary":  f.get("summary", ""),
        "due_date": f.get("duedate", ""),
        "priority": (f.get("priority") or {}).get("name", "Unknown"),
        "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
        "status":   (f.get("status") or {}).get("name", ""),
        "url":      f"{cfg['jira']['base_url'].rstrip('/')}/browse/{issue['key']}",
    }


async def _jql_search(cfg: dict, jql: str) -> list:
    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.get(
            f"{_api_base(cfg)}/search/jql",
            headers=_auth_headers(cfg),
            params={"jql": jql, "fields": "summary,duedate,priority,assignee,status", "maxResults": 200},
            timeout=30,
        )
    if resp.status_code != 200:
        print(f"[ERROR] Jira API {resp.status_code}: {resp.text[:300]}")
        return []
    return [_parse_issue(i, cfg) for i in resp.json().get("issues", [])]


def _proj_jql(cfg: dict) -> str:
    projects = cfg["jira"].get("projects") or ([cfg["jira"]["project"]] if cfg["jira"].get("project") else [])
    if not projects:
        return ""
    keys = ", ".join(projects)
    return f"AND project in ({keys})"


async def fetch_due_tickets(cfg: dict) -> list:
    today     = date.today()
    due_limit = today + timedelta(days=cfg["alert"].get("due_soon_days", 2))
    jql = (
        f'statusCategory != Done {_proj_jql(cfg)} '
        f'AND due <= "{due_limit.strftime("%Y-%m-%d")}" '
        f'ORDER BY due ASC, priority ASC'
    )
    return await _jql_search(cfg, jql)


async def fetch_priority_tickets(cfg: dict) -> list:
    levels   = cfg["alert"].get("priority_levels", ["Highest", "High"])
    pri_list = ", ".join(f'"{p}"' for p in levels)
    jql = (
        f'statusCategory != Done {_proj_jql(cfg)} '
        f'AND priority in ({pri_list}) '
        f'ORDER BY priority ASC, created ASC'
    )
    return await _jql_search(cfg, jql)


def categorise(issues: list, due_soon_days: int) -> tuple[list, list]:
    today    = date.today()
    overdue  = []
    due_soon = []
    for issue in issues:
        due_str = issue.get("due_date")
        if not due_str:
            continue
        due_date = datetime.strptime(due_str, "%Y-%m-%d").date()
        issue["_due_date"] = due_date
        if due_date < today:
            overdue.append(issue)
        elif due_date <= today + timedelta(days=due_soon_days):
            due_soon.append(issue)
    return overdue, due_soon


# ── Teams message builder ─────────────────────────────────────────────────────

def _build_due_rows(issues: list) -> str:
    rows  = []
    today = date.today()
    for t in issues:
        due     = t["_due_date"]
        diff    = (due - today).days
        due_lbl = f"Due in {diff}d ({due})" if diff >= 0 else f"Overdue by {abs(diff)}d ({due})"
        emoji   = PRIORITY_EMOJI.get(t["priority"], "⚪")
        summary = t["summary"][:70] + ("…" if len(t["summary"]) > 70 else "")
        rows.append(
            f"  • [{t['key']}]({t['url']}) {summary}\n"
            f"    {emoji} {t['priority']} | 👤 {t['assignee']} | 📅 {due_lbl}"
        )
    return "\n".join(rows)


def _build_priority_rows(issues: list) -> str:
    rows = []
    for t in issues:
        emoji   = PRIORITY_EMOJI.get(t["priority"], "⚪")
        summary = t["summary"][:70] + ("…" if len(t["summary"]) > 70 else "")
        due_lbl = f"📅 {t['due_date']}" if t.get("due_date") else "📅 No due date"
        rows.append(
            f"  • [{t['key']}]({t['url']}) {summary}\n"
            f"    {emoji} {t['priority']} | 👤 {t['assignee']} | 🔖 {t['status']} | {due_lbl}"
        )
    return "\n".join(rows)


def build_teams_payload(overdue: list, due_soon: list, high_priority: list, cfg: dict) -> dict:
    today_str  = date.today().strftime("%d %b %Y")
    projects   = cfg["jira"].get("projects") or ([cfg["jira"]["project"]] if cfg["jira"].get("project") else ["All"])
    proj_label = ", ".join(projects)
    parts      = [f"📋 **Jira Alert — {today_str}** (Projects: {proj_label})\n"]

    if overdue:
        parts.append(f"🚨 **PAST DUE — {len(overdue)} ticket(s)**\n{_build_due_rows(overdue)}")

    if due_soon:
        days = cfg["alert"].get("due_soon_days", 2)
        parts.append(f"⚠️ **DUE IN < {days} DAYS — {len(due_soon)} ticket(s)**\n{_build_due_rows(due_soon)}")

    if high_priority:
        levels = " / ".join(cfg["alert"].get("priority_levels", ["Highest", "High"]))
        parts.append(f"🔥 **{levels} PRIORITY — {len(high_priority)} open ticket(s)**\n{_build_priority_rows(high_priority)}")

    return {"text": "\n\n".join(parts)}


async def send_teams_alert(payload: dict, webhook_url: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json=payload, timeout=15)
    if resp.status_code in (200, 204):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Alert sent to Teams.")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Teams error {resp.status_code}: {resp.text[:200]}")


# ── Main run ──────────────────────────────────────────────────────────────────

async def run_alert() -> None:
    cfg     = load_config()
    webhook = cfg["teams"]["webhook_url"]

    if "your-org" in webhook or webhook.endswith("..."):
        print("[ERROR] Set your Teams webhook URL in alert_config.json before running.")
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching Jira tickets…")

    due_issues, priority_issues = await asyncio.gather(
        fetch_due_tickets(cfg),
        fetch_priority_tickets(cfg),
    )

    due_soon_days         = cfg["alert"].get("due_soon_days", 2)
    overdue, due_soon     = categorise(due_issues, due_soon_days)

    # Exclude tickets already in overdue/due_soon from priority list to avoid duplicates
    due_keys              = {t["key"] for t in overdue + due_soon}
    high_priority         = [t for t in priority_issues if t["key"] not in due_keys]

    print(f"  → {len(overdue)} overdue | {len(due_soon)} due soon | {len(high_priority)} high priority")

    if not overdue and not due_soon and not high_priority:
        print("  → No alerts to send.")
        return

    payload = build_teams_payload(overdue, due_soon, high_priority, cfg)
    await send_teams_alert(payload, webhook)


def run() -> None:
    asyncio.run(run_alert())


# ── Scheduler ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg      = load_config()
    interval = cfg["alert"].get("schedule_interval", "daily")
    sched_t  = cfg["alert"].get("schedule_time", "09:00")

    print(f"Jira Alert Scheduler starting…")
    print(f"  Schedule : {interval} at {sched_t}")
    print(f"  Project  : {cfg['jira'].get('project', '(all)')}")
    print(f"  Due-soon : within {cfg['alert'].get('due_soon_days', 2)} day(s)")
    print()

    run()  # fire immediately on start

    if interval == "hourly":
        schedule.every().hour.do(run)
    else:
        schedule.every().day.at(sched_t).do(run)

    while True:
        schedule.run_pending()
        time.sleep(30)
