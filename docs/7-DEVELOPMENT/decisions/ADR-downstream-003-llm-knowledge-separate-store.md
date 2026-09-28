# ADR-downstream-003: LLM troubleshooting knowledge lives in SurrealDB beside the mining SQLite DB

Date: 2026-09-28 · Status: accepted · Scope: M12 (LLM Knowledge Generation)

## Context

The Troubleshooting Engine's deterministic text-mining path produces a
precomputed SQLite database (Phase A batch → Phase B read-only
runtime). M12 adds a second, independent LLM-derived knowledge path.
The spec forbids merging the stores, overwriting mining records, and
making mining depend on the LLM.

## Decision

1. **New SurrealDB tables, not SQLite.** `llm_knowledge_build` and
   `llm_knowledge_record` (migration 28) hold LLM knowledge in the
   application's persistent store. The mining SQLite file is never
   opened for LLM reads or writes. SurrealDB was chosen because builds
   need concurrent-submit semantics (409 idempotency, stale-heal),
   the Tasks page already renders `command` rows generically, and no
   new database artifact needs shipping. Both tables are SCHEMALESS
   like every other application table: SCHEMAFULL array/object field
   types SILENTLY DROP values on SurrealDB 2.6.5 (verified live:
   `array`/`array<any>` store `[]`, `array<object>` stores `[{}]`),
   so type safety lives in the Pydantic service layer instead.
2. **The engine package is untouched.** LLM prompting, validation, and
   semantic post-rules live in `api/llm_knowledge_service.py` (pure
   functions) + `api/llm_generation.py` (`LLMKnowledgeGenerator` over
   the existing `provision_langchain_model`). The engine's
   TechnicalVerification / PostRepairEvent distinction is mirrored as
   a local post-rule, not an engine import, so mining never gains an
   LLM dependency.
3. **Builds reuse the surreal-commands worker** (`generate_llm_knowledge`
   command, same retry/heartbeat conventions as `analyze_repair_reports`)
   so build status appears on the Tasks page with no new framework.
4. **Guide source selection never merges.** The Guide UI queries one
   store per mode; the LLM guide is addressed by
   `(build_id, source_report_id)` instead of the mining
   `(equipment, failure_mode)` hierarchy, which LLM rows do not carry.
5. **No embeddings, no RAG.** Per-record structured extraction works
   directly from verbatim workbook-row text.

## Consequences

- Fresh installs with zero LLM builds (and no language model
  configured) keep full Text Mining behavior; `start_build` raises
  `ConfigurationError` (422) without touching mining.
- Same-millisecond duplicate submissions can still race (as with the
  existing embed path); the 409 covers the practical
  double-click/retry case.
- Record IDs are `<analysis_key>-LLMROW-<sheet>-<excel_row>` — stable
  per report, not joinable to mining `record_id`s by design.

## Alternatives rejected

- SQLite tables alongside mining: would couple the LLM lifecycle to
  the single-writer mining replacement cycle and risk store merging.
- Engine-package LLM stage: would violate the no-LLM-in-mining rule
  and add provider deps to the standalone package.
