"""Troubleshooting guides: the per-(equipment, failure mode) output unit."""

from __future__ import annotations

from dataclasses import dataclass, field

from maintenance_troubleshooting.domain.causes import (
    DEFAULT_PROBABILITY_SEMANTICS,
    TroubleshootingCause,
)
from maintenance_troubleshooting.domain.evidence import RepairEvidence
from maintenance_troubleshooting.domain.failure import FailureMode


@dataclass
class RecommendedAction:
    """One troubleshooting step grounded in historical repair actions."""

    order: int
    action: str
    source_record_ids: list[str] = field(default_factory=list)


@dataclass
class TroubleshootingGuide:
    """Output for one (equipment, failure mode) pair.

    ``candidate_causes`` is ordered strongest-first by evidence strength
    (ordering contract owned by the future ranker). ``probability_semantics``
    must honestly label what the percentages mean.
    """

    equipment_code: str
    failure_mode: FailureMode
    symptom_summary: str = ""
    candidate_causes: list[TroubleshootingCause] = field(default_factory=list)
    recommended_actions: list[RecommendedAction] = field(default_factory=list)
    evidence: list[RepairEvidence] = field(default_factory=list)
    generated_from_record_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    probability_semantics: str = DEFAULT_PROBABILITY_SEMANTICS

__all__ = ["RecommendedAction", "TroubleshootingGuide"]
