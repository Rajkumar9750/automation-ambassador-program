# Automation Ambassador Program

A centralized tool suite for the CBRE Automation Ambassador team.
One launcher starts a browser dashboard where you control all tools from a single place.

---

## Contents

- [What's Included](#whats-included)
- [Installation](#installation)
  - [macOS](#macos)
  - [Windows](#windows)
- [Launching the Monitor](#launching-the-monitor)
- [Monitor Dashboard](#monitor-dashboard)
- [Tool — Dashboard Factory](#tool--dashboard-factory)
- [Tool — Dashboard Factory QA](#tool--dashboard-factory-qa)
- [Tool — Jira Tracker](#tool--jira-tracker)
- [Utility — Calculated Fields Extractor](#utility--calculated-fields-extractor)
- [Utility — Timesheet Report](#utility--timesheet-report)
- [Getting Updates](#getting-updates)
- [For Maintainers](#for-maintainers)
- [Troubleshooting](#troubleshooting)

---

## What's Included

| Tool | Port | Description |
|---|---|---|
| **Monitor** | 9000 | Central dashboard — start, stop and monitor all tools |
| **Dashboard Factory** | 8080 | Generate Tableau workbooks from a Postgres database |
| **Dashboard Factory QA** | 5555 | Auto-fix formatting & run QA compliance checks on Tableau workbooks |
| **Jira Tracker** | 8082 | View your Jira tickets and export timesheet reports to Excel |

---

## Installation

Paste the commands for your OS into a terminal. Git and Python install automatically if missing.

---

### macOS

Open **Terminal** (`Cmd + Space` → type `Terminal` → Enter) and run these commands one by one:

```bash
# 1. Install Git and Python via Homebrew (skips if already installed)
command -v brew &>/dev/null || /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install git python@3.11 2>/dev/null || true

# 2. Clone the repository (enter your GitHub username + token when prompted)
git clone https://github.com/Rajkumar9750/automation-ambassador-program.git ~/automation-ambassador-program

# 3. Run setup
cd ~/automation-ambassador-program && bash setup.sh

# 4. Launch the monitor
bash "Launch Monitor.command"
```

Browser opens automatically at **http://localhost:9000**

> Takes **2–5 minutes** on first run. You will only need to do this once.

---

### Windows

Open **PowerShell** (`Win + R` → type `powershell` → Enter) and run these commands one by one:

```powershell
# 1. Install Git (skips if already installed)
winget install --id Git.Git --silent --accept-package-agreements --accept-source-agreements

# 2. Install Python 3.11 (skips if already installed)
winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements

# 3. Refresh PATH so git and python are available in this session
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# 4. Clone the repository (enter your GitHub username + token when prompted)
git clone https://github.com/Rajkumar9750/automation-ambassador-program.git "$HOME\automation-ambassador-program"

# 5. Run setup
cd "$HOME\automation-ambassador-program"; cmd /c setup.bat
```

Then launch:
```powershell
# 6. Launch the monitor
cd "$HOME\automation-ambassador-program"; cmd /c "Launch Monitor.bat"
```

Browser opens automatically at **http://localhost:9000**

> Takes **2–5 minutes** on first run. You will only need to do this once.

---

### GitHub Credentials (required for cloning)

The repository is private — you will be asked for credentials when running the `git clone` step.

- **Username:** your GitHub username
- **Password:** a Personal Access Token (GitHub no longer accepts your account password)

**To create a token:**
1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Click **Generate new token (classic)**
3. Give it a name, tick the **`repo`** scope → **Generate**
4. Copy the token — paste it as the password when `git clone` prompts you

---

---

## Launching the Monitor

After setup is complete, start the monitor to access all tools.

**macOS** — Double-click **`Launch Monitor.command`** in Finder.

**Windows** — Double-click **`Launch Monitor.bat`**.

> **macOS security note:** If you see *"cannot be opened because it is from an unidentified developer"*, this only happens when the folder is downloaded as a ZIP from GitHub. Since you cloned via `git clone` in Terminal, double-click works directly with no prompts.

> **Windows security note:** If Windows SmartScreen appears, click **More info** → **Run anyway**.

A terminal window opens and the browser launches automatically at **http://localhost:9000**.

To stop everything, close the terminal window or press `Ctrl + C` inside it.

---

## Monitor Dashboard

The monitor at **http://localhost:9000** is the central control panel for all tools.

### Tool Cards

Each tool has its own card showing:

| Element | Description |
|---|---|
| **Status badge** | 🟢 Running · 🟡 Starting · 🔴 Stopped |
| **Uptime** | How long the tool has been running |
| **Start button** | Launches the tool |
| **Stop button** | Shuts the tool down |
| **Open button** | Opens the tool in a new browser tab (only active when running) |
| **Logs button** | Shows live stdout/stderr output from the tool |

### How to Start a Tool
1. Find the tool card on the monitor page
2. Click **Start** — status changes to 🟡 Starting
3. Wait a few seconds — status changes to 🟢 Running
4. Click **Open** to use the tool

### How to Stop a Tool
1. Click **Stop** on the tool card
2. Status changes to 🔴 Stopped

### Viewing Logs
Click **Logs** on any managed tool to see its live output. Useful for diagnosing errors.
Click **▾ Hide logs** to collapse the log panel.

---

## Tool — Dashboard Factory

**URL:** http://localhost:8080

Generates Tableau `.twbx` workbooks from a Postgres database.

### How to use
1. Start **Dashboard Factory** from the Monitor and click **Open**
2. Enter your Postgres connection details (host, port, database, username, password)
3. Select the tables and fields you want in the workbook
4. Configure the layout and dashboard settings
5. Click **Generate** — the `.twbx` file downloads automatically

---

## Tool — Dashboard Factory QA

**URL:** http://localhost:5555

Checks Tableau workbooks for formatting issues and compliance, then applies automatic fixes.

### How to use
1. Start **Dashboard Factory QA** from the Monitor and click **Open**
2. Upload a `.twbx` file using the file picker
3. The tool runs compliance checks and shows results
4. Review the findings — issues are listed with descriptions
5. Click to apply fixes
6. Download the corrected workbook

---

## Tool — Jira Tracker

**URL:** http://localhost:8082

View your Jira tickets across active, completed, overdue, and all views. Filter by project, sort by different fields, and drill into ticket activity.

### Connecting to Jira

**First time only:**
1. Start **Jira Tracker** from the Monitor and click **Open**
2. Select your Jira type:
   - **Cloud** — your Jira URL ends in `.atlassian.net`
   - **Server / Data Center** — self-hosted Jira instance
3. Enter your **Jira Base URL** (e.g. `https://yourcompany.atlassian.net`)
4. Enter your **Email**
5. Enter your **API Token** (see below)
6. Click **Connect**

### Getting a Jira API Token

**Jira Cloud:**
1. Go to [id.atlassian.com](https://id.atlassian.com) → **Security** → **API tokens**
2. Click **Create API token**
3. Give it a name (e.g. `Automation Ambassador`) → **Create**
4. Copy the token — **you cannot see it again after closing the dialog**

**Jira Server / Data Center:**
1. Log into your Jira instance → click your profile picture → **Profile**
2. Go to **Personal Access Tokens** in the left sidebar
3. Click **Create token**, set a name and expiry → **Create**
4. Copy the token

> Your credentials are stored locally on your machine only. They are never uploaded to GitHub or shared with anyone.

### Ticket Views

| View | Shows |
|---|---|
| **Active** | To Do + In Progress tickets |
| **Completed** | Resolved / Done tickets |
| **Overdue** | Tickets past their due date |
| **All Mine** | Every ticket assigned to or reported by you |

### Filters & Sorting
- **Project** — filter to a specific Jira project
- **Sort** — Due Date, Last Updated, Priority, or Created date
- **Past assignments** — include tickets previously assigned to you
- **Include reported by me** — include tickets you created/reported

### Ticket Details
Click any ticket row to expand its **Activity** and **Details** panel, showing comments, status changes, and full field values.

---

## Utility — Calculated Fields Extractor

Located directly on the Monitor page at **http://localhost:9000**.

Extracts all calculated fields from a Tableau workbook and exports them to a formatted Excel file — no need to open Tableau.

### How to use
1. Go to the Monitor at http://localhost:9000
2. Scroll to the **Calculated Fields Extractor** card under **Utility Tools**
3. Drag and drop a `.twbx` file onto the upload area — or click to browse
4. The extraction runs automatically
5. Click **⬇ Download Excel** to save the report

The Excel file lists every calculated field in the workbook with its name, formula, and the datasource it belongs to.

---

## Utility — Timesheet Report

Located directly on the Monitor page at **http://localhost:9000**.

Generates a formatted Excel timesheet based on your Jira comment activity. The client name is read from each ticket's summary (text before the `|`), and the Project Code and Activity Code are looked up automatically from the client list.

### Setting Up Credentials (first time only)
1. Scroll to the **Timesheet Report** card on the Monitor
2. Click **Edit**
3. Enter your Jira URL, email, API token, and server type
4. Click **💾 Save Credentials**

Credentials are saved locally and reused for every future report — you only enter them once.

### Generating a Monthly Timesheet
1. Select **Month** under Scope
2. Choose the month and year
3. Click **Generate**
4. The Excel file downloads as `Timesheet_MonthName_YYYY.xlsx`

### Generating a Full-Year Consolidated Timesheet
1. Select **Year** under Scope
2. Choose the year
3. Click **Generate**
4. The Excel file downloads as `Timesheet_Consolidated_YYYY.xlsx`
   - Contains an **All Months** tab with all tickets across the year
   - Plus individual tabs for each month that had activity

### What the Timesheet Contains

Each row is a ticket you commented on during the selected period.

| Column | Description |
|---|---|
| Ticket # | Jira ticket key (e.g. BACS-123), hyperlinked to Jira |
| Category | Issue type (Bug, Task, Story, etc.) |
| Summary | Ticket title |
| Reporter | Who raised the ticket |
| Project Code | Looked up from client name in the ticket summary |
| Activity Code | Looked up based on Jira project (e.g. ONGOING_SUPPORT) |
| Due Date | Ticket due date |
| Start Date | First date you commented on this ticket in the period |
| End Date | Last date you commented on this ticket in the period |

---

## Getting Updates

When a teammate pushes a change, pull it in Terminal:

```bash
cd automation-ambassador-program
git pull
```

Then restart the monitor (close the terminal window and double-click `Launch Monitor.command` / `Launch Monitor.bat` again).

No need to re-run `setup.sh` / `setup.bat` unless new dependencies were added.

---

## For Maintainers

After making any changes, push them to GitHub:

```bash
cd automation-ambassador-program
git add -A
git commit -m "describe what changed"
git push
```

Teammates pull the update with `git pull`.

### Updating the Client List (Detail.xlsx)

The `Detail.xlsx` file in the project root maps client names to Project Codes and Activity Codes used in the Timesheet Report. To update it:

1. Replace `Detail.xlsx` in the project folder with the new version
2. Commit and push:
```bash
git add Detail.xlsx
git commit -m "Update client list"
git push
```

---

## Troubleshooting

### macOS: "Cannot be opened" security warning
Only happens when the folder is downloaded as a ZIP instead of cloned via `git clone`.
**Fix:** Right-click `Launch Monitor.command` → **Open** → **Open**. One time only.

### Windows: SmartScreen warning
Click **More info** → **Run anyway**. One time only.

### A tool won't start
Click the **Logs** button on that tool's card to see the exact error.
Then run setup again to reinstall dependencies:
```bash
bash setup.sh   # macOS
setup.bat       # Windows
```

### "Address already in use" error
Another instance of that tool is already running. Stop it from the Monitor, or restart your computer.

### Python not found after setup completes
Close the terminal, open a new one, and run `bash setup.sh` again. PATH changes take effect in new terminal sessions.

### Timesheet shows empty Project Code / Activity Code
The client name in the ticket summary must match a client name in `Detail.xlsx`.
The tool reads the text before the `|` in the ticket summary (e.g. `Adobe | Issue title` → looks up `Adobe`).
If the client is missing from `Detail.xlsx`, ask a maintainer to add it.

### Jira credentials rejected (401 error)
- Make sure you are using an **API token**, not your Jira password
- For Jira Cloud, the token must come from [id.atlassian.com](https://id.atlassian.com)
- Check that the **Jira Type** (Cloud vs Server) matches your instance

---

## Security Notes

- `monitor_config.json` — stores your Jira credentials locally. Excluded from Git via `.gitignore`. Never shared.
- `Detail.xlsx` — contains client and project code data. Included in the repo. Do not put sensitive data in this file.
- All virtual environments (`venv/`, `.venv/`) — excluded from Git. Recreated locally by setup.
