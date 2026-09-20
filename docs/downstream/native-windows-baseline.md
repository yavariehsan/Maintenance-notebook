# Native Windows baseline

Final baseline record covering upstream commit `3127f14` in `E:\Project\Maintenance_Ai_Agent`, updated 2026-09-20.

**Outcome: technically accepted on SurrealDB 2.6.5 with disposable data.** Fresh migrations 1..25, API startup, notebook CRUD, direct and HTTP text search, restart idempotence, and worker module validation all pass unchanged. **SurrealDB 2.6.5 is the required native runtime. SurrealDB 3.2.4 is unsupported for this repository.** Git ownership established Milestone 2 (`origin` = downstream fork, `upstream` = official, `main` tracks `origin/main`). No application/UI code, dependencies, `.env`, or commits beyond the baseline documents were changed. No real application data was used.

## Tooling and dependency evidence

| Check | Result |
|---|---|
| `git --version` | `2.55.0.windows.3` |
| `node --version` | `v22.23.2` |
| `npm --version` | `11.19.1` |
| `uv --version` | `0.12.7` |
| `surreal version` | `3.2.4+20260803.93ab219`, Windows x86_64 |
| `uv --no-cache --offline run --no-sync python --version` | `Python 3.12.14`; satisfies `.python-version` (`3.12`) and `pyproject.toml` (`>=3.11,<3.13`) |
| `uv --no-cache --offline pip check` | 206 packages checked; one incompatibility: MoviePy 2.2.1 requires Pillow `<12`, installed Pillow is 12.3.0 |
| Selected installed packages versus `uv.lock` | Exact matches: content-core 2.0.7, FastAPI 0.136.3, MoviePy 2.2.1, Pillow 12.3.0, python-dotenv 1.2.2, surreal-commands 1.3.1, surrealdb Python client 1.0.8 |
| Frontend manifest/lockfile | Root dependencies and devDependencies match; `frontend/node_modules` absent |

The Pillow mismatch is the explicit `[tool.uv].override-dependencies` policy already documented in `pyproject.toml`, not a dependency change made for this baseline. This check is therefore not a clean dependency-health pass. Initial uv commands hit a sandbox cache permission error; `--no-cache --offline` allowed the checks without installing or synchronizing packages.

Frontend build/tests were skipped because dependencies were not installed. The lockfile comparison alone does not validate a build.

## Isolation and disposable artifacts

Test root:

```text
C:\Users\yavari.ehsan\AppData\Local\Temp\open-notebook-baseline-20260919-b120kzjm
  source/                 tracked-file archive of 3127f14; no .env or real data
  surrealdb/              disposable RocksDB store
  home/                   disposable user profile
  temp/, appdata/, localappdata/
  database.log, database-2.log, api.log, api-2.log, pytest.log, worker-help.log
  baseline-state.json, run-settings.json
```

The snapshot was created with `git archive`, not a worktree or branch. Tests used the existing repository `.venv\Scripts\python.exe` with the snapshot as working directory. Child environments retained only Windows executable/runtime essentials, then received explicit synthetic settings. `PYTHON_DOTENV_DISABLED=1` prevented implicit dotenv loading. User-profile, temporary, and application-cache directories were redirected into the test root. No provider credentials were passed.

An initial attempt lacked `USERPROFILE`, causing content-core's `Path.home()` to fail before API startup. Providing a disposable profile corrected the test harness, without changing application code. A subsequent log-print operation hit the Windows console encoding; the saved UTF-8 startup log was read separately. These harness errors are distinct from the confirmed database incompatibility.

The database and API used dynamically allocated loopback ports. The decisive run used database port 63313 and API port 63314, also retained in `run-settings.json`. All spawned test processes were stopped, and both ports were verified closed afterward. Artifacts are retained for diagnosis.

## Startup and compatibility results

The native database command was equivalent to:

```powershell
surreal start --bind "127.0.0.1:$dbPort" --user baseline --pass disposable-baseline-only --log info "rocksdb:$trial\surrealdb"
```

The synthetic password above belongs only to disposable tests. SurrealDB `/health` returned HTTP 200. The API ran the existing `run_api.py` with `API_RELOAD=false` and reached `api.main.lifespan`, which invoked the actual `AsyncMigrationManager`. No mocked migration code or modified SQL was used for this test.

