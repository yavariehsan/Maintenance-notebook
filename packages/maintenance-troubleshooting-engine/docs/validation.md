# Real-data validation (Milestone 3)

Validates the engine against an external maintenance-history workbook
without committing the workbook, generated databases, or reports.
All paths below are examples — point them at any workbook.

## 1. Profile the workbook (read-only)

```bash
maintenance-troubleshooting inspect /path/to/history.xlsx
```

Check sheets, headers, unmapped columns (typos like `توع درخواست`
are covered by aliases — extend `ColumnMapping` if new variants appear).

## 2. Split at equipment level (never rows)

```bash
maintenance-troubleshooting split /path/to/history.xlsx \
    --test-fraction 0.2 --seed 42 \
    --train-out /tmp/m3/train.xlsx --test-out /tmp/m3/test.xlsx \
    --split-out /tmp/m3/split.json
```

One equipment's whole history goes to train *or* test (leakage would let
the model see the same equipment on both sides). The command refuses to
write on leakage and records the exact seed, strategy, and composition
in `split.json`. With very few equipment (e.g. <10), say so explicitly
instead of pretending the split is statistically meaningful.

## 3. Generate the training knowledge base

```bash
maintenance-troubleshooting analyze /tmp/m3/train.xlsx \
    --output /tmp/m3/train.db
```

Atomic (tmp → integrity validation → replace). Record the wall time for
future dataset comparison (offline batch: correctness first).

## 4. Build the validation report

```bash
maintenance-troubleshooting report /tmp/m3/train.xlsx \
    --database /tmp/m3/train.db \
    --output-dir /tmp/m3/report \
    --split-json /tmp/m3/split.json \
    --test-workbook /tmp/m3/test.xlsx
```

Produces `validation-report.json` (machine-readable) and
`validation-report.md` (human inspection): dataset/quality/equipment/
modes/causes/actions/guides summaries, split + leakage proof, held-out
association rates (proxy labels, not ground truth), suspicious cases
(generic causes, fallback IDs, unclassified modes, insufficient-repair
guides), a support-percentage self-audit (every percentage recomputed
from evidence rows; any mismatch fails the audit), and limitations.

## 5. Inspect guides manually

```bash
maintenance-troubleshooting inspect-output /tmp/m3/train.db --equipment B104
```

Trace representative records (high/low frequency modes, sparse repair
text, mixed-language text, questionable labels) back to source rows via
`record_id` before trusting aggregates.

## 6. Determinism

Re-run step 3 and compare table dumps excluding `analysis_runs`
(timestamps). The default `none` enrichment path must be byte-identical.

## Reference results (Sample-1, 1706 rows, 13 equipment, seed 42)

- Split: 10 train equipment (1335 rows) / 3 test (371 rows), zero leakage.
- Train knowledge: 269 failure modes, 504 guides, 1949 causes.
- Support self-audit: 1949/1949 exact, 0 mismatches.
- Held-out association: 257/371 equipment matched, 253/371 modes matched,
  159/371 recorded-cause hits (proxy labels; misses are traceable, e.g.
  unseen technical trees or scope-specific cause sets — not errors).
- Real-data fixes this process produced: placeholder-as-missing,
  IDF-weighted token similarity, parenthetical-tag blocking, lexical
  floor for technical boosts, case-folded cause/action grouping.

## Why no LLM by default

The deterministic pipeline already produces coherent, traceable guides
on real data (see reference results). An LLM is therefore not required
for quality, and the default stays `none`: fully offline, deterministic,
and dependency-free. `KnowledgeEnrichmentProvider` remains the isolated
extension point if a future dataset demonstrates a specific gap
(canonical naming, synonym consolidation) that deterministic rules
cannot close — any such use must stay in Phase A, return structured
validated output, and never write the database directly.
