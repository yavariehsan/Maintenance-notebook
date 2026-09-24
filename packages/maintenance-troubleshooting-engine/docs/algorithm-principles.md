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

## 3. Similarity is structural first

`similarity.classify_technical_similarity` yields categories
(`EXACT_EQUIPMENT` > `SAME_MODEL` > `SAME_MANUFACTURER_AND_TYPE` >
`SAME_EQUIPMENT_TYPE` > `SAME_SUBCLASS` > `SAME_MAIN_CLASS`, else
`UNRELATED`/`INDETERMINATE`). Categories are *not* scores and *not*
weights. Mapping categories to numeric support is a separate, testable
decision owned by a future `CauseRanker` implementation.

## 4. Failure mode vs mechanism

- **Failure mode** = what the operator observes
  (`machine does not start`, `axis does not reference`, …).
- **Failure mechanism** = the technical fault
  (`PLC failed to boot`, …).

The engine learns mode→mechanism links from repair descriptions,
technical trees, repeated cases, causes, and mechanisms — never by
merging the two fields.

## 5. Intended evidence hierarchy (interfaces only)

For a query like `Equipment = B104, Failure mode = Machine does not
start`, later milestones should consider evidence roughly in this order
(exposed as composable `EvidenceSource` implementations, ranked by a
`CauseRanker` with an explicit, tested ordering contract):

1. exact historical records for the equipment;
2. same model / highly similar technical tree;
3. same manufacturer and equipment type;
4. other technically similar equipment;
5. semantically similar symptoms;
6. historically associated failure mechanisms;
7. historically associated causes;
8. repair actions associated with those causes.

This list is an interface roadmap, not an implemented ranking.

## 6. Text mining stance

Technician text is Persian/English mixed with model numbers, PLC/CNC
terms, axis/component names, abbreviations, spelling variation,
Arabic/Persian character differences, and incomplete sentences.
Normalization and canonicalization must be configurable and reversible in
effect (originals always retained); lexical similarity (`TokenSet`,
character n-grams) is a documented baseline, not a semantic claim.
Semantic (embedding) matching arrives behind `EmbeddingProvider` as an
optional enhancement with its own evaluation.