Results:

- Backend imports completed; Uvicorn entered application startup.
- Database connectivity/version probing succeeded and reported schema version 0.
- Migration 1 failed in `open_notebook/database/migrations/1.surrealql`, at the `source.asset` field declaration: `FLEXIBLE TYPE option<object>`.
- Exact server error: **`Parse error: FLEXIBLE must be specified after TYPE`** (flattened migration query, position `[1:96]`).
- API logged `Application startup failed. Exiting.` and exited with code **3**. `/openapi.json` never became ready.
- Migration 1 did not complete; migrations 2-25 were not validated. Fresh-database startup is **incompatible with this installed SurrealDB 3.2.4 build**. Existing-database upgrade behavior and subsequent potential incompatibilities remain untested.

No SQL compatibility fixes or database version changes were attempted. The Python client connected successfully; the observed failure is server-side migration syntax validation.

Additional validation, within the same isolated snapshot:

```powershell
& $python -m pytest -q -p no:cacheprovider tests/test_repository_config.py tests/test_startup_migration_retry.py
& $python -m surreal_commands.cli.worker --help
```

- Pytest: **9 passed, 1 warning, 6.22 seconds**, exit 0. Warning: surreal-commands uses deprecated class-based Pydantic configuration. These mocked startup tests do not establish live database compatibility.
- Worker module help: exit 0. This validates the documented Windows module entry point, not queue processing. The worker was not started against the failed schema.

## Native reproduction commands

Use a fresh disposable snapshot, never the real application data directory. Run from the repository in PowerShell:

```powershell
$repo = 'E:\Project\Maintenance_Ai_Agent'
$python = Join-Path $repo '.venv\Scripts\python.exe'
$trial = Join-Path $env:TEMP ('open-notebook-baseline-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $trial | Out-Null
git -C $repo archive --format=zip --output="$trial\source.zip" 3127f14
Expand-Archive -LiteralPath "$trial\source.zip" -DestinationPath "$trial\source"
```

Use dedicated terminals; define `$repo`, `$python`, and the same `$trial` path in each. Before running application processes, retain only essential Windows environment variables and configure disposable paths. This intentionally applies only to dedicated test terminals:

```powershell
$keep = @('SYSTEMROOT','WINDIR','PATH','PATHEXT','COMSPEC','SYSTEMDRIVE')
$names = @([Environment]::GetEnvironmentVariables('Process').Keys)
foreach ($name in $names) {
    if ($name -notin $keep) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
}
foreach ($dir in @('home','temp','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path "$trial\$dir" | Out-Null
}
$env:USERPROFILE = "$trial\home"
$env:TEMP = "$trial\temp"
$env:TMP = "$trial\temp"
$env:APPDATA = "$trial\appdata"
$env:LOCALAPPDATA = "$trial\localappdata"
$env:PYTHON_DOTENV_DISABLED = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:NO_PROXY = '127.0.0.1,localhost'
$env:SURREAL_URL = 'ws://127.0.0.1:18000/rpc'
$env:SURREAL_USER = 'baseline'
$env:SURREAL_PASSWORD = 'disposable-baseline-only'
$env:SURREAL_NAMESPACE = 'baseline'
$env:SURREAL_DATABASE = 'baseline'
$env:OPEN_NOTEBOOK_ENCRYPTION_KEY = 'disposable-baseline-only'
$env:OPEN_NOTEBOOK_PASSWORD = ''
$env:API_HOST = '127.0.0.1'
$env:API_PORT = '15055'
$env:API_RELOAD = 'false'
Set-Location "$trial\source"
```

Choose unused ports; 18000/15055 below are reproduction examples, not the dynamically allocated ports used in validation. Start in order, each in its prepared terminal:

