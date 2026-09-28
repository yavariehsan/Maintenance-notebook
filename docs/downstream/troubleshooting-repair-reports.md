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
  analysis state. Filesystem paths never reach the browser. Same
  filenames never collide: the stored name is unique per upload and the
  `analysis_key` is per-file random hex (never derived from filenames).
- **محتوا tab.** Column names + up to 10 non-empty data rows, generated
  with read-only openpyxl directly from the stored workbook. The engine
  never runs for previews.
- **تحلیل tab.** `تحلیل محتوا` starts a **single-report** analysis run
  (`POST /repair-reports/{id}/analyze`); enabled for `not_analyzed`
  (and `failed`, as the retry), disabled for
  `queued`/`processing`/`completed`. No force-reprocess action exists.
  The tab also shows the report-scoped repair actions mined from this
  file alone (actions / verifications / handover-outcome events /
  history-only records — every item points at a verbatim sentence).
  The legacy collection-wide `POST /repair-reports/analyze` is kept for
  backward compatibility only.

## Analysis lifecycle

States per report: `not_analyzed → queued → processing → completed |
failed`. Single-report runs (`repair_analysis_run` with a singleton
`report_ids`) snapshot **exactly one file**: the generated database
represents that report alone (atomic single-writer replacement — the
previous valid database stays live until the new one validates). No
implicit process-everything: only the requested report is queued.

Flow: `POST /api/repair-reports/{id}/analyze` → run record (`queued`,
singleton `report_ids`) →
surreal-commands job `analyze_repair_reports` → worker builds the
single-file aggregate workbook, runs `analyze_workbook(...,
output_path=<runtime DB>)`, marks run + report `completed`. The
engine's writer (tmp DB → integrity validation → `os.replace`) keeps
runtime readers on either the previous or the new valid database —
never a partial one. The run manifest records the file's aggregate row
range so deterministic fallback IDs (`ROW-<sheet>-<row>`) stay
traceable to `report → worksheet → row`.

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

The equipment selector shows ONLY the equipment code (`کد فرایندی`,
e.g. `M1`) — no name, manufacturer, model, or counts. Identity
semantics are unchanged; this is presentation only.

Concept model (do not conflate):

- **Failure mode**: the observed failure/symptom classification.
- **Candidate cause**: one historical cause associated with the mode,
  with support/probability/confidence.
- **Repair action**: one diagnostic/corrective/verification step mined
  from historical repair descriptions (role + frequency + source
  records). Standalone `تست شد` is kept in history and emitted as a
  `TechnicalVerification` (never a recommended action); `تست و تحویل
  شد` yields a verification plus a handover event.
- **Troubleshooting guide**: the synthesized presentation — failure/
  symptom, ranked candidate causes, the unified recommended-action
  procedure (distinct actions across causes, ordered by cause rank then
  frequency; roles and record refs passed through, never rescored),
  historical evidence/provenance, safety notes when available, and the
  evidence-sufficiency state. Causes are a component of the guide, never
  the guide itself. For the single approved shape (uncompleted
  replacement + switch adjustment + test/handover), the procedure shows
  a deterministic guide-facing instruction
  (`در صورت عدم تعویض پالت، سوئیچ بررسی و در صورت لزوم تنظیم گردد.`)
  with the verbatim recorded action linked beneath it — originals are
  never rewritten.

## Report deletion

`DELETE /repair-reports/{id}` deletes one uploaded report by its stable
record ID (never by filename alone): the report record and its stored
workbook are removed, so the report disappears from the normal listing.
Run history, task/command rows, and the generated knowledge database
are preserved; guides already generated keep pointing at the stored
record IDs, and the Repair Guide source selector reports a deleted
source as unavailable instead of remapping it to another same-named
file. 404 for unknown reports, 409 while the report is being analyzed
(queued/processing or snapshotted by the live run).

## Repair Guide source selection

The Repair Guide screen opens with a Knowledge Source selector
(Text Mining | LLM) followed by source scoping. Text Mining is the
existing deterministic flow below; LLM mode queries only the LLM
Knowledge DB (never merged).

### Text Mining mode (unchanged)

