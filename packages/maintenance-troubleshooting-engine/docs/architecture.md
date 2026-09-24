# Architecture

## Two phases

```text
Phase A — offline batch knowledge generation (may take a long time):

Raw Maintenance Database / Excel
  ↓  InputAdapter + RecordParser (inputs/)
Canonical Records (stable IDs; deterministic fallbacks, never dropped)
  ↓  Normalizer (text/)
Normalized copies (originals untouched)
  ↓  DataQualityAnalyzer (quality/)
Quality report + valid (minable) subset
  ↓  EquipmentAnalyzer (domain/equipment.py)
Equipment entities (identity = کد فرایندی; consensus t1..t5)
  ↓  FailureModeAnalyzer (stages/failure_modes.py)
Canonical failure modes (original / normalized / canonical triple)
  ↓  SimilarityAnalyzer (similarity/)
Equipment similarity matrix (configurable weights + reasons)
  ↓  EvidenceMiner (stages/evidence.py)
Weighted per-scope evidence (same-canonical-mode only)
  ↓  CauseMiner (stages/causes.py)
Candidate causes (explicit / mechanism / inferred kinds)
  ↓  RepairActionMiner (stages/repairs.py)
Structured actions (taxonomy + diagnostic/corrective/verification)
  ↓  [optional] KnowledgeEnrichmentProvider (enrichment/)
Validated structured suggestions (never direct DB writes)
  ↓  KnowledgeSynthesizer (stages/synthesis.py)
Ranked guides, support %, confidence, probabilities, safety
  ↓  OutputDatabaseWriter (stages/writer.py)
NEW troubleshooting SQLite database (atomic: tmp → validate → replace)

Phase B — runtime querying (fast, no mining):

UI / API → TroubleshootingRepository → indexed SQLite reads → result
```

The runtime never reads Excel, clusters records, computes similarity,
extracts causes/actions, or calls an LLM for basic retrieval.

## Module responsibilities

| Module | Owns | Must not |
|---|---|---|
| `domain/` | dataclasses for equipment, records, failures, evidence, causes, guides, repairs, runs, metrics | import I/O, ML, or host code |
| `stages/` | explicit batch stages (parse → mine → synthesize → write) | UI or host concerns |
| `similarity/` | structural technical-tree classification + equipment weight matrix | location/process similarity |
| `text/` | normalization/tokenization/canonicalization + similarity/embedding protocols | any specific LLM/embedding SDK |
| `quality/` | validation and quality reports over canonical records | mutate source records |
| `inputs/` | Excel reading, column mapping, record-ID strategies | host paths, host config |
| `outputs/` | knowledge-base model + JSON serialization | UI or HTTP concerns |
| `enrichment/` | optional provider boundary (NoOp default, fake test double) | direct SQLite writes, API keys in core |
| `runtime/` | read-only repository over generated databases | mining logic |
| `config.py` | `EngineConfig` sections (input … enrichment) | env vars, host settings |
| `pipeline.py` | `analyze_workbook` orchestration | host adapters |
| `cli.py` | `inspect/validate/analyze/export/inspect-output` commands | internal pipeline details leaking to callers |

## LLM policy

- Allowed during Phase A batch generation, never required (default
  `none` works fully offline).
- Never required for Phase B runtime querying.
- Isolated behind `KnowledgeEnrichmentProvider`; bounded inputs,
  structured outputs, validation before synthesis, no direct DB writes.
- No provider SDK in core dependencies; no API keys in core config.
- The output database is provider-independent (enrichment only fills
  `enriched_label` / extra inferred candidates + run metadata).

## Key design rules

1. **Traceability.** Every derived value points back to its source record
   (`record_id`, `equipment_code`). Normalization/inference outputs are
   always distinguishable from original source data.
2. **No silent repair.** The quality layer reports; it does not rewrite.
3. **Technical tree is primary for similarity.** Location tree and process
   tree are context, never similarity evidence (see `data-contract.md`).
4. **Failure mode ≠ failure mechanism.** Observed symptom text and the
   technical fault are separate fields, separate models, separate pipeline
   concerns.
5. **Scores are not probabilities.** See `algorithm-principles.md` and
   `domain/metrics.py`: historical rate, evidence score, confidence, and
   normalized probability are four different types.
6. **Provider independence.** Embeddings/LLMs sit behind protocols in
   `text/providers.py`. The core installs and runs without them.

## Isolation & extraction

This package is developed as if it lived in its own repository:

- No import of `open_notebook`, `api`, SurrealDB, FastAPI, or frontend code
  (enforced by `tests/test_package_boundary.py` via static import scan).
- No host configuration, environment variables, or data directories.
- Own `pyproject.toml`, own dev tooling config, own docs and tests.
- Synthetic test fixtures only; no real customer data in git.

**Extraction:** copy `packages/maintenance-troubleshooting-engine/` to a
new repository. Install with `pip install .`. Nothing else is required.

**Future integration:** the host application must consume this package
through a thin adapter (e.g. a service that calls `analyze_workbook` and
maps the returned `TroubleshootingKnowledgeBase` onto host DTOs). Host code
must not import `maintenance_troubleshooting` internals throughout the
codebase; only the adapter may touch the public API (`__init__` exports).
