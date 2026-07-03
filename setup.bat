@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Automation Ambassador Program - Setup

echo.
echo +==================================================+
echo ^|   Automation Ambassador Program - Setup          ^|
echo +==================================================+
echo.

:: -------------------------------------------------------
:: 1. Ensure Git is available
:: -------------------------------------------------------

where git >nul 2>&1
if %errorlevel% neq 0 (
    :: install.ps1 puts PortableGit here — add it to PATH for this session
    if exist "%USERPROFILE%\PortableGit\cmd\git.exe" (
        set "PATH=%USERPROFILE%\PortableGit\cmd;%PATH%"
    )
)
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo   Git not found. Please re-run install.ps1 to install it automatically.
    pause
    exit /b 1
) else (
    for /f "tokens=*" %%i in ('git --version') do echo   Git: %%i
)
echo.

:: -------------------------------------------------------
:: 2. Ensure Python 3.11 is available
:: -------------------------------------------------------

echo   Ensuring Python 3.11 is installed...

:: Check embeddable Python placed by install.ps1 (no-admin path)
set PYTHON=%USERPROFILE%\python311\python.exe
if exist "%PYTHON%" goto :python_found

:: Check standard per-user install location
set PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
if exist "%PYTHON%" goto :python_found

:: Check system install location
set PYTHON=%PROGRAMFILES%\Python311\python.exe
if exist "%PYTHON%" goto :python_found

:: Search PATH for python3.11 / python3.10 / python3.9 / python (3.11)
set PYTHON=
call :find_python
if defined PYTHON goto :python_found

echo.
echo +==================================================+
echo ^|  Python 3.11 could not be found.               ^|
echo ^|  Please re-run install.ps1 — it will install   ^|
echo ^|  Python automatically without admin rights.    ^|
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
call :make_venv "venv" "%PYTHON%"
venv\Scripts\pip install -q --upgrade pip 2>nul
venv\Scripts\pip install -q -r requirements.txt
echo   Done.

echo [2/4] Setting up Dashboard Factory...
call :make_venv "01_Dashboard_Factory\venv" "%PYTHON%"
01_Dashboard_Factory\venv\Scripts\pip install -q --upgrade pip 2>nul
01_Dashboard_Factory\venv\Scripts\pip install -q -r 01_Dashboard_Factory\requirements.txt
echo   Done.

echo [3/4] Setting up Dashboard Factory QA...
call :make_venv "02_Dashboard_Factory_QA\.venv" "%PYTHON%"
02_Dashboard_Factory_QA\.venv\Scripts\pip install -q --upgrade pip 2>nul
02_Dashboard_Factory_QA\.venv\Scripts\pip install -q -r 02_Dashboard_Factory_QA\requirements.txt
echo   Done.

echo [4/4] Setting up Jira Tracker...
call :make_venv "03_Jira_Tracker\venv" "%PYTHON%"
03_Jira_Tracker\venv\Scripts\pip install -q --upgrade pip 2>nul
03_Jira_Tracker\venv\Scripts\pip install -q -r 03_Jira_Tracker\requirements.txt
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
:: Helper: create venv, recreating if wrong Python version
:: -------------------------------------------------------
:make_venv
set VPATH=%~1
set VPY=%~2
if exist "%VPATH%\Scripts\python.exe" (
    for /f "tokens=2 delims= " %%v in ('"%VPATH%\Scripts\python.exe" --version 2^>^&1') do (
        for /f "tokens=1,2 delims=." %%a in ("%%v") do (
            if %%a==3 if %%b leq 11 exit /b 0
        )
    )
    echo   Wrong Python version in %VPATH% — recreating...
    rmdir /s /q "%VPATH%" 2>nul
)
%VPY% -m venv "%VPATH%"
exit /b 0

:: -------------------------------------------------------
:: Helper: find a working Python 3.9-3.11
:: -------------------------------------------------------
:find_python
for %%p in (python3.11 python3.10 python3.9 python) do (
    where %%p >nul 2>&1
    if !errorlevel!==0 (
        for /f "tokens=2 delims= " %%v in ('%%p --version 2^>^&1') do (
            for /f "tokens=1,2 delims=." %%a in ("%%v") do (
                if %%a==3 if %%b geq 9 if %%b leq 11 (
                    set PYTHON=%%p
                    exit /b 0
                )
            )
        )
    )
)
exit /b 1
