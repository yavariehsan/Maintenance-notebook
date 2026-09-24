"""Deterministic test double for the enrichment boundary.

``FakeKnowledgeEnrichmentProvider`` exercises the full
provider → validation → synthesis → SQLite path without any network or
credentials. It echoes bounded inputs through fixed rules (never an LLM):
a canonical-label suggestion, one inferred cause citing the first record
with repair text, and one deliberately invalid suggestion (unknown record
ID) so tests can prove validation drops it.
"""

from __future__ import annotations

from maintenance_troubleshooting.enrichment.base import (
    EnrichmentInput,
    EnrichmentResult,
    SuggestedAction,
    SuggestedCause,
)


class FakeKnowledgeEnrichmentProvider:
    """Deterministic, offline stand-in for a future LLM adapter."""

    name = "fake"

    def __init__(self, model: str = "fake-1") -> None:
        self.model = model

    def enrich(self, batch: EnrichmentInput) -> EnrichmentResult:
        """Build fixed, traceable suggestions from the bounded input."""
        causes: list[SuggestedCause] = []
        actions: list[SuggestedAction] = []
        for ref in batch.records:
            if ref.repair.strip():
                causes.append(
                    SuggestedCause(
                        cause_label=f"inferred from repair ({ref.record_id})",
                        kind="historically_inferred",
                        basis_record_ids=(ref.record_id,),
                        rationale="fake provider echoes the first repair-bearing record",
                    )
                )
                actions.append(
                    SuggestedAction(
                        action_text=ref.repair.strip().split("\n")[0][:120],
                        role="corrective",
                        basis_record_ids=(ref.record_id,),
                    )
                )
                break
        # Deliberately invalid: validation must drop this.
        causes.append(
            SuggestedCause(
                cause_label="ghost cause",
                kind="historically_inferred",
                basis_record_ids=("NO-SUCH-RECORD",),
                rationale="test double proving validation rejects unknown IDs",
            )
        )
        return EnrichmentResult(
            provider=self.name,
            model=self.model,
            canonical_label_suggestion=f"{batch.failure_mode_label} (enriched)",
            suggested_causes=causes,
            suggested_actions=actions,
        )
