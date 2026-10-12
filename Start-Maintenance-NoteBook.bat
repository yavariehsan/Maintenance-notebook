@echo off
setlocal EnableDelayedExpansion
title Maintenance Notebook Launcher
REM ============================================================================
REM Maintenance Notebook - native Windows launcher (double-click to start)
REM
REM Starts the four services, each in its own window, using the established
REM external application-data root. Startup structure follows the proven local
REM reference pattern (start-open-notebook-New.bat), adapted to this
REM repository and its OPEN_NOTEBOOK_DATA_DIR storage configuration.
REM
REM Readiness sequencing: each service is started only after the previous one
REM is actually reachable (SurrealDB /health, API /health, frontend HTTP).
REM The browser opens only after ALL services report ready, so the first
REM page load never hits a half-started backend.
REM
REM Shutdown: after startup the launcher waits for the X key and then stops
REM ONLY the processes started by this launcher invocation. Ownership is
REM tracked two ways: (1) direct child processes of this launcher window,
REM and (2) service processes whose command line references this project's
REM derived paths (repo root, data root, SurrealDB directory) and that were
REM covers shells that fork the script, e.g. piped stdin). Only service
REM binary names (surreal/cmd/node/uv/python) are ever stopped, and never
REM the launcher command lines themselves. Unrelated SurrealDB/API/Node/
REM Python/CMD/Edge processes are never touched.
REM
REM Requirements: uv, Node.js/npm, existing .env, curl.exe, choice.exe.
REM SurrealDB is discovered at startup (see discovery below) and must be
REM version 2.6.x: that family owns the external store's storage revision
REM (e.g. 2.4.0 fails on this store). The launcher validates the detected
REM binary and refuses incompatible versions with an actionable error.
REM
REM Portable locations (all overridable, none hardcoded to one machine):
REM - MAINTENANCE_DATA_ROOT: application-data root (default keeps the
REM   established external store in E:\Maintenance_Ai_Agent_Data).
REM - SURREALDB_EXE: exact SurrealDB executable to use. When unset, the
REM   launcher looks for surreal.exe on PATH, then falls back to the legacy
REM   %USERPROFILE%\Tools\surrealdb-2.6.5 layout.
REM - SURREAL_USER / SURREAL_PASS: SurrealDB credentials (default root/root
REM   dev default). These must match SURREAL_USER/SURREAL_PASSWORD in .env.
REM SurrealDB credentials below must match SURREAL_USER/SURREAL_PASSWORD in
REM .env (this deployment uses the root/root dev default). If you change the
REM .env credentials, set SURREAL_USER/SURREAL_PASS to match.
REM
REM Ports: SurrealDB 127.0.0.1:8000, API 127.0.0.1:5055, frontend
REM 127.0.0.1:3000. If a port is already in use, close the owning process
REM first; this launcher never kills processes automatically.
REM No data is deleted, migrated manually, or overwritten by this script.
REM API startup owns database migrations.
REM ============================================================================

REM --- project locations: ROOT anchors at this script, DATA_ROOT defaults to
REM --- the established external store but can be relocated per machine.
set "ROOT=%~dp0"
if not defined MAINTENANCE_DATA_ROOT set "MAINTENANCE_DATA_ROOT=E:\Maintenance_Ai_Agent_Data"
set "DATA_ROOT=%MAINTENANCE_DATA_ROOT%"
if not defined SURREAL_USER set "SURREAL_USER=root"
if not defined SURREAL_PASS set "SURREAL_PASS=root"

REM --- external application-data root (API and worker read this at startup).
REM .env is left untouched: it has a known BOM/parsing limitation under
REM "uv run --env-file", and Windows paths are supplied here instead.
REM NOTE: DATA_FOLDER is intentionally NOT set; open_notebook/config.py
REM derives DATA_FOLDER from OPEN_NOTEBOOK_DATA_DIR (falls back to ./data).
set "OPEN_NOTEBOOK_DATA_DIR=%DATA_ROOT%"
set "PYTHONPATH=%ROOT%"
set EXITCODE=0

cd /d "%ROOT%"

