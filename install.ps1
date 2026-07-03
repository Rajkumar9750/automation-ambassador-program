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
# --scope user installs for current user only — no admin/UAC required
winget install --id Python.Python.3.11 --scope user --silent --accept-package-agreements --accept-source-agreements 2>$null
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")

# If winget user-scope failed, fall back to pyenv-win (fully no-admin)
$py311 = Get-Command python3.11 -ErrorAction SilentlyContinue
if (-not $py311) {
    $pyCheck = & python --version 2>&1
    if ($pyCheck -notmatch "3\.11") {
        Write-Host "  winget failed — installing Python 3.11 via pyenv-win (no admin needed)..."
        Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/pyenv-win/pyenv-win/master/pyenv-win/install-pyenv-win.ps1" -OutFile "$env:TEMP\install-pyenv-win.ps1"
        & "$env:TEMP\install-pyenv-win.ps1"
        $env:PYENV = "$HOME\.pyenv\pyenv-win"
        $env:Path  = "$env:PYENV\bin;$env:PYENV\shims;$env:Path"
        pyenv install 3.11.9 --quiet
        pyenv global 3.11.9
        $env:Path = "$HOME\.pyenv\pyenv-win\shims;$env:Path"
    }
}
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
# Use taskkill — most reliable way to force-kill on Windows
cmd /c "taskkill /F /IM python.exe /T >nul 2>&1"
cmd /c "taskkill /F /IM python3.exe /T >nul 2>&1"
cmd /c "taskkill /F /IM uvicorn.exe /T >nul 2>&1"
Start-Sleep -Seconds 3
Write-Host ""

# ── 4. Clone fresh ──────────────────────────────────────
if (Test-Path $DEST) {
    Write-Host "► Removing existing folder..."
    Remove-Item -Recurse -Force $DEST -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}
if (Test-Path $DEST) {
    # Last resort — rename old folder and clone fresh
    $OLD = "$DEST-old-$(Get-Random)"
    Write-Host "  Still locked — moving to $OLD and cloning fresh..."
    Rename-Item -Path $DEST -NewName $OLD -ErrorAction SilentlyContinue
}
Write-Host "► Cloning repository to $DEST..."
git clone $REPO $DEST
Set-Location $DEST

Write-Host ""

# ── 3. Setup ────────────────────────────────────────────
Write-Host "► Running setup..."
Start-Process -FilePath "cmd.exe" -ArgumentList "/c setup.bat" -Wait -NoNewWindow

Write-Host ""

# ── 4. Launch ───────────────────────────────────────────
Write-Host "► Launching Monitor..."
Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"Launch Monitor.bat`""