The Repair Guide screen opens with a source-report selector (Step 0)
listing uploaded repair reports by stable record ID, each labeled with
filename, row count, upload time, and short ID so duplicate filenames
stay distinguishable. A context line names the report(s) backing the
current knowledge database (latest completed run); a backing source
that was deleted renders a warning and is never remapped. Selecting a
source outside the backing run hides the guides (mismatch state)
instead of showing another source's knowledge; with no completed run
known, browsing behaves as before.

### LLM mode (M12)

- **Builds.** `llm_knowledge_build` rows (migration 28): one per
  generation run over selected repair reports. Builds coexist
  (completed / partial / failed / queued / running / cancelled) and
  are never destroyed by newer builds. Created from the report
  detail's تحلیل tab ("Generate LLM Knowledge") or
  `POST /repair-reports/llm-builds`; an equivalent build that is
  still active yields 409 with the live build ID instead of a
  duplicate.
- **Records.** `llm_knowledge_record` rows: one validated extraction
  per workbook row with `build_id`, stable `source_report_id` /
  `source_record_id` (`<analysis_key>-LLMROW-<sheet>-<excel_row>`),
  verbatim `source_text`, and per-item `DATA_SUPPORTED` vs
  `LLM_INFERRED` provenance. Failed records persist their
  `record_error` traceably and never invalidate sibling records.
- **Pipeline (no embeddings — not RAG).** Workbook bytes →
  deterministic row extraction → one structured LLM call per record
  (`LLMKnowledgeGenerator` over the configured language model via
  `provision_langchain_model`) → JSON validation (malformed / missing
  fields / bad enums / wrong shape / empty rejected) → semantic
  post-rules (standalone `تست شد` → verification only,
  `تست و تحویل شد` → verification + handover event, pure
  closure/handover → event, never a corrective action) → SurrealDB.
  The mining SQLite database is never read or written by this path.
- **Guide.** `GET /troubleshooting/llm/guide?build_id=&source_report_id=`
  returns only the selected source's records (explicit
  `no_records_for_source` empty state); a deleted backing report
  keeps its stable identity with `source_deleted` and is never
  remapped. Every response carries `knowledge_source=LLM`,
  `build_id`, `model`, `prompt_version` (`m12-v1`), and the source
  IDs; the UI splits Historical Evidence from LLM-derived
  interpretation with per-item basis badges.
- **Failure isolation.** A failed build/record leaves reports, mining
  knowledge, guides, and embeddings untouched. With zero LLM builds,
  Text Mining works exactly as before (no LLM configuration
  required).

## Endpoints (all under `/api`)

`POST /repair-reports` · `GET /repair-reports` ·
`DELETE /repair-reports/{id}` (404 unknown, 409 while analyzing) ·
`GET /repair-reports/{id}` (+ latest run) ·
`GET /repair-reports/{id}/preview` ·
`POST /repair-reports/{id}/analyze` (409 when busy, 404 unknown, 400
already completed) ·
`GET /repair-reports/{id}/actions` (report-scoped repair actions /
verifications / handover-outcome events / history-only records, 422
when the database is unavailable) ·
`POST /repair-reports/analyze` (legacy collection-wide, 409 when busy) ·
`GET /repair-reports/runs[/{id}]` ·
`POST /repair-reports/llm-builds` (201 new build; 409 with live
build ID while an equivalent build is active; 404 unknown report;
400 empty selection; 422 when no language model is configured) ·
`GET /repair-reports/llm-builds[/{id}]` ·
`GET /repair-reports/llm-builds/{id}/records[?source_report_id=]` ·
`GET /troubleshooting/llm/guide?build_id=&source_report_id=`
(`knowledge_source=LLM` + provenance; explicit empty/deleted-source
states, never cross-source mixing) ·
`DELETE /tasks/{job_id}` (terminal command rows only — never files,
reports, runs, or knowledge; 409 while active, 404 unknown) ·
`DELETE /tasks/history` (terminal task records only; active jobs kept;
idempotent).

## Tests

- Backend: `tests/test_repair_reports.py` — mocked-SurrealDB router
  tests + real-engine aggregate/runtime chain on synthetic fixtures.
