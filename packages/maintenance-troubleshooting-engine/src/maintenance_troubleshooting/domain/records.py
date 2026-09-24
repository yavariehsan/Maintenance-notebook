"""Canonical maintenance record: one Excel row, fully traceable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maintenance_troubleshooting.domain.equipment import TechnicalTree


@dataclass
class MaintenanceRecord:
    """One maintenance/repair record from one workbook row.

    Explicit typed fields cover the known contract (see
    ``docs/data-contract.md``). ``raw`` keeps every source cell verbatim
    and ``extra`` keeps unmapped columns — source information is never
    thrown away, and anything derived later must remain distinguishable
    from these originals.
    """

    record_id: str
    equipment_code: str

    # Request identity (preserved even though record_id derives from them).
    request_prefix: str | None = None
    request_number: str | None = None
    request_type: str | None = None
    stage: str | None = None

    # Observed problem and performed repair (verbatim source text).
    request_description: str | None = None
    repair_description: str | None = None

    # As-recorded failure information (recorded != validated; see failure.py).
    failure_mode_recorded: str | None = None
    proposed_failure_mode: str | None = None
    failure_mechanism_recorded: str | None = None
    cause_recorded: str | None = None
    cause_detail: str | None = None
    referral: str | None = None
    referral_reason: str | None = None

    # Hierarchies. Only technical_tree is similarity evidence.
    technical_tree: TechnicalTree = field(default_factory=TechnicalTree)
    location_tree: str | None = None
    process_tree: str | None = None
    repair_unit_code: str | None = None
    process_code: str | None = None
    process_name: str | None = None

    # Dates/times as recorded (heterogeneous workbook cells); keys such as
    # "repair_start_date". Structured timelines are a later milestone.
    dates: dict[str, str] = field(default_factory=dict)

    # Planning / quality / safety / improvement fields.
    predicted_duration: str | None = None
    eir_proposal: str | None = None
    eir_approved: str | None = None
    report_quality: str | None = None
    repair_quality: str | None = None
    work_time: str | None = None
    deletion_reason: str | None = None
    safety_notes: str | None = None
    issue_bank_recorded: str | None = None
    parameter_change: str | None = None
    parameter_change_detail: str | None = None
    bypass: str | None = None
    bypass_detail: str | None = None
    registered_by: str | None = None
    delay_cause: str | None = None
    total_man_hours: str | None = None
    stop_time: str | None = None

    # Traceability: every source cell, plus unmapped columns.
    raw: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def symptom_text(self) -> str | None:
        """Observed-problem text (the failure-mode side, not the diagnosis)."""
        return self.request_description

    @property
    def has_repair_description(self) -> bool:
        """Whether a non-blank repair description was recorded."""
        return bool(self.repair_description and self.repair_description.strip())
