# Troubleshooting frontend data layer (downstream)

Read-only frontend integration for the troubleshooting runtime API
(`GET /api/troubleshooting/...`, backend Milestone 4). No visible UI
exists yet — **UI placement and visual presentation are intentionally
deferred** until the user specifies where troubleshooting should appear.

## Files (all new, nothing existing modified)

```text
frontend/src/lib/api/troubleshooting.ts       # types + thin apiClient wrapper
frontend/src/lib/api/troubleshooting.test.ts  # endpoint/shape/error tests
frontend/src/lib/hooks/use-troubleshooting.ts # TanStack Query hooks
frontend/src/lib/hooks/use-troubleshooting.test.tsx  # keys/gating/state tests
```

Plus six `QUERY_KEYS` entries in `frontend/src/lib/api/query-client.ts`
(the only modified file). No routes, navigation, components, CSS, or
locale strings were added or changed.

## Placement rationale

`src/custom/` holds downstream *presentation* (screens, layout, theme).
A data-access layer is not presentation: the established architecture
places API clients in `src/lib/api/`, hooks in `src/lib/hooks/`, and
keys in `QUERY_KEYS` (see `tasks.ts` / `use-tasks.ts`, which this layer
mirrors). Introducing `custom/api` + `custom/hooks` would have created
a second data-access architecture, against the milestone's own
convention rule.

## API client

`troubleshootingApi` over the shared `apiClient` (auth, timeout, error
interceptor reused — no second client):

```text
getStatus() → TroubleshootingStatus
listEquipment() → TroubleshootingEquipment[]
getEquipment(code)
listFailureModes(code)
getGuide(code, failureModeId) → TroubleshootingGuide
listCauses(code, failureModeId)
listEvidence(code, failureModeId)
```

Types mirror the backend Pydantic models 1:1. `support_percent`,
`probability`, `confidence`, ranks, roles, and evidence `record_id`s
pass through untouched — the frontend never rescores.

## Hooks and query hierarchy

```text
useTroubleshootingStatus()
useTroubleshootingEquipment()
useTroubleshootingEquipmentDetail(code)   # disabled until code exists
useTroubleshootingFailureModes(code)      # disabled until code exists
useTroubleshootingGuide(code, modeId)     # disabled until both exist
useTroubleshootingCauses(code, modeId)    # disabled until both exist
useTroubleshootingEvidence(code, modeId)  # disabled until both exist
```

Keys nest under `['troubleshooting', ...]` mirroring the URL hierarchy,
so invalidating `['troubleshooting']` refreshes everything while leaf
queries cache independently. Standard 5-minute stale time applies; no
polling, no preloading, no mutations anywhere in this layer.

## State semantics for future UI

- `isPending` → loading; `isError` → request error (404s never retried,
  per the global query client).
- Empty array with `isSuccess` → genuinely no knowledge (distinct from
  loading and from error).
- `status.data.state` → `available` (reads can succeed) vs `missing` |
  `unreadable` | `incompatible` | `unavailable`. Use
  `isTroubleshootingAvailable(status)` as the gate; never collapse these
  into "no data".
- `guide.warnings` may contain
  `insufficient_historical_repair_evidence` — renderable as-is, no
  localization added in this milestone (stable identifiers only).

## Read-only contract

Proven at the HTTP boundary by test: all seven operations issue `GET`
and nothing else; the module surface contains exactly the seven getters.
The backend likewise opens the database with SQLite `mode=ro`.

## Future integration boundary

When placement is specified, build presentation under `src/custom/`
consuming only these hooks (and `isTroubleshootingAvailable`). Do not
bypass the hooks with direct `apiClient` calls from components, and do
not add mutations — troubleshooting knowledge is precomputed and
read-only by product design.
