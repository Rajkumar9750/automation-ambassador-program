@echo off
cd /d "%~dp0"
title Automation Ambassador Program - Setup

echo.
echo +==================================================+
echo ^|   Automation Ambassador Program - Setup          ^|
echo +==================================================+
echo.

:: Detect python command
where python >nul 2>&1
if %errorlevel%==0 (
    set PYTHON=python
) else (
    where python3 >nul 2>&1
    if %errorlevel%==0 (
        set PYTHON=python3
    ) else (
        echo ERROR: Python not found.
        echo Install Python 3.9+ from https://www.python.org/downloads/
        echo Make sure to check "Add Python to PATH" during install.
        pause
        exit /b 1
    )
)

for /f "tokens=*" %%i in ('%PYTHON% --version') do echo   Found: %%i
echo.

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
echo ^|  Setup complete!                                 ^|
echo ^|  Double-click "Launch Monitor.bat" to start.    ^|
echo +==================================================+
echo.
pause
