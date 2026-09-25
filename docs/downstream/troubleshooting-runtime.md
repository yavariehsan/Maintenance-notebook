# Troubleshooting runtime integration (downstream)

Read-only runtime boundary between the host application and the
standalone maintenance troubleshooting engine
(`packages/maintenance-troubleshooting-engine/`).

```text
Raw Maintenance Excel
        |
        | Offline batch processing (Phase A, may take a long time)
        v
Maintenance Troubleshooting Engine
        |
        v
Troubleshooting SQLite DB  (precomputed knowledge, versioned schema)
        |
        | Read-only runtime (Phase B, indexed SQLite reads)
        v
TroubleshootingRepository  (package public API, mode=ro)
        |
        v
Host Adapter  (api/troubleshooting_service.py: config, health, conversion)
        |
        v
Application API  (api/routers/troubleshooting.py)
```

## Two artifacts, two roles

| Artifact | Role | Touched at runtime? |
|---|---|---|
| Raw maintenance database (Excel workbook) | Input to offline batch generation | Never. The runtime has no Excel code path. |
| Troubleshooting Database (SQLite) | Precomputed runtime knowledge | Read-only (`mode=ro`; never created, migrated, or written). |

## Configuration

Explicit file override (absolute path recommended):

```bash
TROUBLESHOOTING_DB_PATH=/data/troubleshooting/maintenance_troubleshooting.db
```

Otherwise the database resolves under the shared application data root
(`OPEN_NOTEBOOK_DATA_DIR` convention from `open_notebook/config.py`):

```text
<DATA_FOLDER>/troubleshooting/maintenance_troubleshooting.db
```

e.g. `E:\Maintenance_Ai_Agent_Data\troubleshooting\maintenance_troubleshooting.db`
when `OPEN_NOTEBOOK_DATA_DIR=E:\Maintenance_Ai_Agent_Data`, else
`./data/troubleshooting/...`. Generate it offline first:

```bash
maintenance-troubleshooting analyze history.xlsx --output <that path>
```

No database is ever auto-created or auto-regenerated: a missing file is
reported as `missing`, not materialized.

## Dependency direction

```text
maintenance-troubleshooting-engine
              ↑
              |  public API only (repository, views, schema version)
        host adapter (api/troubleshooting_service.py)
              ↑
              |
          host app (router, tests, docs)
```

The package is imported installed-first, with a fallback to the
vendored checkout layout (`packages/maintenance-troubleshooting-engine/src`,
also present in the Docker image via `COPY . /app`). If the package is
absent, only troubleshooting reads report `unavailable` — the rest of
the API keeps working. The package itself depends on nothing host-side
(no FastAPI, no SurrealDB, no app config); verified by its own
boundary tests.

## Health states (`GET /api/troubleshooting/status`, always 200)

| State | Meaning |
|---|---|
| `available` | Readable, schema matches, equipment count reported. |
| `missing` | File absent (never auto-created). |
| `unreadable` | Not a readable SQLite database. |
| `incompatible` | `schema_version` metadata differs from the supported version. |
| `unavailable` | Engine package itself not installed. |

The check is fast (file stat + one read-only open + metadata +
equipment count). No filesystem paths ever appear in API bodies; paths
stay in server logs.

## Compatibility contract

- The database carries `metadata.schema_version` (currently `"1"`).
- The host compares it against the engine's exported
  `TROUBLESHOOTING_SCHEMA_VERSION`.
- Match → `available`; mismatch → `incompatible` with both versions
  reported (regenerate with the offline pipeline). No version
  negotiation beyond this check.

## API boundary (all under `/api`, existing auth applies)

```text
GET /troubleshooting/status
GET /troubleshooting/equipment
GET /troubleshooting/equipment/{code}
GET /troubleshooting/equipment/{code}/failure-modes
GET /troubleshooting/equipment/{code}/failure-modes/{mode_id}          (guide)
GET /troubleshooting/equipment/{code}/failure-modes/{mode_id}/causes
GET /troubleshooting/equipment/{code}/failure-modes/{mode_id}/evidence
```

Semantics: every number is read from precomputed data —
`support_percent` (evidence share, not a probability), `probability`,
`confidence`, `weighted_evidence`/`denominator`/`calculation_method`,
ranks, roles/categories, and evidence with source `record_id`s. Nothing
is recomputed in the API layer, and wording stays evidence-based (the
stored sections already say "Historical evidence indicates…").

## Errors (existing conventions, no SQLite internals leak)

| Situation | Result |
|---|---|
| Database missing/unreadable/incompatible | `422` + generic "unavailable" message |
| Unknown equipment / failure mode | `404` |
| Malformed internal data | `500` + regeneration hint (details in server logs) |
| Unexpected failure | `500` generic (details in server logs) |

Typed host exceptions (`ConfigurationError`, `NotFoundError`,
`OpenNotebookError`) map through the existing `api/main.py` handlers.

## Performance and caching

No application-level cache: per-request read-only opens serve indexed
lookups in milliseconds, and the database file may be atomically
replaced after a future batch run (a cache would risk serving stale
knowledge). No full-table scans on lookup paths, no Excel parsing, no
embeddings, no LLM calls, no mining at runtime.

## Security

Operational data stays behind typed repository operations: no static
file serving of the SQLite file, no SQL execution endpoints, no SQL
fragments from clients, no filesystem paths in responses.

## Verification

- `tests/test_troubleshooting_adapter.py`: config resolution, all
  health states, read paths with precomputed-value assertions, 404/422
  mapping, file-hash read-only proof, malformed-DB handling.
- Package `tests/test_repository_readonly.py`: `mode=ro` rejects
  writes, missing files are never created, schema-version export
  matches generated databases.