```powershell
# 1. Disposable database
surreal start --bind 127.0.0.1:18000 --user baseline --pass disposable-baseline-only "rocksdb:$trial\surrealdb"

# 2. API: invokes the unchanged startup/migration mechanism
& $python run_api.py

# 3. Worker: only after successful migrations; not reached in this baseline
$env:PYTHONPATH = "$trial\source"
& $python -m surreal_commands.cli.worker --import-modules commands

# 4. Frontend: only after dependencies and API are ready; not run in this baseline
$env:API_URL = 'http://127.0.0.1:15055'
$env:INTERNAL_API_URL = 'http://127.0.0.1:15055'
Set-Location "$trial\source\frontend"
npm run dev
```

The native guide's normal API/worker commands use `uv run --env-file .env ...`. This baseline deliberately omitted `.env` and used the confirmed uv-managed interpreter directly to preserve isolation. Do not start the API against valuable data while this compatibility failure is unresolved. Stop test services with Ctrl+C in their own terminals.

## Application storage mapping

Paths below are relative to the process working directory, normally the repository root. During testing they resolved inside `source/` in the disposable snapshot.

| Data | Current location/behavior | Future external mapping, not implemented |
|---|---|---|
| SurrealDB records, embeddings, credentials, settings, job state, migration versions | Location selected by native `surreal start` storage argument; independent of Python `DATA_FOLDER` | Existing operator path `E:\Maintenance_Ai_Agent_Data\surrealdb`; not accessed |
| Uploads | `./data/uploads`, from `UPLOADS_FOLDER` | `E:\Maintenance_Ai_Agent_Data\uploads` |
| Podcasts/audio and generation artifacts | `./data/podcasts/episodes/<generated-directory>` | `E:\Maintenance_Ai_Agent_Data\podcasts` |
| Notebook/source chat checkpoints | `./data/sqlite-db/checkpoints.sqlite`; both graph modules open the configured SQLite file | `E:\Maintenance_Ai_Agent_Data\sqlite-db\checkpoints.sqlite` |
| Tokenizer cache | `./data/tiktoken-cache`; `TIKTOKEN_CACHE_DIR` environment override is implemented | `E:\Maintenance_Ai_Agent_Data\tiktoken-cache` |
| Content-core user configuration | Dependency reads `%USERPROFILE%\.content-core\config.toml` if present | Separate operator configuration decision; test profile was empty |
| Browser preferences/auth token | Zustand/localStorage in the browser; not part of filesystem `DATA_FOLDER` | Browser-managed; no relocation implied |

`open_notebook/config.py` hardcodes `DATA_FOLDER = "./data"`. `UPLOADS_FOLDER`, `PODCASTS_FOLDER`, and `LANGGRAPH_CHECKPOINT_FILE` are derived constants, not implemented environment overrides. Setting `DATA_FOLDER` or `LANGGRAPH_CHECKPOINT_FILE` in the environment alone does not relocate them. Import creates the data subdirectories; backend import also created the disposable SQLite file before migrations succeeded. No storage refactor was made.

## Git ownership (established Milestone 2)

Initial tree was clean on `main` at `3127f14`, tracking `origin/main` (official repository). Milestone 2 executed the following against the supplied downstream fork:

```powershell
git remote rename origin upstream
git remote add origin https://github.com/yavariehsan/Maintenance-notebook
git fetch upstream
git fetch origin
```

Verification: `origin/main` already existed at `3127f14`, identical to local `main` and `upstream/main` — no divergence. `git branch --set-upstream-to=origin/main main` now makes local `main` track `origin/main`; `git push origin main` reported `Everything up-to-date`.

Result: `upstream` retains `https://github.com/lfnovo/open-notebook.git`; `origin` is `https://github.com/yavariehsan/Maintenance-notebook`. No `upstream-main`, sync, or custom branches were created. No history rewrite, rebase, or force-push.

## SurrealDB 2.6.5 validation (2026-09-20)

Validated against unmodified `main` (`3127f14` tree, `git status` clean except untracked docs). No `.env`, frontend, migration, or tracked files changed. No real application data used. Disposable artifacts live outside the repository in `C:\Users\yavari.ehsan\AppData\Local\Temp\opencode\m1-surreal265-20260920-618e19ba` (`surrealdb-data/`, `surreal.log`, `api.log`, `api.err.log`, `probe_db.py`, `run_validation.ps1`, `result.json`).

### Why SurrealDB 3.2.4 is incompatible

