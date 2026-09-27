# Pilot knowledge-quality review (Milestone 9)

Validation — not feature — milestone. Question answered here is not "does
the software run" (Milestones 6–8) but "does the generated troubleshooting
knowledge accurately represent the historical evidence and guide repairs".

No domain-expert review was performed; domain-validity judgments below are
explicitly marked as requiring expert confirmation.

## Method

- Native Windows stack only (SurrealDB 2.6.5, `uv run` API, native
  `surreal-commands` worker, no Docker/WSL): upload real
  `E:\Project\Sample\Sample-1.xlsx` (unmodified, 682196 bytes) through
  the production Repair Reports workflow → worker analysis → SQLite DB
  → runtime API reads.
- Deterministic rule-based sample (no cherry-picking): top-3 modes by
  records, 3 rare (≤2 records), top-2 by evidence, weakest-2 by
  evidence, top-2 by cause count, 2 fewest-cause, top-2 by action
  count, same-equipment multi-mode pair, 2 model-family-similarity
  scopes (cross-equipment `same_technical_model` /
  `same_manufacturer_and_type` evidence). Dedup by (equipment, mode).
  Result: 11 guides (B112-heavy: it owns the most modes; FM-0134 spans
  C40/C32/B138/B112).
- Per guide: causes (kinds/support/probability/confidence), linked
  actions (role/frequency), evidence excerpts, safety, symptom text,
  plus an independent support recomputation
  (`100·Σweights/denominator`) against stored values.
- Human-review artifact (per-guide detail) was generated to disposable
  TEMP during validation and deleted afterward; it is not committed.

## Dataset facts

1706 records → 13 equipment, 277 failure modes, 3919 causes, 20493
repair actions, 615 guides. Integrity: 0 orphan evidence, 0 broken
cause/action links, 0 duplicate record IDs. Repair descriptions are
never blank (0%); failure mechanism blank in 64%; technical tree empty
in 64%; model (t5)/manufacturer (t4) missing in 64%; 65% of scopes are
singletons; safety notes 0 (source has no safety column — expected).

## Findings (classified)

1. **Support/probability math exact** — recomputed top-cause support
   matches stored values to 6 decimals on all 11 sampled guides.
   → software correctness confirmed.
2. **Provenance intact** — every evidence row resolves to a real record
   with namespaced IDs; no orphans. → software correctness confirmed.
3. **Similarity dimensions clean** — evidence uses exact-equipment,
   technical model/class/type and manufacturer+type only; zero
   location/process references (also verified in code: those trees are
   parsed/stored but never consumed by similarity or mining).
   → software correctness confirmed.
4. **No false merges found** — FM-0134 symptoms are tool-change faults
   across the fleet (coherent cross-equipment mode; per-equipment
   weights differ honestly). Near-duplicate labels stay separate where
   they should (X-axis vs Y-axis faults, tool vs pallet change).
   → expected behavior.
5. **Action-text debris (1.4%)** — 295/20493 repair actions are bare
   numbers ("16", "2"), uniformly role-labeled `observed_issue` at
   frequency 1. Cosmetic noise, honestly labeled, never a sole
   recommendation. → data-quality issue; candidate improvement only
   (minimum action-text floor needs re-validation, deferred).
6. **Generic cause-code dominance** — "8- استهلاک قطعه یدکی" is the top
   cause in most guides (up to 459 occurrences) because technicians
   reuse a small cause vocabulary; per-scope support is computed
   honestly from mode-scoped evidence (e.g. 72.2% on 217 records vs
   48.6% on 6). Guides are truthful but less discriminating.
   → data-quality issue (source coding practice), not a software
   defect. Candidate: surface mode-specificity (future milestone).
7. **Singleton guides are thin but honest** — e.g. support 100% /
   probability 1.0 with confidence 0.30 on a single record; confidence
   correctly signals weakness. → expected behavior.
8. **Insufficiency flag unreachable on this dataset** — the runtime
   derives it only when zero causes have linked actions; all 615
   scopes have ≥1. The guard is correct (synthetically tested) but
   never fires here. → expected behavior; noted.
9. **Confidence follows the evidence-count rule visibly** (0.9 on
   well-supported causes, 0.3 on singletons). → software correctness
   confirmed.

No confirmed software defects were found. No engine, API, or UI code
was changed for knowledge-quality reasons.

## Candidate improvements (prioritized, none implemented)

1. Action-text quality floor (strip pure-numeric/single-token debris
   from the *procedure* view or mining) — needs engine change +
   re-validation; future milestone.
2. Mode-specificity signal for ubiquitous generic causes — needs
   engine change; future milestone.
3. Single-record caveat in the UI beyond confidence 0.3 — UI-only;
   future milestone after expert input.
4. Domain-expert review of the 11-guide artifact using the documented
   sampling rules — requires a maintenance expert; blocks any claim of
   domain validity, not production use of the tooling.

## Production conclusion

- Demonstrated: native E2E (upload 0.7s, preview 0.9s, submit 0.3s,
  engine ~26s for 1706 records, guide retrieval 0.2s, 24.7 MB DB);
  exact support math; intact provenance; clean similarity dimensions;
  coherent fleet-wide modes; honest confidence on thin evidence.
- Remains unverified: domain-expert usefulness judgment; behavior on
  larger/multi-format corpora; `.env` BOM re-save; frontend visual
  review beyond automated tests.
- Blockers: none found in tooling. The report states no subjective
  quality score: the knowledge is a faithful, traceable presentation
  of the historical evidence, with source-data limitations (generic
  cause coding, terse repair texts, missing technical trees) openly
  carried through rather than hidden.
