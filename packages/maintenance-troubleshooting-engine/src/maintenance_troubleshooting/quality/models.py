"""Data-quality report models (reporting only — never repair)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IssueSeverity(str, Enum):
    """Severity of a single data-quality finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class RecordIssue:
    """One finding about one record."""

    record_id: str
    field: str
    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.WARNING


@dataclass
class MissingFieldAnalysis:
    """Required/optional field coverage for one record."""

    record_id: str
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)


@dataclass
class TextQualityAssessment:
    """Quality signals for a record's free text (no text is modified)."""

    record_id: str
    has_request_text: bool = False
    has_repair_text: bool = False
    repair_text_length: int = 0
    flags: list[str] = field(default_factory=list)


@dataclass
class FailureModeConsistencyCheck:
    """Recorded failure mode vs available symptom text."""

    record_id: str
    recorded_mode: str | None = None
    has_symptom_text: bool = False
    consistent: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class DuplicateGroup:
    """Records sharing one record ID (or duplicate key)."""

    key: str
    record_ids: list[str] = field(default_factory=list)
    row_numbers: list[int] = field(default_factory=list)


@dataclass
class DataQualityReport:
    """Aggregate quality view over a batch of canonical records."""

    total_records: int = 0
    valid_records: int = 0
    issues: list[RecordIssue] = field(default_factory=list)
    missing_fields: list[MissingFieldAnalysis] = field(default_factory=list)
    duplicates: list[DuplicateGroup] = field(default_factory=list)
    text_assessments: list[TextQualityAssessment] = field(default_factory=list)
    consistency_checks: list[FailureModeConsistencyCheck] = field(
        default_factory=list
    )

    def errors(self) -> list[RecordIssue]:
        """Findings that disqualify a record from analysis."""
        return [issue for issue in self.issues if issue.severity == IssueSeverity.ERROR]

    def summary(self) -> str:
        """One-line human summary for CLI/logs."""
        return (
            f"{self.valid_records}/{self.total_records} valid records, "
            f"{len(self.issues)} issues "
            f"({len(self.errors())} errors), "
            f"{len(self.duplicates)} duplicate groups"
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable view of the report."""
        return {
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "issues": [
                {
                    "record_id": issue.record_id,
                    "field": issue.field,
                    "code": issue.code,
                    "message": issue.message,
                    "severity": issue.severity.value,
                }
                for issue in self.issues
            ],
            "duplicates": [
                {
                    "key": group.key,
                    "record_ids": group.record_ids,
                    "row_numbers": group.row_numbers,
                }
                for group in self.duplicates
            ],
            "summary": self.summary(),
        }
