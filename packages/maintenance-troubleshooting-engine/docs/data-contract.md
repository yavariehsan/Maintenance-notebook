# Data contract

## Source workbook

One row = one maintenance/repair record. The same equipment appears in
many rows. The workbook is assumed UTF-8-compatible `.xlsx` with a header
row; exact headers may vary, hence every canonical field accepts a list of
aliases (see `inputs.ColumnMapping`).

> **Equipment identity (confirmed for this milestone):** the stable
> equipment identifier is **کد فرایندی** (e.g. `B104`), always treated as
> a string — never converted to an integer, leading zeros and formatting
> preserved. One equipment owns many maintenance records; records are
> never collapsed. `تجهیز` is the display name (and a legacy fallback
> alias for the code when `کد فرایندی` is absent).

## Canonical fields and default Persian headers

| Canonical field | Default header(s) | Required |
|---|---|---|
| `equipment_code` | کد فرایندی، کد تجهیز، کد دستگاه، تجهیز (legacy fallback) | yes |
| `equipment_name` | تجهیز، نام تجهیز | no |
| `request_prefix` | پیشوند درخواست | yes |
| `request_number` | شماره درخواست | yes |
| `repair_unit_code` | کد واحد تعمیراتی | no |
| `process_name` | فرایند | no |
| `request_type` | نوع درخواست | no |
| `stage` | مرحله | no |
| `request_description` | شرح درخواست | no |
| `repair_description` | شرح تعمیر | no |
| `failure_mode` | حالت خرابی | no |
| `proposed_failure_mode` | حالت خرابی پیشنهادی | no |
| `failure_mechanism` | مکانیزم خرابی | no |
| `defect_cause` | دلیل بروز عیب | no |
| `defect_cause_detail` | توضیحات دلیل بروز عیب | no |
| `referral` | ارجاع | no |
| `referral_reason` | دلیل ارجاع | no |
| `technical_tree` | درخت تکنیکال | no |
| `location_tree` | درخت موقعیت | no |
| `process_tree` | درخت فرایند | no |
| `t1`…`t11` | t1…t11 | no |
| `repair_start_year/month/date/time` | سال/ماه/تاریخ/زمان شروع تعمیر | no |
| `test_start_year/month/date/time` | سال/ماه/تاریخ/زمان شروع تست | no |
| `request_year/month/date/time` | سال/ماه/تاریخ درخواست (+ساعت درخواست) | no |
| `test_end_year/month/date/time` | سال/ماه/تاریخ پایان تست (+زمان پایان تست) | no |
| `expected_delivery_year/month/date/time` | سال/ماه/تاریخ/زمان تحویل پیش بینی شده | no |
| `repair_end_year/month/date/time` | سال/ماه/تاریخ/زمان پایان تعمیر | no |
| `predicted_duration` | پیش بینی مدت انجام کار | no |
| `eir_proposal` | پیشنهاد بهبود جهت جلوگیری از بروز مجددخرابی (EIR) | no |
| `eir_approved` | آیا EIR پیشنهادی تکنسین مورد تایید است؟ | no |
| `report_quality` | کیفیت گزارش | no |
| `repair_quality` | کیفیت تعمیر | no |
| `work_time` | زمان انجام کار | no |
| `deletion_reason` | دلیل حذف برگه | no |
| `safety_notes` | خطرات بالقوه/ملاحظات ایمنی/ | no |
| `issue_bank_recorded` | ثبت در بانک مساله | no |
| `parameter_change` | تغییر در پارامترهای سیستم | no |
| `parameter_change_detail` | توضیحات تغییر در پارامترهای سیستم | no |
| `bypass` | Bypass | no |
| `bypass_detail` | توضیحات Bypass | no |
| `registered_by` | کاربر ثبت کننده | no |
| `delay_cause` | علت تاخیر | no |
| `total_man_hours` | جمع نفر ساعت | no |
| `stop_time` | STOP TIME | no |

Any header not in the mapping is preserved verbatim in
`MaintenanceRecord.raw` / `extra` — unknown columns are never dropped.

## Identity rules

- **Record ID** (default): `{request_prefix}-{request_number}`, e.g.
  `B-101`. Strategy is pluggable (`inputs.RecordIdStrategy`); the
  original prefix/number fields are always preserved. Rows without a
  usable prefix/number get a deterministic `ROW-<sheet>-<row>` fallback
  ID plus a reported row problem — never silently discarded.
