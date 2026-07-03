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

$pyCheck = & python --version 2>&1
$needPython = $pyCheck -notmatch "3\.11"

if ($needPython) {
    # Use the embeddable zip — pure zip extract, no installer EXE, no UAC prompt on any machine
    Write-Host "  Downloading Python 3.11 embeddable package (no admin needed)..."
    $pyDir = "$HOME\python311"
    $pyZip = "$env:TEMP\python311-embed.zip"
    Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip" -OutFile $pyZip
    Expand-Archive -Path $pyZip -DestinationPath $pyDir -Force

    # Uncomment 'import site' so pip-installed packages are importable
    $pthFile = "$pyDir\python311._pth"
    if (Test-Path $pthFile) {
        (Get-Content $pthFile) -replace '#import site','import site' | Set-Content $pthFile
    }

    # Bootstrap pip (downloads a .py file and runs it — no EXE, no UAC)
    Write-Host "  Installing pip..."
    $getPip = "$env:TEMP\get-pip.py"
    Invoke-WebRequest -UseBasicParsing -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
    & "$pyDir\python.exe" $getPip --quiet

    # Embeddable Python has no venv module — install virtualenv as replacement
    Write-Host "  Installing virtualenv..."
    & "$pyDir\python.exe" -m pip install --quiet virtualenv

    # Add to user PATH persistently
    $userPath = [Environment]::GetEnvironmentVariable("Path","User")
    if ($userPath -notlike "*python311*") {
        [Environment]::SetEnvironmentVariable("Path", "$pyDir\Scripts;$pyDir;$userPath", "User")
    }
    $env:Path = "$pyDir\Scripts;$pyDir;$env:Path"
    Write-Host "  ✔ Python 3.11 ready at $pyDir"
}
Write-Host ""

# ── 2. Git ──────────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "► Git not found — downloading PortableGit (no admin needed)..."
    $gitVersion  = "2.49.0"
    $portableUrl = "https://github.com/git-for-windows/git/releases/download/v$gitVersion.windows.1/PortableGit-$gitVersion-64-bit.7z.exe"
    $portableExe = "$env:TEMP\PortableGit.exe"
    $gitDir      = "$HOME\PortableGit"

    Invoke-WebRequest -UseBasicParsing -Uri $portableUrl -OutFile $portableExe
    # 7-zip SFX: -o sets output dir, -y suppresses prompts — no installer, no UAC
    & $portableExe -o"$gitDir" -y | Out-Null
    Start-Sleep -Seconds 8

    $userPath = [Environment]::GetEnvironmentVariable("Path","User")
    if ($userPath -notlike "*PortableGit*") {
        [Environment]::SetEnvironmentVariable("Path", "$gitDir\cmd;$userPath", "User")
    }
    $env:Path = "$gitDir\cmd;$env:Path"
    Write-Host "  ✔ PortableGit ready at $gitDir"
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
