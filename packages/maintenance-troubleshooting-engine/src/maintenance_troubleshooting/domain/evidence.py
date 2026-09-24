"""Repair evidence: traceable links from records to candidate causes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from maintenance_troubleshooting.domain.equipment import TechnicalTree


class RelevanceBasis(str, Enum):
    """Why a historical record counts as evidence for a query.

    Ordered roughly from strongest to weakest for documentation purposes;
    the final ranking is owned by a future ``CauseRanker`` and must be
    tested explicitly — this enum is a vocabulary, not a scoring table.
    """

    EXACT_EQUIPMENT = "exact_equipment"
    SAME_TECHNICAL_MODEL = "same_technical_model"
    SAME_MANUFACTURER_AND_TYPE = "same_manufacturer_and_type"
    SAME_EQUIPMENT_TYPE = "same_equipment_type"
    SAME_TECHNICAL_CLASS = "same_technical_class"
    SHARED_FAILURE_MODE = "shared_failure_mode"
    SIMILAR_SYMPTOM_TEXT = "similar_symptom_text"
    SHARED_MECHANISM = "shared_mechanism"


@dataclass
class RepairEvidence:
    """One historical record's contribution to a candidate cause.

    Allows the engine to state: this record is relevant (basis), this
    repair action and cause were associated with it, it belongs to this
    equipment, and it came from this source record.
    """

    evidence_id: str
    record_id: str
    equipment_code: str
    relevance_basis: RelevanceBasis
    repair_action: str | None = None
    cause: str | None = None
    mechanism: str | None = None
    technical_snapshot: TechnicalTree | None = None
    notes: str | None = None
    # Mining scope and weighting (populated by the evidence miner).
    scope_equipment: str = ""
    scope_failure_mode: str = ""
    relevance_detail: str = ""
    weight: float = 1.0