REM --- preflight: fail early with actionable errors, before starting anything.
if not exist "%ROOT%.env" (
  echo [ERROR] Missing .env in %ROOT%
  echo   Copy .env.example to .env (if provided) or create it, then retry.
  exit /b 1
)
if not exist "%ROOT%run_api.py" (
  echo [ERROR] Missing run_api.py in %ROOT%
  echo   Run this launcher from a full repository checkout.
  exit /b 1
)
if not exist "%DATA_ROOT%\" (
  echo [ERROR] Application-data root not found: %DATA_ROOT%
  echo   Create it, or set MAINTENANCE_DATA_ROOT to the existing location.
  exit /b 1
)
where uv >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 'uv' not found on PATH.
  echo   Install uv ^(https://docs.astral.sh/uv/^) and retry.
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 'node' not found on PATH.
  echo   Install Node.js 22+ and retry.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 'npm' not found on PATH.
  echo   Repair the Node.js installation and retry.
  exit /b 1
)
where curl.exe >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 'curl.exe' not found on PATH.
  echo   Use a Windows 10+ inbox installation and retry.
  exit /b 1
)

REM --- SurrealDB discovery: explicit override, then PATH, then legacy layout.
REM --- Never guess across versions: the binary below is validated for the
REM --- required 2.6.x family before anything starts.
set "SURREAL_EXE="
if defined SURREALDB_EXE (
  if exist "%SURREALDB_EXE%" (
    set "SURREAL_EXE=%SURREALDB_EXE%"
  ) else (
    echo [ERROR] SURREALDB_EXE points to a missing file: %SURREALDB_EXE%
    exit /b 1
  )
)
if not defined SURREAL_EXE (
  for /f "delims=" %%S in ('where surreal.exe 2^>nul') do (
    if not defined SURREAL_EXE set "SURREAL_EXE=%%S"
  )
)
if not defined SURREAL_EXE (
  if exist "%USERPROFILE%\Tools\surrealdb-2.6.5\surreal.exe" (
    set "SURREAL_EXE=%USERPROFILE%\Tools\surrealdb-2.6.5\surreal.exe"
  )
)
if not defined SURREAL_EXE (
  echo [ERROR] No SurrealDB executable found.
  echo   Install SurrealDB 2.6.x and either put surreal.exe on PATH
  echo   or set SURREALDB_EXE to its full path, then retry.
  exit /b 1
)
for %%D in ("%SURREAL_EXE%\..") do set "SURREAL_DIR=%%~fD"
echo Using SurrealDB: %SURREAL_EXE%

REM --- version gate: the store revision requires the 2.6.x family.
REM --- `surreal version` prints "<major>.<minor>.<patch> ..." on line one.
set "SURREAL_VER="
for /f "tokens=1" %%V in ('"%SURREAL_EXE%" version 2^>nul') do (
  if not defined SURREAL_VER set "SURREAL_VER=%%V"
)
set "SURREAL_MAJOR="
set "SURREAL_MINOR="
for /f "tokens=1,2 delims=." %%A in ("%SURREAL_VER%") do (
  set "SURREAL_MAJOR=%%A"
  set "SURREAL_MINOR=%%B"
)
if "%SURREAL_MAJOR%.%SURREAL_MINOR%"=="2.6" (
  echo SurrealDB version %SURREAL_VER% accepted ^(requires 2.6.x^).
) else (
  if "%SURREAL_MAJOR%"=="" (
    echo [WARN] Could not parse SurrealDB version output; continuing.
    echo   If startup fails, set SURREALDB_EXE to a 2.6.x binary and retry.
  ) else (
    echo [ERROR] Incompatible SurrealDB version: %SURREAL_VER% ^(requires 2.6.x^).
    if exist "%USERPROFILE%\Tools\surrealdb-2.6.5\surreal.exe" (
      echo   A 2.6.x binary exists at %USERPROFILE%\Tools\surrealdb-2.6.5\surreal.exe
      echo   Set SURREALDB_EXE to that full path to use it.
    )
    echo   Install SurrealDB 2.6.x or point SURREALDB_EXE at one, then retry.
    exit /b 1
  )
)

