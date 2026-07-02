# Automation Ambassador Program – Windows Installer
# Run in PowerShell: Set-ExecutionPolicy Bypass -Scope Process -Force; iex (irm https://raw.githubusercontent.com/Rajkumar9750/automation-ambassador-program/main/install.ps1)

$REPO = "https://github.com/Rajkumar9750/automation-ambassador-program.git"
$DEST = "$HOME\automation-ambassador-program"

Write-Host ""
Write-Host "+==================================================+"
Write-Host "|   Automation Ambassador Program - Installer      |"
Write-Host "+==================================================+"
Write-Host ""

# ── 1. Git ──────────────────────────────────────────────
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

# ── 2. Clone or update ──────────────────────────────────
if (Test-Path "$DEST\.git") {
    Write-Host "► Folder already exists — pulling latest changes..."
    Set-Location $DEST
    git pull
} elseif (Test-Path $DEST) {
    Write-Host "► Incomplete folder found — removing and cloning fresh..."
    Remove-Item -Recurse -Force $DEST
    git clone $REPO $DEST
    Set-Location $DEST
} else {
    Write-Host "► Cloning repository to $DEST..."
    git clone $REPO $DEST
    Set-Location $DEST
}

Write-Host ""

# ── 3. Setup ────────────────────────────────────────────
Write-Host "► Running setup..."
Start-Process -FilePath "cmd.exe" -ArgumentList "/c setup.bat" -Wait -NoNewWindow

Write-Host ""

# ── 4. Launch ───────────────────────────────────────────
Write-Host "► Launching Monitor..."
Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"Launch Monitor.bat`""
