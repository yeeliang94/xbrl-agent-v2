@echo off
:: Start XBRL Agent v2 on http://localhost:8100 (or PORT from .env), on Windows.
:: Sets up what is missing first: the Python environment, its packages and the
:: browser app. A step whose inputs have not changed is skipped
:: (scripts\startup_cache.py), so later starts are quick.
setlocal enabledelayedexpansion
cd /d "%~dp0"
:: PDFs carry characters Windows' default code page cannot write (v1 gotcha 1).
set PYTHONUTF8=1
set "VERSION_CHECK=import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"

:: ---- The Python environment: remade when broken or older than 3.12 ----
if exist "venv\" (
    set "VENV_OK="
    if exist "venv\Scripts\python.exe" (
        venv\Scripts\python.exe -c "%VERSION_CHECK%" >nul 2>&1 && set "VENV_OK=1"
    )
    if not defined VENV_OK (
        echo The Python environment is broken or older than 3.12; making a new one.
        rmdir /s /q venv
    )
)

if not exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD="
    rem 1. The Windows py launcher.
    where py >nul 2>&1 && py -3 -c "%VERSION_CHECK%" >nul 2>&1 && set "PYTHON_CMD=py -3"
    rem 2. The usual install folders, newest first: Python is often installed but not on PATH.
    if not defined PYTHON_CMD (
        for %%V in (314 313 312) do (
            for %%D in ("%LOCALAPPDATA%\Programs\Python\Python%%V" "C:\Program Files\Python%%V" "C:\Python%%V") do (
                if not defined PYTHON_CMD if exist "%%~D\python.exe" (
                    "%%~D\python.exe" -c "%VERSION_CHECK%" >nul 2>&1 && set "PYTHON_CMD="%%~D\python.exe""
                )
            )
        )
    )
    rem 3. python on PATH.
    if not defined PYTHON_CMD (
        where python >nul 2>&1 && python -c "%VERSION_CHECK%" >nul 2>&1 && set "PYTHON_CMD=python"
    )
    if not defined PYTHON_CMD (
        echo Python 3.12 or newer is needed. Install it from python.org and run this again.
        pause
        exit /b 1
    )
    echo Making the Python environment with !PYTHON_CMD!...
    !PYTHON_CMD! -m venv venv
    if errorlevel 1 ( pause & exit /b 1 )
)

venv\Scripts\python.exe scripts\startup_cache.py check pip
if errorlevel 1 (
    echo Installing Python packages...
    rem requirements.txt applies constraints.txt itself.
    venv\Scripts\python.exe -m pip install -q -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
    venv\Scripts\python.exe scripts\startup_cache.py mark pip
) else (
    echo Python packages unchanged; skipping the install.
)

if not exist ".env" (
    copy .env.example .env >nul
    echo Made .env from .env.example. Add the gateway address and key to it.
    notepad .env
)

:: ---- Node.js: often installed but not on PATH (v1 gotcha 8) ----
where node >nul 2>&1
if errorlevel 1 (
    if exist "C:\Program Files\nodejs\node.exe" (
        set "PATH=C:\Program Files\nodejs;!PATH!"
    ) else if exist "%LOCALAPPDATA%\Programs\nodejs\node.exe" (
        set "PATH=%LOCALAPPDATA%\Programs\nodejs;!PATH!"
    )
)

:: ---- The browser app ----
where node >nul 2>&1
if errorlevel 1 goto :no_node
for /f %%N in ('node --version') do echo Node.js %%N
venv\Scripts\python.exe scripts\startup_cache.py check npm
if errorlevel 1 (
    echo Installing the browser app's packages...
    pushd web
    call npm ci
    if errorlevel 1 ( popd & pause & exit /b 1 )
    popd
    venv\Scripts\python.exe scripts\startup_cache.py mark npm
) else (
    echo Browser app packages unchanged; skipping the install.
)
venv\Scripts\python.exe scripts\startup_cache.py check build
if errorlevel 1 (
    echo Building the browser app...
    pushd web
    call npm run build
    if errorlevel 1 ( popd & pause & exit /b 1 )
    popd
    venv\Scripts\python.exe scripts\startup_cache.py mark build
) else (
    echo Browser app unchanged; skipping the build.
)
goto :start_server

:no_node
if exist "web\dist\index.html" (
    echo WARNING: Node.js not found. Using the browser app built earlier, which may be out of date.
) else (
    echo WARNING: Node.js not found, so the browser app cannot be built. Install it from nodejs.org.
)

:start_server
echo Starting the server...
venv\Scripts\python.exe -m app.main
pause
