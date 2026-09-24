"""Optional knowledge-enrichment boundary (LLM adapters plug in here)."""

from maintenance_troubleshooting.enrichment.base import (
    EnrichmentInput,
    EnrichmentRecordRef,
    EnrichmentResult,
    KnowledgeEnrichmentProvider,
    SuggestedAction,
    SuggestedCause,
    validate_enrichment,
)
from maintenance_troubleshooting.enrichment.fake import FakeKnowledgeEnrichmentProvider
from maintenance_troubleshooting.enrichment.noop import NoOpEnrichmentProvider

__all__ = [
    "EnrichmentInput",
    "EnrichmentRecordRef",
    "EnrichmentResult",
    "FakeKnowledgeEnrichmentProvider",
    "KnowledgeEnrichmentProvider",
    "NoOpEnrichmentProvider",
    "SuggestedAction",
    "SuggestedCause",
    "validate_enrichment",
]
