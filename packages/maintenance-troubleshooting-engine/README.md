# Maintenance Troubleshooting Engine

Standalone Python package for mining maintenance-history workbooks and
generating evidence-driven troubleshooting guides.

> **Isolation contract.** This package knows nothing about the host
> application (Open Notebook / Maintenance AI Agent). It has no imports
> from `open_notebook`, `api`, or any host service; no SurrealDB, FastAPI,
> or frontend dependency; and it reads no host configuration or data
> directory. The host may call it through a thin adapter in a later
> milestone. See `docs/architecture.md` (Isolation & extraction).

## Installation

```bash
# Inside this repository (isolated virtualenv recommended):
cd packages/maintenance-troubleshooting-engine
uv venv
uv pip install -e ".[dev]"

# Or with pip (the package is self-contained):
pip install ./packages/maintenance-troubleshooting-engine
```

Requires Python >= 3.11. The only runtime dependency is `openpyxl`
(pure Python, for `.xlsx` input). All ML/AI providers are optional
interfaces, never hard dependencies.

## Quick start

```python
from maintenance_troubleshooting import EngineConfig, analyze_workbook

result = analyze_workbook("maintenance-history.xlsx")
print(result.quality_report.summary())
print(f"canonical records: {len(result.records)}")
```

With explicit configuration and column mapping:

```python
from maintenance_troubleshooting import (
    ColumnMapping,
    EngineConfig,
    analyze_workbook,
)

config = EngineConfig.default()
mapping = ColumnMapping.default().with_alias("equipment_code", ["MY_EQUIP_COL"])
result = analyze_workbook("history.xlsx", configuration=config, column_mapping=mapping)
```

## CLI

```bash
maintenance-troubleshooting --help
maintenance-troubleshooting inspect history.xlsx
maintenance-troubleshooting validate history.xlsx
maintenance-troubleshooting analyze history.xlsx
maintenance-troubleshooting export history.xlsx -o knowledge-base.json
```

## Layout

```text
src/maintenance_troubleshooting/
    __init__.py        # public API (analyze_workbook, domain models, config)
    cli.py             # inspect / validate / analyze / export
    config.py          # EngineConfig (input/normalization/similarity/...)
    pipeline.py        # orchestration + future evidence/ranking interfaces
    domain/            # Equipment, MaintenanceRecord, FailureMode, evidence,
                       #   causes, guides, probability/confidence metrics
    similarity/        # technical-tree similarity classification (structural,
                       #   not a final score)
    text/              # Persian-aware normalizer/tokenizer/canonicalizer,
                       #   provider-independent similarity + embedding interfaces
    quality/           # validation, duplicates, text-quality, consistency
    inputs/            # Excel reader, configurable column mapping, record IDs
    outputs/           # TroubleshootingKnowledgeBase (JSON-serializable)
tests/                 # synthetic fixtures only — no real customer data
docs/
    architecture.md
    data-contract.md
    algorithm-principles.md
```

## What the percentages mean

The engine reports cause support as percentages, e.g.
`Cause A — 62%`. Unless a methodology note says otherwise, that number is
a **normalized share of evidence weight**, not a calibrated real-world
probability. See `docs/algorithm-principles.md` and the `metrics` module.

## Development

```bash
cd packages/maintenance-troubleshooting-engine
pytest            # package tests (synthetic fixtures only)
ruff check src tests
mypy src
```

## Extraction

Copy the directory `packages/maintenance-troubleshooting-engine/` into a
new repository. It carries its own `pyproject.toml`, README, docs, tests,
and CLI entry point; nothing else in the host repository is required.
