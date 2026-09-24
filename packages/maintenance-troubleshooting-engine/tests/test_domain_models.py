"""Domain models: identity, traceability, and metric semantics."""

import pytest

from maintenance_troubleshooting.domain import (
    Confidence,
    Equipment,
    FailureInterpretation,
    FailureMechanism,
    FailureMode,
    FailureProvenance,
    MaintenanceRecord,
    OccurrenceRate,
    RelevanceBasis,
    RepairEvidence,
    TechnicalTree,
    TroubleshootingCause,
    TroubleshootingGuide,
    normalize_probabilities,
)


def test_equipment_identity_is_code_only() -> None:
    """Location/process must not exist on Equipment (not similarity axes)."""
    equipment = Equipment(equipment_code="QX-101", manufacturer="سازنده الف")
    assert equipment.identity_key() == "QX-101"
    for forbidden in ("location", "process", "workshop", "factory"):
        assert not any(
            forbidden in name.lower() for name in vars(equipment)
        ), forbidden


def test_technical_tree_levels_and_depth() -> None:
    tree = TechnicalTree.from_mapping({"t1": "a", "t2": " ", "t5": "m", "t7": "x"})
    assert tree.levels() == ("a", None, None, None, "m")
    assert tree.depth() == 2
    assert tree.extra_levels == {"t7": "x"}
    assert not tree.is_empty()
    assert TechnicalTree().is_empty()


def test_record_keeps_symptom_and_repair_separate() -> None:
    record = MaintenanceRecord(
        record_id="QX-1001",
        equipment_code="QX-101",
        request_description="دستگاه روشن نمی‌شود",
        repair_description="تعویض بلبرینگ",
    )
    assert record.symptom_text == "دستگاه روشن نمی‌شود"
    assert record.has_repair_description
    assert not MaintenanceRecord(
        record_id="X", equipment_code="Y", repair_description="  "
    ).has_repair_description


def test_failure_provenance_distinguishes_recorded_from_inferred() -> None:
    recorded = FailureMode(
        key="m1", label="روشن نشدن", provenance=FailureProvenance.RECORDED
    )
    inferred = FailureMechanism(
        key="f1", label="خرابی PLC", provenance=FailureProvenance.INFERRED
    )
    interpretation = FailureInterpretation(
        symptom=recorded, mechanism=inferred, basis="repairs R-1..R-2"
    )
    assert interpretation.symptom.provenance is FailureProvenance.RECORDED
    assert interpretation.mechanism is not None
    assert interpretation.mechanism.provenance is FailureProvenance.INFERRED


def test_occurrence_rate_is_descriptive_not_predictive() -> None:
    assert OccurrenceRate(count=3, total=4, population="QX-101").rate == pytest.approx(0.75)
    assert OccurrenceRate(count=0, total=0).rate == 0.0
    assert OccurrenceRate(count=9, total=4).rate == 1.0  # clamped, still a rate


def test_confidence_bounds_are_enforced() -> None:
    Confidence(value=0.8, basis="extractor agreement")
    with pytest.raises(ValueError):
        Confidence(value=1.5)


def test_normalize_probabilities_documents_share_semantics() -> None:
    result = normalize_probabilities({"a": 62.0, "b": 24.0, "c": 14.0})
    total = sum(item.probability for item in result)
    assert total == pytest.approx(1.0)
    assert result[0].cause == "a"
    assert all(item.method == "proportional" for item in result)


def test_normalize_probabilities_refuses_to_invent_distributions() -> None:
    assert normalize_probabilities({}) == []
    assert normalize_probabilities({"a": 0.0, "b": -2.0}) == []


def test_guide_orders_causes_and_labels_semantics() -> None:
    evidence = RepairEvidence(
        evidence_id="e1",
        record_id="QX-1001",
        equipment_code="QX-101",
        relevance_basis=RelevanceBasis.EXACT_EQUIPMENT,
        cause="فرسودگی بلبرینگ",
    )
    cause = TroubleshootingCause(cause="فرسودگی بلبرینگ", supporting_evidence=[evidence])
    guide = TroubleshootingGuide(
        equipment_code="QX-101",
        failure_mode=FailureMode(
            key="m", label="روشن نشدن", provenance=FailureProvenance.OBSERVED
        ),
        candidate_causes=[cause],
        evidence=[evidence],
        generated_from_record_ids=["QX-1001"],
    )
    assert guide.candidate_causes[0].evidence_count == 1
    assert "calibrated" in guide.probability_semantics.lower() or "Not a calibrated" in guide.probability_semantics
