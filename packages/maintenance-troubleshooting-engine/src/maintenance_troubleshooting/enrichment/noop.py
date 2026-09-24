"""Default enrichment: deterministic processing without any provider."""

from __future__ import annotations

from maintenance_troubleshooting.enrichment.base import (
    EnrichmentInput,
    EnrichmentResult,
)


class NoOpEnrichmentProvider:
    """No-op enrichment: suggestions always empty, pipeline stays pure."""

    name = "none"

    def enrich(self, batch: EnrichmentInput) -> EnrichmentResult:
        """Return an empty, valid result for any bounded input."""
        return EnrichmentResult(provider=self.name)
