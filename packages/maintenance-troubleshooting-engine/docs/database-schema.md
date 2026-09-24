# Troubleshooting database schema

SQLite database generated atomically by `OutputDatabaseWriter`
(`<output>.tmp-<pid>` → integrity validation → atomic replace).
Schema version `1` (see `metadata`). Foreign keys enforced at write
time; read path uses only indexed `SELECT`s (no mining at query time).

## Tables

```text
metadata (key TEXT PK, value TEXT)
  schema_version, engine_version, probability_semantics,
  support_method, input_filename, input_hash

analysis_runs (id INTEGER PK, started_at, completed_at,
  duration_seconds, engine_version, schema_version, input_filename,
  input_hash, record_count, equipment_count, failure_mode_count,
  cause_count, repair_action_count, llm_enrichment_enabled,
  llm_provider, llm_model)
  One row per generation run (audit trail).

equipment (code TEXT PK, name, main_class, sub_class, equipment_type,
  manufacturer, model, t1..t5, record_count)
  One row per distinct کد فرایندی (consensus t1..t5).

maintenance_records (record_id TEXT PK, equipment_code, equipment_name,
  request_prefix, request_number, request_type, symptom_text,
  repair_description, failure_mode_recorded, proposed_failure_mode,
  failure_mechanism_recorded, cause_recorded, t1..t5, location_tree,
  process_tree, safety_notes, raw_json)
  Every workbook row, including invalid ones (traceability). The loose
  equipment association is intentional: invalid rows have no equipment.

failure_modes (id TEXT PK, canonical_label, normalized_label,
  enriched_label, aliases_json, record_count, status)
  Mined modes (status: classified / unclassified).

equipment_failure_modes (equipment_code, failure_mode_id,
  record_ids_json, record_count; composite PK)
  Which modes each equipment attests, with record lists.

candidate_causes (id TEXT PK, equipment_code → equipment,
  failure_mode_id → failure_modes, cause_label, kinds_json,
  support_percent, evidence_count, weighted_evidence, denominator,
  calculation_method, similarity_score, similarity_basis,
  confidence_value, confidence_basis, probability, rank)
  Ranked per (equipment, mode); full support accounting inline.

repair_actions (id TEXT PK, equipment_code, failure_mode_id, category,
  role, action_text, normalized_text, source_record_ids_json, frequency)
  Mined actions, scoped and deduplicated.

cause_repair_actions (cause_id, repair_action_id; composite PK)
  Structured cause → action links.

evidence (id TEXT PK, scope_equipment, scope_failure_mode,
  record_id → maintenance_records, equipment_code, relevance_basis,
  relevance_detail, weight)
  Weighted per-scope evidence with reasons
  (e.g. `same_manufacturer_and_model+same_failure_mode`).

cause_evidence (cause_id, evidence_id; composite PK)
  Explicit cause → evidence traceability.

guide_sections (id INTEGER PK, equipment_code, failure_mode_id,
  section, title, position, body)
  Pre-rendered sections: symptom, cause (ranked), safety, method.
  Bodies use "Historical evidence indicates…" wording — no universal
  engineering claims.

safety_notes (id INTEGER PK, equipment_code, failure_mode_id,
  cause_ids_json, note_text, source_record_ids_json)
  Recorded safety notes only (never invented), linked to causes.
```

## Relationships

```text
equipment 1───* equipment_failure_modes *───1 failure_modes
equipment 1───* candidate_causes
candidate_causes *───* repair_actions (via cause_repair_actions)
candidate_causes *───* evidence (via cause_evidence)
evidence *───1 maintenance_records
equipment + failure_modes ───* guide_sections / safety_notes
```

## Indexes (runtime reads stay cheap)

```text
idx_records_equipment, idx_efm_equipment, idx_causes_scope,
idx_actions_scope, idx_evidence_scope, idx_evidence_record,
idx_sections_scope, idx_safety_scope
```

The repository (`runtime/TroubleshootingRepository`) answers
equipment → modes → guide → causes → actions → evidence with keyed
lookups only — never a full-history scan per request.

## Limitations (honest boundaries)

- Percentages are evidence shares, not calibrated probabilities.
- A cause absent from history cannot be suggested (no hallucination).
- Records without repair text contribute frequency/statistics but no
  actions; such guides carry `insufficient_historical_repair_evidence`.
- Cross-equipment transfer follows technical similarity only;
  location/process coincidence transfers nothing.
- Lexical failure-mode clustering groups wording, not deep semantics
  (semantic enrichment is an optional, explicitly-marked layer).
- Empty historical evidence yields no distribution (no invented splits).