- Backend (M12): `tests/test_llm_knowledge_service.py` — extraction
  contract validation, semantic post-rules (`تست شد` cases),
  record-ID stability, build idempotency/stale-heal, guide
  source-isolation/deleted-source/versioning; no LLM or DB.
  `tests/test_llm_knowledge_api.py` — router contract (201/409/400/
  404/422, scoping, provenance, empty states), worker partial-failure
  behavior with an injected fake LLM, resume-without-duplicates, and
  Tasks-page surfacing of the `generate_llm_knowledge` family.
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

## Analysis state contract (report vs run vs command)

Three related but distinct states share one truth; no screen may present
a running analysis as completed:

- **Report** (`repair_report.analysis_state`): the state of the
  report's analysis *result* — `not_analyzed | queued | processing |
  completed | failed`.
- **Run** (`repair_analysis_run.status`): the currently executing
  knowledge-generation run — `queued | processing | completed | failed`.
- **Command** (`command.status`): the background job — `new | running |
  completed | failed | canceled`, visible on the Tasks page alongside
  embedding jobs.

The Tasks page (`GET /api/tasks`) lists both embedding jobs and repair
analysis runs: analysis commands map to the same task row shape with
`item_type: "repair_analysis"`, the linked `run_id`, and report
filenames as the title. There are no chunk counts for analysis jobs, so
progress stays indeterminate while active (never estimated) and reads
100% once completed. Tasks are ordered most-recently-updated first
(canonical `updated_at`, then creation time, then stable job ID as the
deterministic tie-break). Bounded 2s polling on both screens converges them
on the same truth; starting analysis additionally wakes the Tasks
cache, and observing completion on a report detail refreshes the
troubleshooting guide caches.

Embedding jobs are deduplicated per source: submitting `/embed` while a
genuinely active (`new`/fresh `running`) embed job exists for the same
source returns the live command ID instead of a duplicate. A `running`
job with no worker write for over 30 minutes is declared abandoned,
marked `failed` with an explicit reason, and replaced by exactly one
new job — bounded recovery that never restarts work indefinitely.
`Clear History` (`DELETE /api/tasks/history`, confirmed in the UI)
removes terminal (`completed`/`failed`/`canceled`) task records only;
active jobs are kept, never canceled or deleted, and the operation is
idempotent.

Rules: starting analysis marks the included report `queued`
immediately (both screens converge through bounded 2s polling; the
Tasks page wakes via cache invalidation at submit). A `failed` run
keeps previously-`completed` reports `completed` (the runtime DB still
holds their knowledge); only reports that never contributed become
`failed`. A second POST while a run is active gets 409 — including
inside the submit grace window (5 min), so a duplicate run can never
interleave state writes. A `completed` report cannot be re-analyzed
(no force-reprocess). Task-record deletion (`DELETE /tasks/{id}`)
removes only the terminal command row; active jobs get 409, and files,
reports, runs, and the knowledge database are never touched. Worker liveness comes from heartbeats written
to the command record during engine execution; a `running` command
without liveness for 30 min is declared orphaned, its run finalized as
failed, and its command row flipped to `failed` (a restarted worker
only resumes `new` commands, and the worker refuses to complete a run
that is no longer `processing`, so resurrection is impossible). A lost
source file fails its run loudly; restore the file and retry — there is
deliberately no silent subset regeneration. Report deletion removes the
report record and its stored file; run/task history and the knowledge
database are preserved, and deleted sources are reported as
unavailable, never remapped.

Operational notes (observed on native Windows, not hypothetical):

- Uvicorn file-reload does not reliably replace the API worker process
  on Windows: after editing backend code, restart the API (and always
  restart the worker — it has no reload at all) instead of trusting
  autoreload.
- A missing source blob fails its run loudly by design; restore the
  file from backup and retry — the failed report stays eligible.
- Lease/grace constants live in `api/repair_report_service.py`
  (`SUBMIT_GRACE_SECONDS`, `RUNNING_LEASE_SECONDS`,
  `HEARTBEAT_INTERVAL_SECONDS`); the 30-minute lease comfortably covers
  observed engine runs (30–110 s for 1706–3414 records) while bounding
  orphaned-`running` recovery.
