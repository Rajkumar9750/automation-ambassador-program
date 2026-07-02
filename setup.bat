@echo off
cd /d "%~dp0"
title Automation Ambassador Program - Setup

echo.
echo +==================================================+
echo ^|   Automation Ambassador Program - Setup          ^|
echo +==================================================+
echo.

:: -------------------------------------------------------
:: 1. Ensure Git is installed (needed for future git pull)
:: -------------------------------------------------------

where git >nul 2>&1
if %errorlevel% neq 0 (
    echo   Git not found. Installing via winget...
    where winget >nul 2>&1
    if %errorlevel%==0 (
        winget install --id Git.Git --silent --accept-package-agreements --accept-source-agreements
        echo   Git installed. You may need to close and reopen this window for git to work.
    ) else (
        echo   winget not available. Install Git manually from https://git-scm.com/downloads
    )
) else (
    for /f "tokens=*" %%i in ('git --version') do echo   Git: %%i
)
echo.

:: -------------------------------------------------------
:: 2. Find or install Python 3.9+
:: -------------------------------------------------------

set PYTHON=
call :find_python
if defined PYTHON goto :python_found

echo   Python 3.9+ not found. Attempting auto-install...
echo.

:: Try winget (available on Windows 10 1709+ and Windows 11)
where winget >nul 2>&1
if %errorlevel%==0 (
    echo   Installing Python 3.11 via winget...
    winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if %errorlevel%==0 (
        echo   Python installed. Refreshing PATH...
        :: Refresh PATH so python is available in this session
        for /f "tokens=*" %%i in ('where python 2^>nul') do set PYTHON=%%i
        call :find_python
        goto :python_found
    )
)

:: Try chocolatey
where choco >nul 2>&1
if %errorlevel%==0 (
    echo   Installing Python 3.11 via Chocolatey...
    choco install python311 -y
    call :find_python
    goto :python_found
)

:: Manual fallback
echo.
echo +==================================================+
echo ^|  Auto-install failed.                           ^|
echo ^|  Please install Python 3.9+ manually:          ^|
echo ^|  https://www.python.org/downloads/             ^|
echo ^|  Check "Add Python to PATH" during install.    ^|
echo +==================================================+
pause
exit /b 1

:python_found
if not defined PYTHON (
    echo ERROR: Python install may have succeeded but requires a new terminal.
    echo Please close this window and run setup.bat again.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('%PYTHON% --version') do echo   Found: %%i
echo.

:: -------------------------------------------------------
:: 2. Create / update virtual environments
:: -------------------------------------------------------

echo [1/4] Setting up Monitor...
if not exist "venv\Scripts\python.exe" %PYTHON% -m venv venv
venv\Scripts\pip install --quiet --upgrade pip
venv\Scripts\pip install --quiet -r requirements.txt
echo   Done.

echo [2/4] Setting up Dashboard Factory...
if not exist "01_Dashboard_Factory\venv\Scripts\python.exe" %PYTHON% -m venv 01_Dashboard_Factory\venv
01_Dashboard_Factory\venv\Scripts\pip install --quiet --upgrade pip
01_Dashboard_Factory\venv\Scripts\pip install --quiet -r 01_Dashboard_Factory\requirements.txt
echo   Done.

echo [3/4] Setting up Dashboard Factory QA...
if not exist "02_Dashboard_Factory_QA\.venv\Scripts\python.exe" %PYTHON% -m venv 02_Dashboard_Factory_QA\.venv
02_Dashboard_Factory_QA\.venv\Scripts\pip install --quiet --upgrade pip
02_Dashboard_Factory_QA\.venv\Scripts\pip install --quiet -r 02_Dashboard_Factory_QA\requirements.txt
echo   Done.

echo [4/4] Setting up Jira Tracker...
if not exist "03_Jira_Tracker\venv\Scripts\python.exe" %PYTHON% -m venv 03_Jira_Tracker\venv
03_Jira_Tracker\venv\Scripts\pip install --quiet --upgrade pip
03_Jira_Tracker\venv\Scripts\pip install --quiet -r 03_Jira_Tracker\requirements.txt
echo   Done.

echo.
echo +==================================================+
echo ^|  Setup complete!                                ^|
echo ^|  Double-click "Launch Monitor.bat" to start.   ^|
echo +==================================================+
echo.
pause
exit /b 0

:: -------------------------------------------------------
:: Helper: find a working Python 3.9+
:: -------------------------------------------------------
:find_python
for %%p in (python3.11 python3.10 python3.9 python3 python) do (
    where %%p >nul 2>&1
    if !errorlevel!==0 (
        for /f "tokens=2 delims= " %%v in ('%%p --version 2^>^&1') do (
            for /f "tokens=1,2 delims=." %%a in ("%%v") do (
                if %%a geq 3 if %%b geq 9 (
                    set PYTHON=%%p
                    exit /b 0
                )
            )
        )
    )
)
exit /b 1
