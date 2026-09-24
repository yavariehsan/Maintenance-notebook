"""Candidate causes with evidence and support metrics."""

from __future__ import annotations

from dataclasses import dataclass, field

from maintenance_troubleshooting.domain.evidence import RepairEvidence
from maintenance_troubleshooting.domain.metrics import (
    CauseProbability,
    Confidence,
    EvidenceScore,
    OccurrenceRate,
)

#: Honest default label attached to every guide's percentages.
DEFAULT_PROBABILITY_SEMANTICS = (
    "Share of total evidence weight for this failure mode. "
    "Not a calibrated real-world probability."
)


@dataclass
class SupportBreakdown:
    """Per-dimension support contributions behind a candidate cause.

    Values are documented support weights (see ``EvidenceScore``), not
    probabilities. ``None`` means the dimension had no evidence.
    """

    technical_tree_support: float | None = None
    equipment_specific_support: float | None = None
    manufacturer_support: float | None = None
    model_support: float | None = None
    failure_mode_support: float | None = None


@dataclass
class TroubleshootingCause:
    """One candidate cause with its evidence and support metrics."""

    cause: str
    supporting_evidence: list[RepairEvidence] = field(default_factory=list)
    historical_frequency: OccurrenceRate | None = None
    similarity_score: float | None = None
    support: SupportBreakdown = field(default_factory=SupportBreakdown)
    evidence_score: EvidenceScore | None = None
    confidence: Confidence | None = None
    probability: CauseProbability | None = None
    recommended_actions: list[str] = field(default_factory=list)

    @property
    def evidence_count(self) -> int:
        """Number of supporting historical records."""
        return len(self.supporting_evidence)


__all__ = [
    "DEFAULT_PROBABILITY_SEMANTICS",
    "SupportBreakdown",
    "TroubleshootingCause",
]
