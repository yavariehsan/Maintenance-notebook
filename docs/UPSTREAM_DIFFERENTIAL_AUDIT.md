# Upstream Differential Audit — open-notebook v1.15.0 vs Maintenance-notebook fork

Date: 2026-10-11. Method: read-only Git-object comparison (release tag now
available locally after an authorized fetch; no merges, no code changes).

## 1. Baseline

* Upstream release: `lfnovo/open-notebook` tag `v1.15.0` = `315d525`
  (`chore(release): v1.15.0 (#1455)`, 2026-10-04). Verified by tag + message.
* Fork HEAD at audit time; merge-base with upstream: `3127f14` (2026-09-13).
* Upstream range audited: `3127f14..315d525` (42 commits).
* Limitation: none material — the exact release tree is present. Statements
  about *intent* (why upstream chose something) remain inferences.

## 2. Summary counts

```text
PORTED: 14
PARTIALLY_PORTED: 7
MISSING: 5
INTENTIONALLY_DIFFERENT: 8
NOT_APPLICABLE: 9
DEFERRED: 4
```

## 3. Change table

| Upstream change | Evidence | Fork evidence | Class | Notes |
|---|---|---|---|---|
| PBKDF2 creds `2866a9d` (#1360) | fixed app salt, `pbkdf2v1:<fernet>`, migrate endpoint, ADR-009 | fork-native per-record salt + v1/v2 multi-key + same endpoint shape | PORTED | Fork salt design is strictly stronger; no byte-parity claimed |
| Empty reply `86454db` (#1427) | `IncompleteGenerationError`, checkpoint rollback, `extract(None)→""`, stream passthrough | graph guards with `ExternalServiceError`; no rollback/helper/subtype | PARTIALLY_PORTED | Missing: subtype, failed-turn rollback (retry duplicates question), None-input handling |
| Empty-source refusal `5f021c5` (#1425) | worker+router guard | graph-level guard covering both paths | PORTED | Different layer, equivalent coverage |
| Truncated/empty output `e5e6313` (#1385) | new exception + worker handling | empty-output guard only; no truncation detection | PARTIALLY_PORTED | Truncation (mid-stream cut) not detected |
| Partial embeddings `93e0890` (#1424) | DELETE partials on insert failure | pre-insert count gate | PARTIALLY_PORTED | Complementary mechanisms; fork lacks post-failure cleanup |
| Source-chat streaming `2aa5872` (#1423) | stream only newest answer + badge restore | badge restore done; backend streams full history | PARTIALLY_PORTED | History re-stream appends into the live bubble until refetch replaces it |
| Worker deletion `90c6fed` (#1364) + ADR-013 | `get()` NotFound vs DatabaseOperationError split | byte-different, semantically identical split + fail-fast + reconcile | PORTED | Convergent implementation with own tests |
| Timeout 180s `a917bbf` (#1441) | `ensure_llm_timeout_default()` at import | 60s default kept, operator-overridable | INTENTIONALLY_DIFFERENT | Measured keep-60 decision stands; mechanism documented as pattern |
| Ask 8192 + think fixes | `cfdd16f`, `92120f6` (merged pre-base) | byte-identical | PORTED | — |
| Auth UTF-8 #1344 | byte-path fix | Present + `_FILE` hardening | PORTED | — |
| Search scope #1331, ask budget, search fix #1345 | Pre-base merges | Inherited where fork didn't rewrite | PORTED | Search UI itself rewritten (below) |
| Search UI rewrite (fork) | n/a | Persian-first UI, −518/+ page | INTENTIONALLY_DIFFERENT | Product direction |
| Quiet Green (#1218/#1220) | 140+ file reskin on side branch | Not adopted; brief excludes it | INTENTIONALLY_DIFFERENT | Future project, not drift |
| Fork product core (M18/M19/M20, databases UI, Persian policy, migrations 26–32, openpyxl pin) | n/a | Protected by design | INTENTIONALLY_DIFFERENT | 6 rows collapsed here |
| Credential serialization | Unknown upstream bytes vs fork v1/v2 | Deliberate fork-native format | INTENTIONALLY_DIFFERENT | Stronger salt model |
| MiniMax base provider | In tip + fork identically | Zero fork diff | PORTED | TTS/M3 voices below |
| MiniMax TTS/M3 `02870a7`, SiliconFlow/Z.ai `ed6b40e` | Provider additions post-base | Absent; no product requirement | MISSING | Low priority; registry pattern ready; adopt only on requirement |
| OpenDocument `4aadf88` + content-core 2.2 | ODT accept + env docs | content-core 2.0.7, no ODT | MISSING | Gated on content-core 2.x upgrade assessment |
| Typed extraction errors `5d6f51e` | `source.py` rework + 150-line tests | Old error mapping | MISSING | Same content-core gate; 118-line rework, needs careful port |
| Batch inserts `5d61841` | Single-connection bounded batches | Per-call connections, no batch helper | MISSING | Perf-relevant for bulk repair imports; adopt helper only |
| Cleared description `6b4c1f9` | Persist cleared text | Backend handles `""`; frontend sender unverified | PARTIALLY_PORTED | Verify TransformationEditorDialog/NotebookHeader send `""` vs `undefined` |
| order_by validation `5bba1f3` | Shared `_validate_order_by` | Inline allowlist in `notebooks.py` | PORTED | Equivalent, different shape |
| Insights-after-generation `4e390a7` | Polling UI | `insights.ts` polling present | PORTED | Functionally present |
| Ruff format gate `e2a76dd` | Format + CI gate | `ruff check`+mypy gated; no format section | PARTIALLY_PORTED | Adopting format = whole-tree reformat; defer deliberately |
| npm 38 updates `be03e57` / axios `^1.20.0` / next `^16.3.8` (branch evidence) | Security/feature bumps | Fork `^1.18.1` / `^16.3.4` | MISSING | Now concrete (was DEFERRED): axios/next/react pins known; needs compat-tested bump batch |
| soupsieve/pyasn1/uv/docker `d521eb7`, `e53be53`-remainder, `59e103d`, `553fdea`, `f88b1e5`, `36408a6` | Transitive/infra bumps | At tip levels | DEFERRED | Transitive-only; adopt with the axios/next batch after advisory check |
| Podcasts `2c62064`, `6f56513`, `60e3c21` | TTS prompts, speaker profiles | No podcast product customization | NOT_APPLICABLE | — |
| Crawl4AI/YouTube/CCORE | env knobs | Out of maintenance scope | NOT_APPLICABLE | Token doc already inherited |
| Maintainer profile/research/changelog/docs/design/ADR-admin | Chores/docs | No functional effect on fork | NOT_APPLICABLE | 5 rows collapsed here |
| Iteration-count upper bound | Own hardening note | Parser accepts any positive int | DEFERRED | Policy decision, not upstream-derived |
| Rotation runbook prose | Operational docs | Code+endpoint shipped | DEFERRED | Docs-only follow-up |

## 4. Previously tracked roadmap — final status

P0.1/P0.3/P0.4/P0.5/P1.1/P1.2/P1.6 IMPLEMENTED; P1.3/P1.5 VERIFIED_EXISTING;
P0.2 NO_CHANGE_REQUIRED (with the new exception below); P1.4 badge DEFERRED;
P1.7 keep-60 INTENTIONALLY_DIFFERENT; M18/M19/M20 intact.

## 5. Newly discovered gaps (not in the previous shortlist)

1. **axios `^1.20.0` / next `^16.3.8` / react `^19.3.0`** (branch
   `all-npm-dc810b5271`): first concrete pins — upgrades P0.2 from
   DEFERRED to actionable MISSING. Needs compat-tested bump batch
   (provider adapters, build, full suites).
2. **`IncompleteGenerationError` subtype + checkpoint rollback** (`86454db`
   remainder): failed chat turns leave the question in history; retry
   duplicates it. Small, high-value port.
3. **Stream-only-newest-answer** (`2aa5872` remainder): live bubble
   concatenates history until refetch. Small backend fix.
4. **Truncation detection** (`e5e6313` remainder): mid-stream cuts
   currently pass as valid output.
5. **Partial-embedding cleanup** (`93e0890` remainder): delete-partials
   complements the count gate.
6. **Batch inserts** (`5d61841`): adopt helper for bulk paths.
7. **content-core 2.2 gate** (`4aadf88`, `5d6f51e`, `59e103d`): one
   upgrade assessment unlocks ODT + typed errors; do not cherry-pick the
   rework onto 2.0.7.
8. **Quiet Green scope** (`#1218`/`#1220`): recorded as excluded so it is
   never mistaken for drift.

## 6. Deferred items

Per-row reasons in §3. Common rule applied: no evidence → DEFERRED, never
assumed. Transitive-only bumps wait for the axios/next batch's advisory
check; badge/timeout/format stay deliberately unadopted with reasons.

## 7. Security/data findings

Read-only audit (plus the authorized fetch): no services started, no
migrations run, no secrets read or transmitted, no `.env`/data/database/
runtime contact. Test constants referenced are short synthetic fixtures.

## 8. Recommended implementation order

1. `IncompleteGenerationError` + rollback + stream-newest (small, user-visible correctness).
2. Truncation detection + embedding cleanup + batch inserts (correctness/perf, same areas).
3. content-core 2.2 assessment → ODT + typed errors (dependency-gated).
4. axios/next/react bump batch with full compat testing.
5. Cleared-description sender check; ruff-format adoption decision.
6. Provider additions only on product requirement; badge only on contract.

## 9. Limitations

Side-branch pins (axios/next) are directional, not release verdicts; the
v1.15.0 tree itself was compared commit-by-commit for the 42-commit range,
so release coverage is complete for functional changes. Upstream *intent*
statements are inferences. Fork UI areas rewritten wholesale (search page)
were compared structurally, not line-by-line.