REM --- process ownership: record this launcher window's PID and start time.
REM --- Shutdown stops (1) direct children of this PID with service names and
REM --- (2) service processes referencing this project's fixed paths that were
REM --- created after this launcher started.
for /f %%P in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq $PID }).ParentProcessId"') do set LAUNCHER_PID=%%P
for /f %%T in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq $PID }).CreationDate.ToString('yyyyMMddHHmmss')"') do set LAUNCH_START=%%T
if "%LAUNCHER_PID%"=="" goto NO_OWNERSHIP
if "%LAUNCH_START%"=="" goto NO_OWNERSHIP
echo Launcher PID: %LAUNCHER_PID% started %LAUNCH_START% (only processes started by this invocation will ever be stopped)
goto OWNERSHIP_OK
:NO_OWNERSHIP
echo [ERROR] Could not determine launcher ownership; aborting to avoid unsafe shutdown.
exit /b 1
:OWNERSHIP_OK

echo.
echo ==========================================
echo [1/4] Starting SurrealDB...
echo ==========================================

start "SurrealDB" "%SURREAL_EXE%" start --user "%SURREAL_USER%" --pass "%SURREAL_PASS%" --bind 127.0.0.1:8000 "rocksdb:%DATA_ROOT%\surrealdb"

echo Waiting for SurrealDB readiness (http://127.0.0.1:8000/health)...
set TRIES=0
:WAIT_SURREAL
curl.exe -sf -m 2 http://127.0.0.1:8000/health >nul 2>nul
if not errorlevel 1 goto SURREAL_READY
set /a TRIES+=1
if !TRIES! GTR 60 goto FAIL_SURREAL
ping -n 3 127.0.0.1 >nul
goto WAIT_SURREAL
:SURREAL_READY
echo [READY] SurrealDB on 127.0.0.1:8000 (%TIME%)

echo.
echo ==========================================
echo [2/4] Starting API...
echo ==========================================

start "API" cmd /k "cd /d %ROOT% && uv run --env-file .env run_api.py"

echo Waiting for API readiness (http://127.0.0.1:5055/health)...
set TRIES=0
:WAIT_API
curl.exe -sf -m 2 http://127.0.0.1:5055/health >nul 2>nul
if not errorlevel 1 goto API_READY
set /a TRIES+=1
if !TRIES! GTR 150 goto FAIL_API
ping -n 3 127.0.0.1 >nul
goto WAIT_API
:API_READY
echo [READY] API on 127.0.0.1:5055 (%TIME%)

echo.
echo ==========================================
echo [3/4] Starting Worker...
echo ==========================================

start "Worker" cmd /k "cd /d %ROOT% && uv run --env-file .env python -m surreal_commands.cli.worker --import-modules commands"

echo Waiting for worker process (surreal_commands.cli.worker)...
set TRIES=0
:WAIT_WORKER
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'surreal_commands\.cli\.worker' }) { exit 0 } else { exit 1 }" >nul 2>nul
if not errorlevel 1 goto WORKER_RUNNING
set /a TRIES+=1
if !TRIES! GTR 30 goto FAIL_WORKER
ping -n 3 127.0.0.1 >nul
goto WAIT_WORKER
:WORKER_RUNNING
echo [RUNNING] Worker (surreal_commands.cli.worker) (%TIME%)

echo.
echo ==========================================
echo [4/4] Starting Frontend...
echo ==========================================

start "Frontend" cmd /k "cd /d %ROOT%\frontend && npm run dev"