- Migration `1.surrealql` uses 2.x field syntax `FLEXIBLE TYPE option<object>` (`open_notebook/database/migrations/1.surrealql:7`). SurrealDB 3.2.4 rejects it: `Parse error: FLEXIBLE must be specified after TYPE`.
- Migration 1 also uses 2.x full-text syntax `DEFINE ANALYZER ... TOKENIZERS ... FILTERS ...` and `DEFINE INDEX ... SEARCH ANALYZER my_analyzer BM25 HIGHLIGHTS` (`1.surrealql:65-72`), changed in SurrealDB 3.x migration documentation.
- Version counter uses `CREATE type::thing('_sbl_migrations', $version)` / `DELETE type::thing(...)` (`open_notebook/database/async_migrate.py:301,311`), also rejected under 3.x.
- Reordering `FLEXIBLE` alone is therefore insufficient. Migrations were intentionally not patched for 3.2.4.

### SurrealDB 2.6.5 checksum verification

- Binary: `surreal-v2.6.5.windows-amd64.exe`, verified before execution.
- Official GitHub release `v2.6.5` (asset id `380465370`): `size=62194176`, `digest=sha256:dd9b6fa15edacbde96d490dd5727b49b5cf40df80f29074c7dc17acb974f509f`, confirmed live via `https://api.github.com/repos/surrealdb/surrealdb/releases/tags/v2.6.5`.
- Local `Get-FileHash -Algorithm SHA256`: `DD9B6FA15EDACBDE96D490DD5727B49B5CF40DF80F29074C7DC17ACB974F509F`, size `62194176`. Match (case-insensitive).
- `surreal version`: `2.6.5 for windows on x86_64`. Surreal log: `Running 2.6.5 for windows on x86_64`.

### Native application-path validation

Exact native Windows startup sequence for this project (run from the repository root in PowerShell, each service in its own terminal):

```powershell
# 1. Database (SurrealDB 2.6.5 required; 3.x unsupported)
& $verifiedSurreal start --bind 127.0.0.1:8000 --user <SURREAL_USER from .env> --pass <SURREAL_PASSWORD from .env> "rocksdb:<disposable-data-dir>"

# 2. API (loads the existing .env file unchanged)
uv run --env-file .env run_api.py

# 3. Worker module check (queue processing not validated)
.venv\Scripts\python.exe -m surreal_commands.cli.worker --help
```

Native Windows workflow from repository root with existing `.env` file unchanged (validation 2026-09-20 used `uv run --env-file .env run_api.py`):

```powershell
uv run --env-file .env run_api.py
```

- SurrealDB storage: disposable `rocksdb:<temp>\surrealdb-data`, outside repository. Real `E:\Maintenance_Ai_Agent_Data\surrealdb` untouched (still empty). Repository `./data` did not exist before; test-created `data/` (`podcasts/`, `sqlite-db/checkpoints.sqlite`, `tiktoken-cache/`, `uploads/`) removed afterward (gitignored, `git status` unchanged).
- `.env` sets `SURREAL_URL=ws://127.0.0.1:8000/rpc`. Port 8000 was occupied by unrelated `ClientTools5` (observed PID 12772 on 2026-09-20; do not terminate unrelated processes), so SurrealDB used free loopback port `50333` (`Started web server on 127.0.0.1:50333`) with `.env` `SURREAL_USER/PASSWORD/NAMESPACE/DATABASE`. Process-level `SURREAL_URL=ws://127.0.0.1:50333/rpc` overrode only the port; `.env` file not modified. API used native default `127.0.0.1:5055` (verified free before start).
- Normal project ports: SurrealDB `127.0.0.1:8000` (from `.env` `SURREAL_URL`), API `127.0.0.1:5055` (default when `API_PORT` is unset). Disposable-test override: start SurrealDB on a free loopback port and export `SURREAL_URL=ws://127.0.0.1:<free-port>/rpc` in the test process only; keep `API_PORT=5055` when free. Never edit `.env` port values for a disposable run.
- `GET /health`: HTTP 200. `GET /openapi.json`: HTTP 200.

### Migration result

Fresh database started at version 0. API lifespan ran the unmodified `AsyncMigrationManager`:

