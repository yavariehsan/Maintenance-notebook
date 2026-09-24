"""Record validation: missing fields, text quality, mode consistency."""

from __future__ import annotations

from dataclasses import dataclass

from maintenance_troubleshooting.domain.records import MaintenanceRecord
from maintenance_troubleshooting.quality.models import (
    DataQualityReport,
    FailureModeConsistencyCheck,
    IssueSeverity,
    MissingFieldAnalysis,
    RecordIssue,
    TextQualityAssessment,
)

#: Fields without which a record cannot be used for mining.
DEFAULT_REQUIRED_FIELDS: tuple[str, ...] = ("record_id", "equipment_code")

#: Short repair texts are flagged (informational; threshold is configurable).
DEFAULT_MIN_REPAIR_LENGTH = 10


@dataclass
class RecordValidator:
    """Validate canonical records and assemble a quality report.

    Validation reports; it never modifies records. Duplicates are detected
    separately by ``DuplicateDetector`` and merged into the report by the
    caller (``pipeline``) to keep each checker single-purpose.
    """

    required_fields: tuple[str, ...] = DEFAULT_REQUIRED_FIELDS
    min_repair_length: int = DEFAULT_MIN_REPAIR_LENGTH
    blank_flags: tuple[str, ...] = ("blank_repair", "short_repair", "blank_request")

    def _field_value(self, record: MaintenanceRecord, name: str) -> str | None:
        value = getattr(record, name, None)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def validate(self, record: MaintenanceRecord) -> list[RecordIssue]:
        """Findings for one record (missing identifiers are errors)."""
        issues: list[RecordIssue] = []
        for name in self.required_fields:
            if self._field_value(record, name) is None:
                issues.append(
                    RecordIssue(
                        record_id=record.record_id or "?",
                        field=name,
                        code="missing_required_field",
                        message=f"Required field '{name}' is blank.",
                        severity=IssueSeverity.ERROR,
                    )
                )
        if not record.has_repair_description:
            issues.append(
                RecordIssue(
                    record_id=record.record_id,
                    field="repair_description",
                    code="blank_repair",
                    message="Repair description is blank.",
                    severity=IssueSeverity.WARNING,
                )
            )
        return issues

    def missing_fields(
        self, record: MaintenanceRecord, optional_fields: tuple[str, ...] = ()
    ) -> MissingFieldAnalysis:
        """Required/optional coverage for one record."""
        analysis = MissingFieldAnalysis(record_id=record.record_id)
        for name in self.required_fields:
            if self._field_value(record, name) is None:
                analysis.missing_required.append(name)
        for name in optional_fields:
            if self._field_value(record, name) is None:
                analysis.missing_optional.append(name)
        return analysis

    def assess_text(self, record: MaintenanceRecord) -> TextQualityAssessment:
        """Text-quality signals for one record (read-only)."""
        repair = (record.repair_description or "").strip()
        request = (record.request_description or "").strip()
        flags: list[str] = []
        if not repair and "blank_repair" in self.blank_flags:
            flags.append("blank_repair")
        elif 0 < len(repair) < self.min_repair_length and "short_repair" in self.blank_flags:
            flags.append("short_repair")
        if not request and "blank_request" in self.blank_flags:
            flags.append("blank_request")
        return TextQualityAssessment(
            record_id=record.record_id,
            has_request_text=bool(request),
            has_repair_text=bool(repair),
            repair_text_length=len(repair),
            flags=flags,
        )

    def check_failure_mode(self, record: MaintenanceRecord) -> FailureModeConsistencyCheck:
        """Recorded mode vs symptom-text availability (structure, not verdict).

        A recorded mode without any symptom text cannot be validated later;
        a missing recorded mode with symptom text is minable but unlabeled.
        Neither case is "fixed" here — both are reported.
        """
        notes: list[str] = []
        has_symptom = bool((record.symptom_text or "").strip())
        if record.failure_mode_recorded and not has_symptom:
            notes.append("recorded mode has no symptom text to validate against")
        if not record.failure_mode_recorded and has_symptom:
            notes.append("symptom text present but no recorded failure mode")
        return FailureModeConsistencyCheck(
            record_id=record.record_id,
            recorded_mode=record.failure_mode_recorded,
            has_symptom_text=has_symptom,
            consistent=not notes,
            notes=notes,
        )

    def validate_all(
        self,
        records: list[MaintenanceRecord],
        optional_fields: tuple[str, ...] = (),
    ) -> DataQualityReport:
        """Assemble the full report for a batch of records."""
        report = DataQualityReport(total_records=len(records))
        for record in records:
            issues = self.validate(record)
            report.issues.extend(issues)
            report.missing_fields.append(
                self.missing_fields(record, optional_fields)
            )
            report.text_assessments.append(self.assess_text(record))
            report.consistency_checks.append(self.check_failure_mode(record))
            if not any(
                issue.severity == IssueSeverity.ERROR for issue in issues
            ):
                report.valid_records += 1
        return report
