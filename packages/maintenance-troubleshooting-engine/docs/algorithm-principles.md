# Algorithm principles

This document constrains *future* scoring/ranking milestones. It defines
what may be claimed — and what must not.

## 1. Evidence first, hallucination never

Historical maintenance records are the primary evidence. Technical-tree
similarity, text similarity, failure-mode consistency, cause association,
and repair descriptions are structured evidence sources. LLMs/embeddings
may later assist *extraction* and *semantic matching*; they must never
invent causes, actions, or percentages. Forbidden shortcuts:

- exact-string search dressed up as analysis;
- sending a whole workbook to an LLM and quoting the answer;
- LLM-invented troubleshooting steps;
- arbitrary percentages or arbitrary "similarity scores" presented as
  probabilities.

## 2. Four quantities, four types (`domain/metrics.py`)

| Quantity | Type | Meaning |
|---|---|---|
| Historical occurrence rate | `OccurrenceRate` | `count / total` over a stated record set. Descriptive only. |
| Evidence/support score | `EvidenceScore` | Heuristic combination of evidence components with a named method. A support weight. |
| Model confidence | `Confidence` | Self-reported certainty of a model/extractor with a stated basis. |
| Normalized cause probability | `CauseProbability` | Share of total evidence weight, summing to 1. Only via `normalize_probabilities`. |

A troubleshooting UI may display `Cause A — 62%`, but the attached
`probability_semantics` must say what it is. The default semantics:

> "Share of total evidence weight for this failure mode. Not a calibrated
> real-world probability."

Never label a heuristic as "probability" without recording the
normalization method that produced it.

## 3. Similarity is structural first, weights are configured

`similarity.classify_technical_similarity` yields categories
(`EXACT_EQUIPMENT` > `SAME_MODEL` > `SAME_MANUFACTURER_AND_TYPE` >
`SAME_EQUIPMENT_TYPE` > `SAME_SUBCLASS` > `SAME_MAIN_CLASS`, else
`UNRELATED`/`INDETERMINATE`). `SimilarityAnalyzer` maps categories to
support weights via `SimilarityConfig.technical_weights` (defaults
1.0 / 0.8 / 0.6 / 0.45 / 0.30 / 0.15 / 0.0 / 0.0) — an explicit,
configurable analytical hierarchy, not unexplained percentages. Every
evidence row stores its weight *and* its reason
(`same_manufacturer_and_model+same_failure_mode`, …).

Measured on real data (Sample-1): placeholder `"-"` technical trees
would have made unrelated equipment "similar" — placeholders are now
missing values, so such equipment compares as `INDETERMINATE`
(weight 0) while same-equipment evidence still counts at 1.0.

## 4. Failure mode vs mechanism

- **Failure mode** = what the operator observes
  (`machine does not start`, `axis does not reference`, …).
- **Failure mechanism** = the technical fault
  (`PLC failed to boot`, …).

The engine learns mode→mechanism links from repair descriptions,
technical trees, repeated cases, causes, and mechanisms — never by
merging the two fields.

## 5. Evidence hierarchy (implemented in the miners)

For a query like `Equipment = B104, Failure mode = Machine does not
start`, evidence is collected per (equipment, canonical-mode) scope from
same-mode records, weighted by technical similarity, roughly in this
order (implemented in `EvidenceMiner` + `CauseMiner`, each row keeping
its reason):

1. exact historical records for the equipment;
2. same model / highly similar technical tree;
3. same manufacturer and equipment type;
4. other technically similar equipment;
5. (reserved) semantically similar symptoms;
6. historically associated failure mechanisms;
7. historically associated causes;
8. repair actions associated with those causes.

Rung 5 (semantic symptom similarity beyond the canonical mode) is
reserved for the optional enrichment layer; the deterministic pipeline
uses canonical-mode membership. The ordering is explicit, configured,
and tested — not a hidden ranking.

## 6. Text mining stance (validated on real data)

Technician text is Persian/English mixed with model numbers, PLC/CNC
terms, axis/component names, abbreviations, spelling variation,
Arabic/Persian character differences, and incomplete sentences.
Normalization and canonicalization must be configurable and reversible in
effect (originals always retained); lexical similarity (`TokenSet`,
character n-grams) is a documented baseline, not a semantic claim.
Semantic (embedding) matching arrives behind `EmbeddingProvider` as an
optional enhancement with its own evaluation.

Real-data refinements (each justified by measured false merges/splits):

- Missing-value placeholders (`"-"`, `نامشخص`, …) normalize to missing
  everywhere — never clusters, mechanisms, or tree levels.
- Token Jaccard uses IDF weights over distinct mode wordings so generic
  words (مشکل، تعویض، error) cannot merge distinct failures; the
  `0.55` threshold is unchanged.
- Technical context only boosts pairs with lexical substance
  (`min_lexical_for_tech_boost = 0.35`).
- Disjoint parenthetical `(category)` tags never merge (tagless wordings
  may still join any cluster).
- Cause/action grouping is case-folded (`Axis Control System` ≡
  `Axis control system`); labels keep the most frequent raw variant.
- Action keyword matching is token-aware: keywords must occur as whole
  tokens (ASCII-only inflections `ed/d/s/es/ing` accepted; a single
  leading `و` conjunction is stripped), so `قطعه` never matches `قطع`;
  ZWNJ splits tokens, making `می‌شود` ≡ `می شود` at match time without
  rewriting stored text.
- Repair sentences shorter than `min_repair_length` (10) are rejected
  unless they name a known component/parameter (own-equipment tree,
  official aliases, or manufacturer-scoped induced terms, token-aware).
- Standalone closure phrasing yields history objects, never recommended
  actions; test-and-handover yields verification + handover event
  objects; all point at the verbatim source sentence.
