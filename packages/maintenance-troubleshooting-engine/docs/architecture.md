# Architecture

## Pipeline

```text
Excel workbook (.xlsx)
  ↓
Input Adapter (inputs/excel.py)
  · configurable Persian column mapping
  · equipment codes preserved as identifiers
  · raw row values retained
  ↓
Canonical Records (domain/records.py)
  · one MaintenanceRecord per row
  · stable record IDs (inputs/record_ids.py)
  ↓
Data Quality (quality/)
  · validation, missing-field analysis, duplicates,
    text-quality assessment, failure-mode consistency
  · original data never silently repaired
  ↓
Text Processing (text/)
  · Persian-aware normalization / tokenization / canonicalization
  · provider-independent similarity + embedding interfaces
  ↓
Technical Similarity (similarity/)
  · structural classification of technical-tree overlap
  · extensible scorer interface (final ranking is a later milestone)
  ↓
Failure Analysis (domain/failure.py + future pipeline stages)
  · recorded failure mode vs observed symptom vs inferred mechanism
  ↓
Cause Evidence (domain/evidence.py, domain/causes.py)
  · every candidate cause points at its source records
  ↓
Troubleshooting Knowledge Base (outputs/)
  · JSON-serializable, UI-independent
  ↓
Output Adapter (outputs/ + CLI export)
```

## Module responsibilities

| Module | Owns | Must not |
|---|---|---|
| `domain/` | dataclasses for equipment, records, failures, evidence, causes, guides, metrics | import I/O, ML, or host code |
| `similarity/` | structural technical-tree classification + scorer protocol | final ranking weights |
| `text/` | normalization/tokenization/canonicalization + similarity/embedding protocols | any specific LLM/embedding SDK |
| `quality/` | validation and quality reports over canonical records | mutate source records |
| `inputs/` | Excel reading, column mapping, record-ID strategies | host paths, host config |
| `outputs/` | knowledge-base model + JSON serialization | UI or HTTP concerns |
| `config.py` | `EngineConfig` sections | env vars, host settings |
| `pipeline.py` | `analyze_workbook` orchestration + future evidence/ranking protocols | host adapters |
| `cli.py` | `inspect/validate/analyze/export` commands | internal pipeline details leaking to callers |

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
