# M15 — Upstream v1.15.0 Differential Audit

Date: 2026-10-06. Auditor: OpenCode (read-only; no code changed in this batch).
No upstream fetch performed; no network use; synthetic reasoning only.

## 1. Audit scope

* Exact target: Open Notebook v1.15.0, release commit
  `315d5255af2a5132aada41c94d5c3c5dc8e837aa` — **not available locally**
  (`git cat-file` fails; no v1.15.x tag; fetch prohibited).
* Current fork commit: `9378af6` (Batch A key rotation).
* Upstream baseline actually used: local `upstream/main` tip `3127f14`
  (2026-09-13, = fork merge-base) plus locally present side branches
  (dependabot npm/uv/docker, `feat/design-polish`, `docs/design-system-record`,
  `codex/research-runtime-baseline`, `chore/maintainer-profile`,
  `fix/issue-1221-ask-max-tokens`). Side branches are directional evidence
  only and are NEVER substituted for the release.
* Limitation: anything that landed between tip and the release is
  unverifiable and is marked DEFERRED, never inferred.

## 2. Executive summary

```text
PORTED: 14
INTENTIONALLY_DIFFERENT: 7
NOT_APPLICABLE: 7
DEFERRED: 8
```

## 3. Complete change matrix

| Upstream area | v1.15.0 change (per brief / local evidence) | Current fork evidence | Classification | Notes |
|---|---|---|---|---|
| P0.1 credential encryption | PBKDF2, versioned, migrate endpoint | `encryption.py` fork-native `pbkdf2v1`+`pbkdf2v2` multi-key, endpoint, 39+21 tests | PORTED | Format is fork-native; no upstream byte-parity claimed |
| P0.3 empty model reply | Empty reply is an error | Guards in `chat.py`, `source_chat.py`, `transformation.py` + 9 tests | PORTED | Ask already had it via `cfdd16f`/`92120f6` |
| P0.4 empty transformation input | Refuse pre-LLM | `transformation.py` `InvalidInputError` guard + 7 tests | PORTED | Kept distinct from P0.3 output guard |
| P0.5 worker stall/deletion | Fail fast on deleted; DB errors retryable | `base.py get()` distinction + `source_commands` fail-fast + M19 reconcile | PORTED | `get_all` convention matched |
| P1.1 fail-once sources | Malformed sources fail immediately | `stop_on` ValueError + deleted→terminal (`387f6dd`) + 4 tests | PORTED | 15-attempt budget kept for genuine transients |
| P1.2 context-length | No 25-min retry | `ContextLengthExceededError` + `stop_on` in 3 workers + phase handling | PORTED | Includes custom LLM/repair workers |
| P1.3 Ask budget | 8192 shared budget | `ASK_MAX_TOKENS=8192` + think-truncation, byte-identical to tip | PORTED | Inherited from merged ask branch |
| P1.4 decoder/session | Chunk framing, badge persistence | Decoder verified + indicator restore (`use-source-chat.ts`) + 3 tests | PORTED | Badge part deferred, see §6 |
| P1.5 partial embeddings | No false-embedded | Chunk-count gate + empty/dedup/progress tests; per-batch bounded retry | PORTED | Verified present, no code needed |
| P1.6 UTF-8 passwords | Non-ASCII auth works | #1344 byte path + `_FILE` UTF-8 fix + 13 tests | PORTED | Browser header limits remain client-side |
| Auth base (#1344) | UTF-8 wire bytes compare | `api/auth.py`, in history | PORTED | — |
| Search/Ask notebook scope (#1331) | Scope to selected notebooks | `ask.py` `notebook_ids` threading intact | PORTED | Backend scoping inherited |
| brace-expansion 1.1.16 | Security bump (`e53be53`) | Same pin in fork `package.json` | PORTED | — |
| MiniMax provider | Provider addition | Identical `provider_registry.py` (zero fork diff) | PORTED | Inherited |
| axios `^1.18.1` vs branch `^1.20.0` | Dependabot direction (unmerged branch) | Fork stays `^1.18.1` | INTENTIONALLY_DIFFERENT | No advisory evidence locally; freshness alone banned as a reason |
| Quiet Green reskin (#1218/#1220) | Full UI reskin | Fork keeps Persian-first UI + databases UI; brief excludes reskin | INTENTIONALLY_DIFFERENT | Separate future project per brief |
| Credential KDF serialization | Unknown upstream bytes | Fork-native v1/v2 envelopes | INTENTIONALLY_DIFFERENT | Deliberate; documented |
| Timeout defaults | 180s recommendation | 60s esperanto default kept (operator-overridable), 600s UI ceiling | INTENTIONALLY_DIFFERENT | Measured decision, Batch 2 |
| M18/M19/M20 architecture | n/a (fork product core) | Scope insights, lifecycle, Persian policy | INTENTIONALLY_DIFFERENT | Protected by design |
| Migration numbering 26–32 | Fork-owned schema | Registered up/down pairs | INTENTIONALLY_DIFFERENT | Ownership, not drift |
| Search UI (#1331 surface) | Scoped search UI | Fork rewrote search page (Persian-first, −518/+?) | INTENTIONALLY_DIFFERENT | Product UI direction |
| Podcast fixes | Podcast changes | No podcast product customization in fork | NOT_APPLICABLE | Pre-existing env-only test failures unrelated |
| YouTube/CCORE vars | Ingest options | Not in maintenance product scope | NOT_APPLICABLE | — |
| ODT ingestion | Format support | Excel-driven product (`openpyxl` direct pin) | NOT_APPLICABLE | Revisit on CMMS demand |
| SiliconFlow/Z.ai | Provider additions | No product requirement | NOT_APPLICABLE | Registry pattern ready |
| oss-maintainer/research/chores | Side-branch work | Test/chore scaffolding | NOT_APPLICABLE | — |
| Docker node:26 | Builder image (unmerged branch) | Deployment choice, not product behavior | NOT_APPLICABLE | — |
| soupsieve 2.9 | Transitive bump (unmerged branch) | Lock at 2.8.4 both sides | NOT_APPLICABLE | Transitive of beautifulsoup; no advisory evidence locally |
| Exact release diff | `315d525` contents | Object unavailable; no fetch performed | DEFERRED | Blocks all byte-level parity claims |
| Next 16.3.8 | Brief-named floor | No local ref contains it (tip+branch: `^16.3.4`) | DEFERRED | Cannot verify or adopt |
| P1.4 provider/model badge | Badge metadata | No per-message authoritative identity; no UI/strings | DEFERRED | Contract not available; decoder work shipped |
| pyasn1 0.6.4 | Branch-only bump | Not inspected for applicability | DEFERRED | Branch observation only |
| v1.15.0 migration changes | Unknown | Cannot inspect release tree | DEFERRED | No evidence of any; fork set unchanged |
| OpenDocument/providers (if in release) | Unknown | Release tree unavailable | DEFERRED | Covered by NOT_APPLICABLE rows if absent |
| Iteration-count upper bound | Own hardening note | Parser accepts any positive int | DEFERRED | Not upstream-derived; needs policy decision |
| Key rotation UX/docs | Operational procedure | Code+endpoint shipped; runbook prose minimal | DEFERRED | Docs can follow without code risk |

## 4. Previously tracked roadmap — final status

P0.1 IMPLEMENTED (`37c06dd` + rotation `9378af6`); P0.2 NO_CHANGE_REQUIRED;
P0.3/P0.4/P0.5/P1.2/P1.6 IMPLEMENTED; P1.1 IMPLEMENTED (`387f6dd`);
P1.3 VERIFIED_EXISTING; P1.4 decoder/session IMPLEMENTED, badge DEFERRED;
P1.5 VERIFIED_EXISTING; P1.7 NO_CHANGE_REQUIRED (keep 60s, decision A);
M18/M19/M20 IMPLEMENTED (protected, green).

## 5. Newly discovered gaps (not in the previous shortlist)

1. **axios `^1.20.0` dependabot pin** (unmerged branch; fork `^1.18.1`):
   real upstream direction, but no advisory text locally → record as
   DEFERRED/INTENTIONALLY_DIFFERENT, adopt only with CVE evidence.
2. **soupsieve 2.9 / node:26 / pyasn1** (unmerged branches): observations
   only; transitive/infra, no action.
3. **Quiet Green reskin scope** (`#1218`/`#1220`, 140+ files): the largest
   upstream delta discovered; excluded by brief, recorded so it is never
   mistaken for drift.
4. **Search-scope #1331 split**: backend inherited, UI intentionally
   rewritten — prevents a future false "regression" claim.
5. **Iteration-count upper bound**: own hardening note from review, not an
   upstream gap; needs a policy decision, not code in this batch.

## 6. Deferred items

Per-row reasons in §3. Common thread: the release object is unavailable, so
release-conditional items (exact pins, exact bytes, migration contents) stay
DEFERRED; product-judgment items (badge, timeout default, axios freshness)
stay intentionally unadopted with evidence cited.

## 7. Security/data findings

This audit performed zero writes: no services started, no migrations run,
no secrets read or transmitted (synthetic reasoning only), no `.env`/data/
database/runtime contact, no installs. No secret, user, application, or
machine-specific data entered any artifact created in this batch.
