"""Data quality: validation, duplicates, text, and consistency checks."""

from maintenance_troubleshooting.domain import MaintenanceRecord
from maintenance_troubleshooting.quality import (
    DuplicateDetector,
    IssueSeverity,
    RecordValidator,
)


def _record(record_id: str = "QX-1001", **overrides) -> MaintenanceRecord:
    params = {
        "record_id": record_id,
        "equipment_code": "QX-101",
        "request_description": "دستگاه روشن نمی‌شود",
        "repair_description": "تعویض بلبرینگ انجام شد",
        "failure_mode_recorded": "روشن نشدن",
    }
    params.update(overrides)
    return MaintenanceRecord(**params)  # type: ignore[arg-type]


def test_blank_repair_is_warning_not_error() -> None:
    issues = RecordValidator().validate(_record(repair_description=""))
    assert any(i.code == "blank_repair" for i in issues)
    assert all(i.severity is IssueSeverity.WARNING for i in issues)


def test_blank_identifiers_are_errors() -> None:
    issues = RecordValidator().validate(_record(record_id="", equipment_code=""))
    assert {i.field for i in issues if i.severity is IssueSeverity.ERROR} == {
        "record_id",
        "equipment_code",
    }


def test_missing_field_analysis_splits_required_optional() -> None:
    analysis = RecordValidator().missing_fields(
        _record(repair_description=None), optional_fields=("repair_description",)
    )
    assert analysis.missing_required == []
    assert analysis.missing_optional == ["repair_description"]


def test_duplicate_detection_groups_by_record_id() -> None:
    records = [_record("QX-1"), _record("QX-2"), _record("QX-1")]
    groups = DuplicateDetector().find_duplicates(records)
    assert len(groups) == 1
    assert groups[0].key == "QX-1"
    assert groups[0].row_numbers == [0, 2]


def test_text_assessment_flags() -> None:
    assessment = RecordValidator().assess_text(_record(repair_description="x"))
    assert assessment.flags == ["short_repair"]
    blank = RecordValidator().assess_text(
        _record(repair_description=None, request_description=None)
    )
    assert set(blank.flags) == {"blank_repair", "blank_request"}


def test_failure_mode_consistency_notes() -> None:
    validator = RecordValidator()
    unlabeled = validator.check_failure_mode(
        _record(failure_mode_recorded=None, request_description="متن")
    )
    assert not unlabeled.consistent
    unvalidatable = validator.check_failure_mode(
        _record(failure_mode_recorded="X", request_description=None)
    )
    assert not unvalidatable.consistent
    clean = validator.check_failure_mode(_record())
    assert clean.consistent


def test_validate_all_counts_valid_records() -> None:
    report = RecordValidator().validate_all(
        [_record("A"), _record("", equipment_code=""), _record("B", repair_description=None)]
    )
    assert report.total_records == 3
    assert report.valid_records == 2
    assert "2/3" in report.summary()
    assert report.to_dict()["summary"] == report.summary()
