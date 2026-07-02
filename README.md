# Automation Ambassador Program

A centralized tool suite for the CBRE Automation Ambassador team.
One launcher opens a browser dashboard where you start, stop, and monitor all tools.

---

## What's Included

| Tool | Port | Description |
|---|---|---|
| **Monitor** | 9000 | Central dashboard — manage all tools from one place |
| **Dashboard Factory** | 8080 | Generate Tableau workbooks from Postgres |
| **Dashboard Factory QA** | 5555 | Tableau workbook formatting & QA compliance checks |
| **Jira Tracker** | 8082 | View Jira tickets & export timesheets to Excel |

---

## First-Time Setup

### Prerequisites
- Git installed → [git-scm.com](https://git-scm.com/downloads)
- That's it — Python is installed automatically by the setup script

---

### macOS

Open **Terminal** and run:

```bash
git clone https://github.com/Rajkumar9750/automation-ambassador-program.git
cd automation-ambassador-program
bash setup.sh
```

Setup will:
1. Check for Python 3.9+ — installs it via Homebrew automatically if missing
2. Create virtual environments for all 4 tools
3. Install all dependencies

Then launch:
```
Right-click "Launch Monitor.command" → Open
(macOS security prompt on first launch — click Open)
```

Browser opens automatically at **http://localhost:9000**

---

### Windows

Open **Command Prompt** and run:

```bat
git clone https://github.com/Rajkumar9750/automation-ambassador-program.git
cd automation-ambassador-program
setup.bat
```

Setup will:
1. Check for Python 3.9+ — installs it via **winget** automatically if missing
2. Create virtual environments for all 4 tools
3. Install all dependencies

Then launch:
```
Double-click "Launch Monitor.bat"
If Windows SmartScreen appears → click "More info" → "Run anyway"
```

Browser opens automatically at **http://localhost:9000**

---

## Getting Updates

Whenever a teammate pushes a change, pull it with:

```bash
cd automation-ambassador-program
git pull
```

No need to re-run setup unless new dependencies were added.

---

## Using the Monitor (http://localhost:9000)

The monitor is your control centre for all tools.

### Starting / Stopping a Tool
- Click **Start** on any tool card to launch it
- Click **Stop** to shut it down
- Click **Open** to open the tool in a new browser tab
- Click **Logs** to see live output from that tool

### Tool Status Indicators
| Status | Meaning |
|---|---|
| 🟢 Running | Tool is up and responding |
| 🟡 Starting | Process launched, waiting for it to be ready |
| 🔴 Stopped | Tool is not running |

---

## Tool Guides

### Dashboard Factory (port 8080)
Generates Tableau workbooks from a Postgres database connection.

1. Start the tool from the Monitor
2. Click **Open** to go to http://localhost:8080
3. Enter your Postgres connection details
4. Select the fields and layout you need
5. Click **Generate** — downloads the `.twbx` workbook

---

### Dashboard Factory QA (port 5555)
Checks and auto-fixes formatting issues in Tableau workbooks.

1. Start the tool from the Monitor
2. Click **Open** to go to http://localhost:5555
3. Upload a `.twbx` file
4. Review the compliance checks
5. Apply fixes and download the corrected workbook

---

### Jira Tracker (port 8082)
View your active Jira tickets and export timesheet reports.

1. Start the tool from the Monitor
2. Click **Open** to go to http://localhost:8082
3. Enter your Jira credentials (URL, email, API token)
4. Your tickets load automatically

**To get a Jira API Token:**
- Jira Cloud: go to https://id.atlassian.com/manage-profile/security/api-tokens → Create API token
- Jira Server: Profile → Personal Access Tokens → Create token

---

### Calculated Fields Extractor (in Monitor)
Extracts all calculated fields from a Tableau workbook into an Excel report — no need to open Tableau.

1. Go to the Monitor at http://localhost:9000
2. Scroll to the **Calculated Fields Extractor** card
3. Drag and drop a `.twbx` file onto the upload area (or click to browse)
4. Click **Extract** — downloads an Excel file with all calculated fields

---

### Timesheet Report (in Monitor)
Generates an Excel timesheet based on your Jira comment activity. Project Code and Activity Code are looked up automatically from the client list.

1. Go to the Monitor at http://localhost:9000
2. Scroll to the **Timesheet Report** card
3. First time: click **Edit** and enter your Jira credentials → **Save**
4. Select **Monthly** or **Full Year**
5. Pick the month/year
6. Click **Generate** — downloads an Excel file with:
   - Ticket #, Category, Summary, Reporter
   - Project Code & Activity Code (looked up by client name)
   - Due Date, Start Date, End Date

---

## Troubleshooting

### macOS: "Cannot be opened because it is from an unidentified developer"
Right-click the `.command` file → **Open** → click **Open** in the prompt.
Only needed once.

### Windows: SmartScreen blocks the `.bat` file
Click **More info** → **Run anyway**.

### A tool shows "Failed to stop" or HTTP 500
This is fixed in the current version. Make sure you have the latest code:
```bash
git pull
```

### Tool won't start — shows error in Logs
Click the **Logs** button on the tool card to see the exact error.
Most common cause: run `bash setup.sh` again to reinstall dependencies.

### "Address already in use" on a port
Another instance of that tool is already running.
Either stop it from the Monitor, or restart your computer.

### Python not found after setup
Close the terminal, open a new one, and run the setup script again.
The PATH update takes effect in new terminal sessions.

---

## Pushing Updates (for maintainers)

After making changes to any file:

```bash
cd automation-ambassador-program
git add -A
git commit -m "describe what changed"
git push
```

Teammates pull the update with:
```bash
git pull
```

---

## Notes
- `monitor_config.json` stores your saved Jira credentials **locally only** — it is excluded from Git via `.gitignore` and never shared
- `Detail.xlsx` contains the client → Project Code / Activity Code mapping used by the Timesheet Report
- All virtual environments (`venv/`, `.venv/`) are excluded from Git — they are created fresh on each machine by `setup.sh`