echo Waiting for frontend readiness (http://127.0.0.1:3000/)...
set TRIES=0
:WAIT_FRONTEND
curl.exe -sf -m 2 http://127.0.0.1:3000/ >nul 2>nul
if not errorlevel 1 goto FRONTEND_READY
set /a TRIES+=1
if !TRIES! GTR 150 goto FAIL_FRONTEND
ping -n 3 127.0.0.1 >nul
goto WAIT_FRONTEND
:FRONTEND_READY
echo [READY] Frontend on 127.0.0.1:3000 (%TIME%)

echo.
echo ==========================================
echo  Service status:
echo   SurrealDB - READY (127.0.0.1:8000)
echo   API       - READY (127.0.0.1:5055 /health)
echo   Worker    - RUNNING (surreal_commands.cli.worker)
echo   Frontend  - READY (127.0.0.1:3000)
echo  Open the app at: http://localhost:3000
echo ==========================================

start "" "http://localhost:3000"
echo Browser opened after all services reported ready (%TIME%).
echo.
choice /c X /n /m "Press X to stop all Maintenance Notebook services and exit: "
echo.
if errorlevel 2 goto CHOICE_ABORT
goto SHUTDOWN

:CHOICE_ABORT
echo [WARN] No X confirmation received; leaving services running.
echo Close the four service windows manually if you want to stop them.
exit /b 2

:FAIL_SURREAL
echo [ERROR] SurrealDB did not become ready on 127.0.0.1:8000 in time.
set EXITCODE=1
goto SHUTDOWN

:FAIL_API
echo [ERROR] API did not become ready on 127.0.0.1:5055 in time.
echo If port 5055 is already in use by another process, stop it and retry.
set EXITCODE=1
goto SHUTDOWN

:FAIL_WORKER
echo [ERROR] Worker process did not appear in time.
set EXITCODE=1
goto SHUTDOWN

:FAIL_FRONTEND
echo [ERROR] Frontend did not become ready on 127.0.0.1:3000 in time.
echo If port 3000 is already in use by another process, stop it and retry.
set EXITCODE=1
goto SHUTDOWN

:SHUTDOWN
echo.
echo Stopping services started by this launcher invocation ...
echo (Only owned surreal/cmd/node/uv/python processes are stopped.
echo  Pre-existing or unrelated processes are never touched.)
powershell -NoProfile -Command "$lp=$env:LAUNCHER_PID; $t0=$env:LAUNCH_START; $roots=@($env:ROOT,$env:DATA_ROOT,$env:SURREAL_DIR); $names='^(surreal\.exe|cmd\.exe|node\.exe|uv\.exe|python\.exe)$'; $done=@{}; foreach ($p in (Get-CimInstance Win32_Process)) { if ($p.ProcessId -eq $lp) { continue }; if ($p.Name -notmatch $names) { continue }; if ($p.CommandLine -like '*Start-Maintenance-NoteBook.bat*') { continue }; $owned = ($p.ParentProcessId -eq $lp); if ((-not $owned) -and ($p.CreationDate.ToString('yyyyMMddHHmmss') -ge $t0)) { foreach ($r in $roots) { if ($p.CommandLine -like ('*'+$r+'*')) { $owned=$true; break } } }; if ($owned -and (-not $done.ContainsKey($p.ProcessId))) { $done[$p.ProcessId]=$true; Write-Output ('Stopping ' + $p.Name + ' PID ' + $p.ProcessId); & taskkill /PID $p.ProcessId /T /F } }"
echo.
echo Verifying ports are released...
set TRIES=0
:WAIT_PORTS_CLOSED
set OPENPORTS=0
netstat -ano | findstr "LISTENING" | findstr "127.0.0.1:8000" >nul && set OPENPORTS=1
netstat -ano | findstr "LISTENING" | findstr "127.0.0.1:5055" >nul && set OPENPORTS=1
netstat -ano | findstr "LISTENING" | findstr ":3000" | findstr "LISTENING" >nul && set OPENPORTS=1
if "%OPENPORTS%"=="0" goto PORTS_CLOSED
set /a TRIES+=1
if !TRIES! GTR 15 goto PORTS_STUCK
ping -n 3 127.0.0.1 >nul
goto WAIT_PORTS_CLOSED
:PORTS_CLOSED
echo [OK] Ports 8000, 5055 and 3000 are released.
goto SHUTDOWN_DONE
:PORTS_STUCK
echo [WARN] Some port is still listening; check for processes outside this launcher.
:SHUTDOWN_DONE
echo All launcher-started services stopped. Exiting.
ping -n 4 127.0.0.1 >nul
exit /b !EXITCODE!
