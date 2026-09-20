@echo off
title Maintenance Notebook Launcher
REM ============================================================================
REM Maintenance Notebook - native Windows launcher (double-click to start)
REM
REM Starts the four services, each in its own window, using the established
REM external application-data root. Startup structure follows the proven local
REM reference pattern (start-open-notebook-New.bat), adapted to this
REM repository and its OPEN_NOTEBOOK_DATA_DIR storage configuration.
REM
REM Requirements: uv, Node.js/npm, existing .env. SurrealDB runs from the
REM pinned binary below (2.6.5), matching the version that owns the external
REM store in E:\Maintenance_Ai_Agent_Data\surrealdb. Do not substitute a
REM different SurrealDB version: storage revisions are not readable across
REM versions (e.g. 2.4.0 fails on this store with revision errors).
REM SurrealDB credentials below must match SURREAL_USER/SURREAL_PASSWORD in
REM .env (this deployment uses the root/root dev default). If you change the
REM .env credentials, update the SurrealDB line below to match.
REM
REM Ports: SurrealDB 127.0.0.1:8000, API 127.0.0.1:5055, frontend
REM 127.0.0.1:3000. If a port is already in use, close the owning process
REM first; this launcher never kills processes automatically.
REM No data is deleted, migrated manually, or overwritten by this script.
REM API startup owns database migrations.
REM ============================================================================

REM --- fixed project locations ---
set ROOT=E:\Project\Maintenance_Ai_Agent
set DATA_ROOT=E:\Maintenance_Ai_Agent_Data

REM --- external application-data root (API and worker read this at startup).
REM .env is left untouched: it has a known BOM/parsing limitation under
REM "uv run --env-file", and Windows paths are supplied here instead.
REM NOTE: DATA_FOLDER is intentionally NOT set; open_notebook/config.py
REM derives DATA_FOLDER from OPEN_NOTEBOOK_DATA_DIR (falls back to ./data).
set OPEN_NOTEBOOK_DATA_DIR=%DATA_ROOT%
set PYTHONPATH=%ROOT%

cd /d %ROOT%

echo.
echo ==========================================
echo Starting SurrealDB...
echo ==========================================

start "SurrealDB" "%USERPROFILE%\Tools\surrealdb-2.6.5\surreal.exe" start --user root --pass root --bind 127.0.0.1:8000 "rocksdb:%DATA_ROOT%\surrealdb"

echo Waiting for SurrealDB on port 8000...

:WAIT_SURREAL
netstat -ano | findstr "127.0.0.1:8000" | findstr "LISTENING" >nul

if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto WAIT_SURREAL
)

echo SurrealDB is ready on port 8000.

echo.
echo ==========================================
echo Starting API...
echo ==========================================

start "API" cmd /k "cd /d %ROOT% && uv run --env-file .env run_api.py"

echo.
echo ==========================================
echo Starting Worker...
echo ==========================================

start "Worker" cmd /k "cd /d %ROOT% && uv run --env-file .env python -m surreal_commands.cli.worker --import-modules commands"

echo.
echo ==========================================
echo Starting Frontend...
echo ==========================================

start "Frontend" cmd /k "cd /d %ROOT%\frontend && npm run dev"

echo.
echo ==========================================
echo All services are starting...
echo Open the app at: http://127.0.0.1:3000
echo ==========================================

timeout /t 3 /nobreak >nul

start "" "http://127.0.0.1:3000"

pause