- `Running migration 1` through `Running migration 25`: 25 events.
- `Migration successful. New version: 25`.
- `Migrations completed successfully. Database is now at version 25`.
- `API initialization completed successfully`. `Uvicorn running on http://127.0.0.1:5055`.
- Direct probe: `get_all_versions()` returns exactly `1..25`; `get_current_version()==25`; `needs_migration()==False`.

### API startup and smoke-test result

- `GET /api/notebooks` fresh: `[]`.
- `POST /api/notebooks`: `notebook:ho7ywgop1u4nh3exgjxa`.
- `GET /api/notebooks/{id}` and `PUT` name update: pass.
- Direct `repo_create source` with FLEXIBLE `asset` object, `repo_relate ... reference`, `repo_create source_embedding`, `fn::vector_search(..., 0.5, $notebooks)`: pass (`source:6nwtmsu4vv3gg7moeoed`).
- `repo_delete` source plus `DELETE /api/notebooks/{id}`: final `GET /api/notebooks` is `[]`.
- Processes stopped via `taskkill /PID <pid> /T /F`. Ports `50333` and `5055` verified closed (no LISTENING sockets, no `python` processes). `result.json`: `{"success":true,"migrations":25}`.

### Required native SurrealDB version

Required native runtime for this project: **SurrealDB 2.6.5**. Do not use SurrealDB 3.2.4 without a dedicated migration-rewrite task.

### Additional acceptance validation (2026-09-20)

Disposable run `m1-accept-20260920-bd9ce32c` (fresh `surrealdb-data`, SurrealDB port `63756`, API `5055`, `result.json success:true`):

- Direct `fn::text_search('ZirconiumMarker', 10, true, false, $notebook_ids)`: pass, seeded source returned by `id`/`parent_id`.
- HTTP `POST /api/search` `{"query":"ZirconiumMarker","type":"text","limit":10,"search_sources":true,"search_notes":false,"notebook_id":"<id>"}`: `total_count>=1`, seeded source present. Text search works without an embedding model.
- Restart idempotence: API stopped (`taskkill /PID <pid> /T /F`), restarted against the same disposable store. Log shows `Database is already at the latest version`; notebook persists; text search still returns results.
- Worker: `.venv\Scripts\python.exe -m surreal_commands.cli.worker --help` exit 0. Queue processing not started.
- Ports `63756`/`5055` verified closed afterward; no `python`/`surreal` processes left; repository `./data` recreated by the run and removed afterward.

### Environment notes

- `.env` cause: file starts with bytes `EF BB BF` (UTF-8 BOM) before `#`. `uv 0.12.7 --env-file .env` warns `Failed to parse environment file .env at position 0`; Python `load_dotenv()` tolerates the BOM, so the API still authenticated with `.env` credentials. Safest recommendation (not executed): re-save `.env` as UTF-8 without BOM with byte-identical content otherwise, approved explicitly by the operator since `.env` is a local gitignored file. No content or secret changes are needed.
- Port 8000 conflict: observed `127.0.0.1:8000 LISTENING` owned by `ClientTools5` (PID 12772) during validation; later absent. Unrelated user processes were not terminated or modified.
- `open_notebook/config.py` still hardcodes `DATA_FOLDER = "./data"`; no storage refactor made.

### Remaining compatibility concerns

- Frontend build/tests skipped: `frontend/node_modules` absent; no dependencies installed for this milestone.
- Worker queue processing, upgrade from pre-existing data, and multi-client concurrency remain unvalidated.
- `SEARCH ANALYZER` DDL plus direct and HTTP text search now pass on 2.6.5; vector search also passes. No further SurrealDB incompatibilities observed on 2.6.5.

## Remaining blockers and next step

1. Git ownership established; baseline documents pending commit in Milestone 2.
2. Keep SurrealDB 2.6.5 pinned as the native runtime; do not start UI work on SurrealDB 3.2.4.
3. Approve a separate external-storage implementation and tests before real-data use.
4. Frontend install/build and worker queue processing belong to later milestones, not this baseline.

Do not begin the custom presentation layer until the baseline commit lands. No PowerShell automation scripts or custom UI files were created. No real application data was used.
