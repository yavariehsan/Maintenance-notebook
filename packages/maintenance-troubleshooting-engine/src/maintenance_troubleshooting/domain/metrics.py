"""Probability vs confidence vs support: four different types.

A troubleshooting UI may display ``Cause A — 62%``, but the implementation
must know — and record — which of these the number is:

1. ``OccurrenceRate`` — historical occurrence rate (``count / total`` over a
   stated record set). Descriptive; not a prediction.
2. ``EvidenceScore`` — heuristic support weight combining evidence
   components with a named method. A weight; not a probability.
3. ``Confidence`` — a model/extractor's self-reported certainty with a
   stated basis. Not a probability.
4. ``CauseProbability`` — a normalized share of evidence weight summing to
   1, produced only by :func:`normalize_probabilities`, which documents its
   method. A share of evidence, not a calibrated real-world probability,
   unless the methodology note says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


@dataclass(frozen=True)
class OccurrenceRate:
    """How often something appeared in a stated historical record set."""

    count: int
    total: int
    population: str = ""

    @property
    def rate(self) -> float:
        """Descriptive frequency in [0, 1]. Zero when the set is empty."""
        if self.total <= 0 or self.count <= 0:
            return 0.0
        return min(1.0, self.count / self.total)


@dataclass(frozen=True)
class EvidenceScore:
    """Heuristic support weight with a named method and components."""

    value: float
    method: str = "unspecified"
    components: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Confidence:
    """Self-reported certainty of a model or extractor stage."""

    value: float
    basis: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"confidence must be within [0, 1], got {self.value}")


@dataclass(frozen=True)
class CauseProbability:
    """Normalized share of evidence weight for one cause."""

    cause: str
    probability: float
    method: str = "proportional"


class ProbabilityMethod(str, Enum):
    """Documented normalization methods producing CauseProbability."""

    PROPORTIONAL = "proportional"  # share_i = max(score_i,0) / sum(max(scores,0))


def normalize_probabilities(
    scores: Mapping[str, float],
    method: ProbabilityMethod = ProbabilityMethod.PROPORTIONAL,
) -> list[CauseProbability]:
    """Convert evidence scores into shares summing to 1.

    Semantics (recorded on every result): each value is the cause's share
    of total non-negative evidence weight. This is **not** a calibrated
    real-world probability. Empty or all-zero input yields ``[]`` (no
    evidence → no distribution), never an invented uniform split.
    """
    if method is not ProbabilityMethod.PROPORTIONAL:
        raise ValueError(f"unsupported probability method: {method}")
    weights = {cause: max(0.0, float(score)) for cause, score in scores.items()}
    total = sum(weights.values())
    if total <= 0:
        return []
    return [
        CauseProbability(cause=cause, probability=weight / total, method=method.value)
        for cause, weight in weights.items()
    ]
