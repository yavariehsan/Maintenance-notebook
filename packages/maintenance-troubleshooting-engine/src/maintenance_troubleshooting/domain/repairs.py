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
    """One mined repair action with its supporting records.

    ``category``/``role`` are the primary classification (unchanged
    historical semantics). ``secondary_categories`` holds every other
    taxonomy category whose keywords matched the same sentence, in
    taxonomy-priority order — the sentence-level multi-type record
    (M11C D3). It never invents categories: entries come only from the
    same keyword table as the primary.
    """

    action_id: str
    category: ActionCategory
    role: ActionRole
    action_text: str
    normalized_text: str = ""
    source_record_ids: list[str] = field(default_factory=list)
    frequency: int = 0
    equipment_code: str = ""
    failure_mode_id: str = ""
    secondary_categories: list[ActionCategory] = field(default_factory=list)

    @property
    def evidence_count(self) -> int:
        """Number of supporting historical records."""
        return len(self.source_record_ids)


class VerificationEventType(str, Enum):
    """Kind of verification semantic an approved marker carries.

    Only values with explicit expert approval may be emitted:
    ``test`` (test-driven check, e.g. ``تست و تحویل شد``) and ``outcome``
    (a stated fixed/completed outcome attached to a technical action,
    e.g. ``برطرف شد``). Anything else stays unrepresented (M11C D4/D5).
    """

    TEST = "test"
    OUTCOME = "outcome"


class HandoverEventType(str, Enum):
    """Kind of post-repair handover/closure semantic.

    ``handover`` covers physical handover markers (e.g. ``تحویل`` forms);
    ``outcome`` covers stated fixed/completed outcomes kept as events.
    Values are labels on verbatim source sentences, never interpretations.
    """

    HANDOVER = "handover"
    OUTCOME = "outcome"


@dataclass
class TechnicalVerification:
    """A verification step attested by a historical sentence (M11C D4).

    Emitted only for expert-approved triggers: the canonical
    test-and-handover sentence, or a test/outcome marker co-occurring in
    a sentence that also yields a technical RepairAction. Standalone
    ``تست شد`` without a decided rule yields nothing (open question).
    """

    verification_id: str
    record_id: str
    sentence: str
    event_type: VerificationEventType
    equipment_code: str = ""
    failure_mode_id: str = ""
    repair_action_id: str | None = None


@dataclass
class PostRepairEvent:
    """A handover/closure event attested by a historical sentence (M11C D5).

    Pure closure sentences yield an event and no RepairAction; mixed
    sentences yield the technical RepairAction plus this event, all
    pointing at the same source sentence.
    """

    event_id: str
    record_id: str
    sentence: str
    event_type: HandoverEventType
    equipment_code: str = ""
    failure_mode_id: str = ""
    repair_action_id: str | None = None
