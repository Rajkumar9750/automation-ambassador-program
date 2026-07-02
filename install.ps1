# Automation Ambassador Program – Windows Installer
# Run in PowerShell: Set-ExecutionPolicy Bypass -Scope Process -Force; iex (irm https://raw.githubusercontent.com/Rajkumar9750/automation-ambassador-program/main/install.ps1)

$REPO = "https://github.com/Rajkumar9750/automation-ambassador-program.git"
$DEST = "$HOME\automation-ambassador-program"

Write-Host ""
Write-Host "+==================================================+"
Write-Host "|   Automation Ambassador Program - Installer      |"
Write-Host "+==================================================+"
Write-Host ""

# ── 1. Python 3.11 ──────────────────────────────────────
# Force Python 3.11 — 3.12+ breaks pandas and other dependencies
Write-Host "► Ensuring Python 3.11 is installed..."
winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements 2>$null
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")
Write-Host ""

# ── 2. Git ──────────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "► Git not found — installing via winget..."
    winget install --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    # Refresh PATH in this session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Host "  Git was installed but needs a new terminal session to activate."
        Write-Host "  Please close this window, open a new PowerShell, and run:"
        Write-Host "  cd '$DEST' then .\setup.bat"
        Write-Host ""
        # Still try to clone using the full path
        $gitPath = "C:\Program Files\Git\cmd\git.exe"
        if (-not (Test-Path $gitPath)) {
            Write-Host "  Could not find git.exe. Please restart and run install.ps1 again."
            Read-Host "Press Enter to exit"
            exit 1
        }
        Set-Alias git $gitPath
    }
} else {
    Write-Host "✔ Git: $(git --version)"
}

Write-Host ""

# ── 3. Kill any running instances (release file locks) ──
Write-Host "► Stopping any running instances..."
@(9000, 8080, 5555, 8082) | ForEach-Object {
    $port = $_
    try {
        $pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
        $pids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    } catch {}
}
# Also kill any python/uvicorn from the project folder
Get-Process -Name "python","python3","uvicorn" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*automation-ambassador*" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Write-Host ""

# ── 4. Clone or update ──────────────────────────────────
if (Test-Path $DEST) {
    Write-Host "► Removing existing folder and cloning fresh..."
    Remove-Item -Recurse -Force $DEST -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
if (Test-Path $DEST) {
    # Still locked — pull instead
    Write-Host "  (Some files still locked — pulling latest instead)"
    Set-Location $DEST
    git pull
    # Delete old venvs so setup recreates them with Python 3.11
    @("venv","01_Dashboard_Factory\venv","02_Dashboard_Factory_QA\.venv","03_Jira_Tracker\venv") | ForEach-Object {
        $vpath = Join-Path $DEST $_
        if (Test-Path $vpath) { Remove-Item -Recurse -Force $vpath -ErrorAction SilentlyContinue }
    }
} else {
    Write-Host "► Cloning repository to $DEST..."
    git clone $REPO $DEST
    Set-Location $DEST
}
Set-Location $DEST

Write-Host ""

# ── 3. Setup ────────────────────────────────────────────
Write-Host "► Running setup..."
Start-Process -FilePath "cmd.exe" -ArgumentList "/c setup.bat" -Wait -NoNewWindow

Write-Host ""

# ── 4. Launch ───────────────────────────────────────────
Write-Host "► Launching Monitor..."
Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"Launch Monitor.bat`""
