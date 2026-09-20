# ADR-downstream-001: Isolated downstream presentation and upstream synchronization

- **Status**: Accepted. Baseline validation complete on SurrealDB 2.6.5; remote ownership established (`origin` = downstream fork, `upstream` = official, `main` tracks `origin/main`). The custom UI layer is not implemented.
- **Date**: 2026-09-19
- **Baseline**: `3127f14`
- **Related**: [Native Windows baseline](../../downstream/native-windows-baseline.md)

## Context

This downstream project requires substantial UI customization and continued Open Notebook updates. The existing Next.js application has reusable hooks and primitives but no UI override registry. Native Windows is required; Docker and WSL are outside the development workflow.

## Decision

Propose downstream presentation in `frontend/src/custom/` and assets in `frontend/public/custom/`. Keep routing in `frontend/src/app/`; integrate through a root stylesheet import, the existing `AppShell` children contract, and selected thin page adapters. Preserve upstream providers, authentication, API clients, streaming, query hooks, stores, and UI primitives. Apply theme tokens at the document root, including dark mode. Keep custom translations separately owned when needed, with locale parity and minimal i18n integration.

Use `upstream` for the official repository and `origin` for the downstream repository. Shared `main` contains the validated customized application. `upstream/main` is sufficient; do not create a redundant `upstream-main` branch. Develop on short-lived `custom/*` branches. Merge a recorded upstream SHA into `sync/*`, resolve shared integration files explicitly, validate, and promote without squashing away upstream ancestry. Do not rewrite shared downstream history.

Separate Windows tooling, storage/database compatibility, theme, shell, translations, and individual screen changes into coherent commits. Validate database changes on disposable data before any real-data startup. Record accepted upstream SHAs and downstream release checkpoints.

## Alternatives considered

- A second frontend or full component copy: duplicates infrastructure and increases behavioral drift.
- A general plugin registry: no demonstrated requirement justifies the additional abstraction yet.
- Repeated rebasing of shared main: rewrites published history and complicates recovery.
- A local upstream mirror branch: duplicates the remote-tracking reference.

## Consequences

Most downstream files have clear ownership; a small set of adapters still needs manual reconciliation. Upstream interface changes can cause regressions without textual conflicts. Custom screens must deliberately adopt upstream UX improvements, and global token overrides affect upstream components. Git rollback does not reverse database migrations. Remote ownership is established and SurrealDB 2.6.5 is the required native runtime; the custom presentation layer remains unstarted.
