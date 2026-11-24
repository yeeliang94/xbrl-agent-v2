@echo off
:: Build a source-only zip for a Veracode static scan, in veracode\.
:: Run start.bat once first so the Python environment exists.
:: Add --include-tests to include the tests. Rules: scripts\package.py.
setlocal
cd /d "%~dp0\.."
set PYTHONUTF8=1

if not exist "venv\Scripts\python.exe" (
    echo ERROR: the Python environment is missing. Run start.bat once first.
    pause
    exit /b 1
)
where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: git is not on PATH. The packager asks git which files to include.
    pause
    exit /b 1
)

venv\Scripts\python.exe scripts\package.py veracode %*
if errorlevel 1 (
    echo.
    echo Packaging failed. Read the message above.
    pause
    exit /b 1
)
pause
