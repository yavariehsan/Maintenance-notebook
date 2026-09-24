"""Failure mode vs failure mechanism.

Failure mode is what the operator observes (``machine does not start``).
Failure mechanism is the technical fault behind it (``PLC failed to boot``).
The engine must learn the relationship between them from evidence; the two
concepts are never merged into one field.

A user-selected (recorded) failure mode is not assumed correct: every value
carries its provenance so the pipeline can later distinguish recorded,
observed-symptom, and inferred interpretations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FailureProvenance(str, Enum):
    """Where a failure statement came from."""

    RECORDED = "recorded"  # as selected/written in the source record
    OBSERVED = "observed"  # symptom text from request descriptions
    INFERRED = "inferred"  # pipeline interpretation (must cite its basis)


@dataclass
class FailureMode:
    """An observable failure mode with explicit provenance."""

    key: str
    label: str
    provenance: FailureProvenance
    source_record_id: str | None = None


@dataclass
class FailureMechanism:
    """A technical fault / mechanism with explicit provenance."""

    key: str
    label: str
    provenance: FailureProvenance
    description: str | None = None
    source_record_id: str | None = None


@dataclass
class FailureInterpretation:
    """A validated link between an observed symptom and a mechanism.

    ``basis`` must describe the evidence (e.g. repair descriptions of
    records R-1..R-3 plus shared technical tree); ``confidence`` and
    probability semantics live in :mod:`domain.metrics`, not here.
    """

    symptom: FailureMode
    mechanism: FailureMechanism | None
    basis: str
    supporting_record_ids: list[str] = field(default_factory=list)
