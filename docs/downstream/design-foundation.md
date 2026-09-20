# Downstream design/product foundation

Downstream companion to [ADR-downstream-001](../7-DEVELOPMENT/decisions/ADR-downstream-001-customization-boundary.md)
(customization boundary) and the [native Windows baseline](./native-windows-baseline.md).
Status: foundation for product work. Nothing in sections 7–8 is implemented.

## 1. Current downstream UI architecture (implemented)

- Boundary `frontend/src/custom/`: `theme/tokens.css`, `layout/` (`CustomShell`,
  `CustomSidebar`, centralized `navigation.ts`), `screens/{notebooks,sources,
  search,settings,models,podcasts}/`.
- Six thin route adapters under `frontend/src/app/(dashboard)/` render the
  screens verbatim; `AppShell` delegates to `CustomShell`.
- Reused upstream, never duplicated: API clients, TanStack Query hooks, SSE
  (`useAsk`), Zustand stores, dialogs, `SettingsForm`, `ProviderSection`,
  `EpisodesTab`/`TemplatesTab`, all `components/ui` primitives.
- Upstream-owned files changed since the fork: 6 adapters, one `layout.tsx`
  import line, `AppShell` delegation, one locale-test timeout. No changes to
  `globals.css`, primitives, `AppSidebar`, manifests, hooks, or backend.
- Validation standing: lint 0 errors, full vitest suite green, production
  build clean. No browser/visual runner exists.

## 2. Design/token principles

- Custom tokens (`--custom-*`) alias upstream raw palette entries; both `:root`
  and `.dark` follow the document-root convention. Diverge a token only when
  downstream needs its own treatment — never duplicate `globals.css`.
- Screens use `bg-[var(--custom-page)]` / `text-[var(--custom-foreground)]` /
  `border-[var(--custom-border)]` for page containers; feature internals keep
  upstream utilities. No raw hex/rgb or hardcoded light/dark colors in `custom/`.
- Typography, radii, and shadows follow upstream (`font-display`, 4–6px,
  hairline borders). Page titles are `text-2xl` (search keeps its inherited
  responsive `text-xl md:text-2xl` variant).

## 3. Layout/composition principles

- Screen = `AppShell` > scroll container > `p-6` content. States required per
  screen: loading, error (+retry where a mutation exists), empty, populated.
- Keep upstream responsive breakpoints and collapse behavior; preserve
  keyboard/focus semantics of reused components.

## 4. Navigation principles

- `navigation.ts` is the single downstream nav model (keys resolved via `t()`,
  longest-prefix active resolution, nested routes covered by unit tests).
- All 8 upstream destinations stay reachable; never remove a destination that
  has not been redesigned. `AppSidebar.tsx` stays untouched.

## 5. Reusable-abstraction rules

- Extract a custom shared component only on proven reuse across screens, never
  on resemblance. Sharing flows through upstream primitives and reused
  feature components. No second design system, no second API/state layer.

## 6. Upstream/downstream ownership rules

- Downstream: page composition, section grouping, theme tokens, navigation
  presentation, screen states. Upstream: clients, hooks, validation, dialogs
  with embedded flows, primitives, locale infrastructure.
- Complex feature components (`SettingsForm`, `ProviderSection`,
  `EpisodesTab`) stay canonical upstream and are reused, not forked.
- Future syncs are expected to touch at most: route adapters, the layout
  import, `AppShell`, and directly reused feature components.

## 7. Maintenance Agent product concepts (assessment, not implemented)

| Concept | Existing mapping | Verdict |
|---|---|---|
| Documents/manuals | sources (file/web/text ingestion + embeddings) | Direct reuse |
| Knowledge lookup | text/vector search + scopes | Direct reuse |
| AI assistance | ask streaming, source/notebook chat | Direct reuse |
| Shift-handover briefings | podcast TTS episodes | Repurpose |
| Maintenance records/incidents | notes (timestamped, notebook-scoped) | Adapt; failure taxonomy is new |
| Equipment/assets | notebooks (collections) or sources | Implemented: first-class `asset` table (migration 26) with name, type, status, location, manufacturer, model, serial; registry screen under Collect; no relations yet |
| Work orders/tasks | none (job pipeline is infra-only) | New downstream concept (deferred) |
| Equipment status/health | status badges, capability probes | New concept; pattern exists |
| Audit/history | recently-viewed, checkpoints, job history | Reuse + extend |
| Roles/permissions | single-password auth only | Gap; backend limitation |

## 8. Proposed future information architecture (not implemented)

- Notebooks list → equipment fleets/systems; sources → manuals library;
  search → incident/knowledge lookup; podcasts → handover briefings;
  settings/models → provider config (unchanged); transformations → report
  templates. New: asset-source/note links, work orders, health overview.

## 9. Explicit non-goals

- No rewrite of upstream flows, no second clients/state/validation/media
  layers, no new auth model, no locale-architecture changes, no speculative
  components, no migrating screens for migration's sake.

## 10. Open questions (require product decisions)

- Asset registry data model and host surface (notebook-scoped records vs new tables).
- Work-order lifecycle and its relation to the commands/job pipeline.
- Failure taxonomy for notes/incidents and search facets.
- Multi-user roles: needs backend work; single-password auth is insufficient.
- Visual verification story (no browser runner exists).
- `.env` BOM re-save and production content onboarding remain open ops items.
