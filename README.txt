╔══════════════════════════════════════════════════════════════╗
║          Automation Ambassador Program                       ║
║          Tool Suite – Getting Started Guide                  ║
╚══════════════════════════════════════════════════════════════╝

WHAT'S INCLUDED
───────────────
  01_Dashboard_Factory/     Tableau workbook generation from Postgres
  02_Dashboard_Factory_QA/  Tableau workbook formatting & QA checks
  03_Jira_Tracker/          Jira activity tracking & timesheet export
  monitor.py / monitor.html Central dashboard to manage all tools


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  macOS INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BEFORE YOU BEGIN (one-time)
  1. Ensure Python 3.9+ is installed:
       Open Terminal → type: python3 --version
       Install from: https://www.python.org/downloads/

HOW TO START
  Step 1 — Right-click "Launch Monitor.command" → click Open
           (macOS security prompt on first launch — click Open)
  Step 2 — Terminal window opens; installs all packages (~2-3 min)
  Step 3 — Browser opens automatically at http://localhost:9000


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WINDOWS INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BEFORE YOU BEGIN (one-time)
  1. Install Python 3.9+ from: https://www.python.org/downloads/
     IMPORTANT: Check "Add Python to PATH" during installation.
  2. Restart your PC after installing Python.

HOW TO START
  Step 1 — Double-click "Launch Monitor.bat"
           (Windows may show a SmartScreen warning →
            click "More info" → "Run anyway")
  Step 2 — Command window opens; installs all packages (~2-3 min)
  Step 3 — Browser opens automatically at http://localhost:9000


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  AFTER THE FIRST RUN (both platforms)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Just double-click the launch file — starts in seconds,
  no reinstall, no warnings.


TOOL PORTS
──────────
  Monitor              →  http://localhost:9000
  Dashboard Factory    →  http://localhost:8080
  Dashboard Factory QA →  http://localhost:5555
  Jira Tracker         →  http://localhost:8082


JIRA CREDENTIALS (Timesheet tool)
──────────────────────────────────
  First time: click "Edit" in the Timesheet card → enter your
  Jira URL, email, and API token → click "Save Credentials".
  Saved locally on your machine only. Never shared.


TROUBLESHOOTING
───────────────
  macOS: "Cannot be opened" error
    → Right-click the .command file → Open (once only)

  Windows: "Python not found" or setup fails
    → Reinstall Python and check "Add Python to PATH"
    → Restart PC, then try again

  Windows: SmartScreen blocks the .bat file
    → Click "More info" → "Run anyway"

  "Address already in use" (port conflict)
    → Another instance is already running
    → Check open Terminal/Command windows or restart your PC

  A tool won't start from the monitor
    → Click the "Logs" button on that tool's card to see the error


IMPORTANT
─────────
  • Requires internet on first run (downloads packages)
  • Do NOT share this folder after entering Jira credentials
    (monitor_config.json stores your saved token locally)
  • Works on macOS and Windows
