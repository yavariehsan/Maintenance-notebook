# Repair Reports Workflow + Troubleshooting Guide (Milestone 6)

First UI integration over the troubleshooting stack (M1 engine → M2 batch
pipeline → M3 validation → M4 read-only runtime → M5 frontend data layer).

```text
                ┌──────────────────────┐
                │  گزارشات تعمیر       │
                │                      │
                │  Repair Report Files │
                └──────────┬───────────┘
                           │
                           │ analysis
                           ▼
                ┌──────────────────────┐
                │ Maintenance Engine   │
                │      Offline         │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ Troubleshooting DB   │
                └──────────┬───────────┘
                           │ read-only
                           ▼
                ┌──────────────────────┐
                │ Troubleshooting API  │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ راهنمای تعمیر        │
                │                      │
                │ تجهیز → حالت خرابی  │
                │       → راهنما       │
                └──────────────────────┘
```

## گزارشات تعمیر (Collection → Repair Reports)

- **Storage.** Uploaded `.xlsx`/`.xlsm` files are stored unchanged under
  `<DATA_FOLDER>/repair-reports/` (atomic unique-name claim, basename
  strip, traversal guard — same conventions as `uploads/`). One
  `repair_report` SurrealDB record per file: filename, size, worksheet,
  column/data-row counts, a stable 8-hex `analysis_key`, and the
  analysis state. Filesystem paths never reach the browser.
- **محتوا tab.** Column names + up to 10 non-empty data rows, generated
  with read-only openpyxl directly from the stored workbook. The engine
  never runs for previews.
- **تحلیل tab.** `تحلیل محتوا` starts a collection-wide analysis run;
  enabled for `not_analyzed` (and `failed`, as the retry), disabled for
  `queued`/`processing`/`completed`. No force-reprocess action exists.

## Analysis lifecycle

States per report: `not_analyzed → queued → processing → completed |
failed`. Runs (`repair_analysis_run`) snapshot the **entire collection**:
every run regenerates the runtime database from all uploaded reports,
so a new file adds knowledge without discarding previous work.

Flow: `POST /api/repair-reports/analyze` → run record (`queued`) →
surreal-commands job `analyze_repair_reports` → worker builds the
aggregate workbook, runs `analyze_workbook(..., output_path=<runtime
DB>)`, marks run + reports `completed`. The engine's writer (tmp DB →
integrity validation → `os.replace`) keeps runtime readers on either
the previous or the new valid database — never a partial one.

**Concurrency.** The API returns 409 while a run is active, and the
worker re-checks at start (a late duplicate fails transiently and
retries later). Only one knowledge-generation operation replaces the
runtime database at a time.

**Failure bookkeeping.** A failed run keeps previously-`completed`
reports `completed` (the database still holds their knowledge — tracked
via `last_completed_run_id`); only reports that never contributed become
`failed`. A run whose worker dies without completing is self-healed to
`failed` on the next status check (command-record lifecycle is the
source of truth), so nothing sticks in `processing` forever.

## Multi-file strategy (host-side aggregation, engine untouched)

The engine reads one workbook sheet per invocation and stores
`maintenance_records.record_id` as PRIMARY KEY, so the host builds a
deterministic aggregate workbook per run:

- Files concatenated in stable `(created, id)` order; headers are the
  union in first-seen order; every other cell copied verbatim.
- The request-prefix column (`پیشوند درخواست`) is namespaced per file
  (`<analysis_key>-<prefix>`, e.g. `a3f9c2e1-BR`), making record IDs
  (`a3f9c2e1-BR-1042`) unique across files while remaining traceable to
  `report → worksheet → row`. The run manifest records each file's
  aggregate row range for fallback-ID (`ROW-<sheet>-<row>`) traceability.
- Mining, similarity, support/probability/confidence logic unchanged
  (prefix feeds only the record ID).

## راهنمای تعمیر (Processing → Troubleshooting Guide)

Equipment → failure mode → guide, read exclusively through the existing
M5 hooks/client (`useTroubleshootingEquipment`, `useTroubleshooting-
FailureModes`, `useTroubleshootingGuide`, …). No browser mining, no LLM,
no client-side scoring. Support (0–100%), probability (0–1 normalized
share) and confidence (0–1 evidence-count) render as distinct labeled
values. `insufficient_historical_repair_evidence` warnings, safety
notes, evidence excerpts with source record IDs, and pre-rendered guide
sections all come from the precomputed database verbatim.

## Endpoints (all under `/api`)

`POST /repair-reports` · `GET /repair-reports` ·
`GET /repair-reports/{id}` (+ latest run) ·
`GET /repair-reports/{id}/preview` ·
`POST /repair-reports/analyze` (409 when busy) ·
`GET /repair-reports/runs[/{id}]`.

## Tests

- Backend: `tests/test_repair_reports.py` — mocked-SurrealDB router
  tests + real-engine aggregate/runtime chain on synthetic fixtures.
- Frontend: screen tests (list, two-tab detail, guide flow) with mocked
  hooks + API client tests; navigation and locale-parity coverage.

## Native execution (no Docker/WSL)

The supported workflow is native Windows: pinned `surreal.exe` 2.6.5
(`Start-Maintenance-NoteBook.bat`), `uv run` API, `surreal-commands`
worker (`--import-modules commands`), `npm run dev`, and the engine as
an in-worker Python call. Docker files in this repository are optional
release/deployment support only — nothing in this workflow depends on
them. Command modules must keep real (non-string) input/output type
hints: the command registry resolves them at registration, so
`from __future__ import annotations` is forbidden there. Validated live
on 2026-09-26 against disposable native services with the real
`Sample-1.xlsx` (single-file run: 1706 records/13 equipment; two-file
run: 3412 records, evidence split evenly across both file namespaces).
