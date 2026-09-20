# ADR-downstream-002: External application storage

- **Status**: Proposed (design only; not implemented).
- **Date**: 2026-09-20
- **Baseline**: `3127f14`
- **Related**: [Native Windows baseline](../../downstream/native-windows-baseline.md), ADR-downstream-001.

## Context

Native Windows runs must keep persistent application data outside the repository. Today `open_notebook/config.py` hardcodes `DATA_FOLDER = "./data"` with derived `uploads/`, `podcasts/`, `sqlite-db/checkpoints.sqlite`, and `tiktoken-cache/`; importing the module creates them via `os.makedirs`. SurrealDB storage is already independent (native `surreal start` storage argument; Docker named volume `surrealdb`, image `surrealdb/surrealdb:v2`). Only `TIKTOKEN_CACHE_DIR` has an environment override. No storage refactor has been made; validation used disposable `./data` recreated and removed per run.

## Target layout

Under `E:\Maintenance_Ai_Agent_Data\` (only directories the application needs; `surrealdb/` already exists empty):

| Data | Current source | Target | Config mechanism required | Code change? |
|---|---|---|---|---|
| SurrealDB records, embeddings, credentials, settings, job state, migration versions | `surreal start "rocksdb:<path>"` arg / Docker `surrealdb` volume | `E:\Maintenance_Ai_Agent_Data\surrealdb` | None (already external by invocation) | No |
| Uploads | `UPLOADS_FOLDER = ./data/uploads` (`config.py:12`) | `E:\Maintenance_Ai_Agent_Data\uploads` | New env override read in `config.py` | Yes, small |
| Podcasts/audio artifacts (`episodes/<generated>/`) | `PODCASTS_FOLDER = ./data/podcasts` (`config.py:18`); episode dirs built by `build_episode_output_dir()` (`commands/podcast_commands.py:27`); DB stores paths relative to `PODCASTS_FOLDER` (`open_notebook/podcasts/audio_paths.py`) | `E:\Maintenance_Ai_Agent_Data\podcasts` | Same override as above | Yes, small |
| Notebook/source chat checkpoints | `LANGGRAPH_CHECKPOINT_FILE = ./data/sqlite-db/checkpoints.sqlite` (`config.py:9`); opened by `open_notebook/graphs/chat.py` and `source_chat.py` | `E:\Maintenance_Ai_Agent_Data\sqlite-db\checkpoints.sqlite` | Same override as above | Yes, small |
| Tokenizer cache | `TIKTOKEN_CACHE_DIR` env or `./data/tiktoken-cache` (`config.py:25`); re-exported for tokenizer libs (`open_notebook/utils/token_utils.py`) | `E:\Maintenance_Ai_Agent_Data\tiktoken-cache` | Already exists (`TIKTOKEN_CACHE_DIR`); keep precedence | No |
| content-core user config (`%USERPROFILE%\.content-core\config.toml`, dependency behavior) | Operator user profile | Separate operator decision | Out of scope | No |
| Browser preferences/auth token (Zustand/localStorage) | Browser | None (browser-managed) | Out of scope | No |

No other persistent filesystem writes were found in `open_notebook/`, `api/`, or `commands/`. `/notebooks/` in `.gitignore` is legacy; no code writes there.

## Decisions

1. Introduce one root override (proposed name `OPEN_NOTEBOOK_DATA_DIR`, unset = current `./data` behavior) that re-roots `sqlite-db/`, `uploads/`, and `podcasts/`, preserving the relative layout so podcast relative audio paths survive the move. Keep `TIKTOKEN_CACHE_DIR` precedence as-is.
2. Keep SurrealDB external by invocation (no code change): document the required native command with `rocksdb:E:\Maintenance_Ai_Agent_Data\surrealdb`.
3. No per-directory overrides in the first change; one root variable is the smallest reviewable surface.

## Migration and backup

- Migrate with all services stopped: copy `./data/uploads`, `./data/podcasts`, `./data/sqlite-db/checkpoints.sqlite` to the matching targets; set the root override plus `TIKTOKEN_CACHE_DIR`; start SurrealDB 2.6.5 on the external store; start the API and verify version 25 with no pending migrations.
- Rollback: unset the override and restart; `./data` remains the fallback.
- Backup: file-copy `uploads/`, `podcasts/`, `checkpoints.sqlite` while stopped (SQLite backup API preferred if online copy is ever needed); SurrealDB via stopped-RocksDB copy or `surreal export`; tokenizer cache excluded (regenerable).

## Smallest safe implementation boundary (future change, not this milestone)

1. `open_notebook/config.py`: read root override, derive the four paths, keep `makedirs` behavior, keep `TIKTOKEN_CACHE_DIR` precedence.
2. Tests on disposable directories: startup creates dirs; podcast relative-path resolution (`audio_paths.py`) against moved root; restart persistence; unset-override fallback to `./data`.
3. Operator doc update: required variables and native Windows start order. No migration code, schema, API, worker, or UI changes.

## Consequences

External data survives repository operations (clean checkouts, `git clean`) and separates operator state from code. The override must be set consistently for every process (API, worker); a half-configured process would write to `./data`. Import-time `makedirs` remains, so a missing override silently recreates `./data` — startup validation must assert the resolved paths.
