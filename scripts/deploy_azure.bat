@echo off
setlocal enabledelayedexpansion

:: ===========================================================================
::  deploy_azure.bat: send XBRL Agent v2 to Azure App Service.
::  Ported from v1's script. Run it from the enterprise Windows laptop, the only
::  machine with both the code and Azure access. Steps for a first deploy and
::  for going back to v1: docs/azure-deploy.md.
::
::  Why it works this way (v1's reasons, still true):
::  - Not GitHub Actions: that would put enterprise Azure credentials in a
::    personal GitHub repository, which policy forbids.
::  - No tests here: this laptop runs Windows, Azure runs Linux, and the package
::    carries no tests. Deploy a commit whose tests have already passed.
::  - Always a fresh browser build: a plain `az webapp deploy` can send an old one.
::
::  Steps (any failure stops it):
::    1. warn if files have changes that are not committed
::    2. npm ci + npm run build, fresh, into web\dist
::    3. scripts\package.py azure: the zip, with the commit in version.txt
::    4. az webapp deploy, or the Cloud Shell steps when az is not installed
:: ===========================================================================

:: PDFs carry characters Windows' default code page cannot write (v1 gotcha 1).
set PYTHONUTF8=1

:: ---- The Azure target. Set both in this window before running. ----
if "%AZ_RESOURCE_GROUP%"=="" set "AZ_RESOURCE_GROUP=CHANGE-ME-resource-group"
if "%AZ_APP_NAME%"=="" set "AZ_APP_NAME=CHANGE-ME-app-name"

:: The company proxy reads encrypted traffic with its own certificate (v1
:: gotcha 5), so az may need these. No working values are known yet.
:: set "HTTPS_PROXY=http://proxy.corp:8080"
:: set "REQUESTS_CA_BUNDLE=C:\path\to\corporate-root-ca.pem"

cd /d "%~dp0\.."
echo ========================================
echo   Deploy XBRL Agent v2 to Azure App Service
echo   Resource group: %AZ_RESOURCE_GROUP%
echo   App name:       %AZ_APP_NAME%
echo ========================================
echo.

if "%AZ_RESOURCE_GROUP:~0,9%"=="CHANGE-ME" goto :no_target
if "%AZ_APP_NAME:~0,9%"=="CHANGE-ME" goto :no_target

:: ---- Python: the packager needs it; any Python 3 will do ----
if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

:: ---- Node.js: often installed but not on PATH (v1 gotcha 8) ----
where node >nul 2>&1
if errorlevel 1 (
    if exist "C:\Program Files\nodejs\node.exe" (
        set "PATH=C:\Program Files\nodejs;!PATH!"
    ) else (
        echo ERROR: Node.js not found. Install it or add it to PATH.
        exit /b 1
    )
)

:: ---- 1. Warn about changes that are not committed ----
git diff --quiet && git diff --cached --quiet
if errorlevel 1 (
    echo WARNING: some files have changes that are not committed. Deploying them
    echo          means what is live will not match any commit.
    set /p CONFIRM="Continue anyway? [y/N] "
    if /i not "!CONFIRM!"=="y" (
        echo Stopped.
        exit /b 1
    )
)

:: ---- 2. Build the browser app, fresh ----
echo.
echo [2/4] Building the browser app...
pushd web
call npm ci
if errorlevel 1 ( echo ERROR: npm ci failed. & popd & exit /b 1 )
call npm run build
if errorlevel 1 ( echo ERROR: the browser app build failed. & popd & exit /b 1 )
popd

:: ---- 3. The package ----
echo.
echo [3/4] Packaging...
set "PKG=%TEMP%\xbrl-v2-deploy.zip"
"!PYTHON!" scripts\package.py azure --out "%PKG%"
if errorlevel 1 ( echo ERROR: packaging failed. & exit /b 1 )

:: ---- 4. Deploy ----
echo.
echo [4/4] Deploying to Azure...
where az >nul 2>&1
if errorlevel 1 (
    echo The Azure command-line tool ^(az^) is not installed on this laptop. The
    echo package is built; deploy it from Azure Cloud Shell instead:
    echo   1. Open https://portal.azure.com, click the Cloud Shell icon, choose Bash.
    echo   2. Manage files ^> Upload, and pick !PKG!
    echo   3. Run:
    echo      az webapp deploy --resource-group %AZ_RESOURCE_GROUP% --name %AZ_APP_NAME% --src-path xbrl-v2-deploy.zip --type zip
    echo Kudu's drag-and-drop zip upload does not work for Linux apps.
    exit /b 1
)
:: az is az.cmd on Windows: without `call` this script would end when az does.
call az webapp deploy --resource-group "%AZ_RESOURCE_GROUP%" --name "%AZ_APP_NAME%" --type zip --src-path "%PKG%"
if errorlevel 1 ( echo ERROR: az webapp deploy failed. & exit /b 1 )

for /f %%H in ('git rev-parse --short HEAD') do set "GIT_HASH=%%H"
echo.
echo ========================================
echo   Deployed commit %GIT_HASH% to %AZ_APP_NAME%.
echo   Check it: https://^<your site^>/api/health shows "commit": "%GIT_HASH%".
echo   First v2 deploy? Follow docs\azure-deploy.md for the settings and first login.
echo ========================================
endlocal
exit /b 0

:no_target
echo ERROR: Choose the target app first. In this window, run for example:
echo          set AZ_RESOURCE_GROUP=rg-xbrl-agent-test
echo          set AZ_APP_NAME=xbrl-agent-test
echo        then run this script again.
exit /b 1
