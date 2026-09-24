"""Structured repair actions mined from repair descriptions.

Actions keep their original sentence, a taxonomy category, a heuristic
role, and the source record IDs that support them. Nothing is invented:
an action exists only if a historical sentence produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ActionCategory(str, Enum):
    """Reusable action taxonomy (Persian + English keyword sets live in the
    repair-action mining stage)."""

    INSPECT = "inspect"
    CHECK = "check"
    MEASURE = "measure"
    TEST = "test"
    ADJUST = "adjust"
    RESET = "reset"
    REPAIR = "repair"
    REPLACE = "replace"
    CLEAN = "clean"
    LUBRICATE = "lubricate"
    TIGHTEN = "tighten"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    CALIBRATE = "calibrate"
    ALIGN = "align"
    CONFIGURE = "configure"
    PARAMETER_CHANGE = "parameter_change"
    BYPASS = "bypass"
    RESTORE = "restore"
    OBSERVED_ISSUE = "observed_issue"


class ActionRole(str, Enum):
    """Heuristic role of an action within its repair description."""

    DIAGNOSTIC = "diagnostic"
    CORRECTIVE = "corrective"
    VERIFICATION = "verification"
    OBSERVED_ISSUE = "observed_issue"


@dataclass
class RepairAction:
    """One mined repair action with its supporting records."""

    action_id: str
    category: ActionCategory
    role: ActionRole
    action_text: str
    normalized_text: str = ""
    source_record_ids: list[str] = field(default_factory=list)
    frequency: int = 0
    equipment_code: str = ""
    failure_mode_id: str = ""

    @property
    def evidence_count(self) -> int:
        """Number of supporting historical records."""
        return len(self.source_record_ids)