- **Equipment codes are identifiers, never numbers.** `B104`, `H13`,
  `M210` (or a numeric-looking `210`) are preserved as exact strings;
  numeric Excel cells are coerced without loss (`210.0` → `"210"`).

## Technical tree (t1…t5)

Conceptual hierarchy (values/naming preserved verbatim from the workbook):

```text
t1  main equipment class
t2  sub class
t3  equipment type
t4  manufacturer
t5  model
```

`t6`…`t11` are retained as extra levels, not similarity dimensions.
Structural classification (`similarity.classify_technical_similarity`)
produces categories (`EXACT_EQUIPMENT` … `UNRELATED`, plus
`INDETERMINATE` when levels are missing) — a classification, not a score.

**Explicitly not similarity evidence:** location tree (`درخت موقعیت`),
process tree (`درخت فرایند`), factory/workshop position.

## Failure-mode mining

The literal `حالت خرابی` value is never the final mode. Normalized mode
texts (recorded or proposed) are clustered with deterministic union-find
over `lexical_weight × max(token-jaccard, char-trigram-jaccard)` plus
`tech_context_weight × t1..t3 agreement` (thresholds configurable).
Modeless records attach via symptom similarity or become explicit
`unclassified` singletons. Each record keeps its original / normalized /
canonical triple; an optional enrichment provider may add an
`enriched_label` without touching the originals.

## Cause and repair-action mining

- Causes group scope evidence by normalized text from `دلیل بروز عیب`
  (`explicitly_recorded`) and `مکانیزم خرابی` (`technical_mechanism`);
  identical texts merge with both kinds recorded.
- Repair sentences split on line/punctuation boundaries, classify into a
  documented Persian/English taxonomy (inspect … restore), and take a
  heuristic role (diagnostic / corrective / verification-after-corrective
  / observed_issue). Sparse records yield no actions; guides then carry
  `insufficient_historical_repair_evidence` instead of invented steps.

## Support percentage (similarity-weighted share)

```text
support_percent(cause) =
    100 × Σ weights of the cause's supporting evidence
        / Σ weights of all usable scope evidence
```

Weights are the technical-similarity weights of the evidence equipment
(defaults: exact 1.0, same model 0.8, same manufacturer+type 0.6, same
type 0.45, subclass 0.30, main class 0.15, unrelated/indeterminate 0.0 —
all configurable). Percentages are independent per cause (one record can
support both its cause and its mechanism) and are stored with
`evidence_count`, `weighted_evidence`, `denominator`, and
`calculation_method`, so every number reproduces exactly. They are shares
of evidence weight, not calibrated probabilities; normalized
probabilities (summing to 1) are derived separately via
`normalize_probabilities`.

## Confidence (`evidence-count-v1`)

`high` (≥5 records, denominator ≥4), `medium` (≥3, ≥2), `low` (≥1),
`insufficient` (none) — thresholds configurable, basis recorded on every
cause alongside (not merged with) support and similarity.

## Domain schemas

- `Equipment`: stable `equipment_code` + technical identity
  (`main_class`, `sub_class`, `equipment_type`, `manufacturer`, `model`,
  `technical_tree`). No location fields by design.
- `MaintenanceRecord`: one row; explicit typed fields + `raw` (every
  source cell) + `extra` (unmapped columns). Raw source stays traceable.
- `FailureMode` / `FailureMechanism` / `FailureInterpretation`: recorded
  vs observed vs inferred, each with provenance.
- `RepairEvidence`: relevance basis + repair action + cause + mechanism +
  `record_id` + `equipment_code`.
- `TroubleshootingCause`: cause + evidence + `OccurrenceRate` +
  `SupportBreakdown` + `EvidenceScore` + `Confidence` + optional
  normalized `CauseProbability` + recommended actions.
- `TroubleshootingGuide`: equipment + failure mode + ordered candidates +
  actions + evidence + `probability_semantics` (honest label).
- `TroubleshootingKnowledgeBase`: versioned, JSON-serializable output;
  see `outputs/`.

## Output shape (conceptual)

```text
equipment
    failure modes
        symptoms
        candidate causes
            support percentage (documented semantics)
            evidence (source record IDs)
            recommended repair actions
        source maintenance records
```
