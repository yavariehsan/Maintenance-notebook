"""Unit tests: failure clustering, action taxonomy, location exclusion."""

from maintenance_troubleshooting.domain import MaintenanceRecord, TechnicalTree
from maintenance_troubleshooting.domain.evidence import RelevanceBasis, RepairEvidence
from maintenance_troubleshooting.domain.normalized import NormalizedRecord
from maintenance_troubleshooting.domain.repairs import ActionCategory, ActionRole
from maintenance_troubleshooting.similarity import (
    TechnicalSimilarityCategory as Cat,
)
from maintenance_troubleshooting.similarity import (
    classify_technical_similarity,
)
from maintenance_troubleshooting.stages.base import PipelineContext
from maintenance_troubleshooting.stages.failure_modes import FailureModeAnalyzer
from maintenance_troubleshooting.stages.normalization import Normalizer
from maintenance_troubleshooting.stages.repairs import (
    RepairActionMiner,
    classify_sentence,
    split_sentences,
)


def _record(record_id: str, mode: str, symptom: str = "متن") -> MaintenanceRecord:
    return MaintenanceRecord(
        record_id=record_id,
        equipment_code="B104",
        request_description=symptom,
        failure_mode_recorded=mode or None,
        technical_tree=TechnicalTree(t1="c", t2="s", t3="t", t4="m", t5="x"),
    )


def _context_with(records: list[MaintenanceRecord]) -> PipelineContext:
    context = PipelineContext()
    context.records = records
    context.valid_records = records
    context = Normalizer().run(context)
    return context


def test_clustering_merges_spelling_variants() -> None:
    context = _context_with(
        [
            _record("R-1", "روشن نشدن دستگاه"),
            _record("R-2", "دستگاه روشن نمی شود"),
            _record("R-3", "روشن نشدن"),
            _record("R-4", "نشت روغن"),
        ]
    )
    context = FailureModeAnalyzer().run(context)
    assert len(context.failure_modes) == 2
    start = next(
        mode
        for mode in context.failure_modes.values()
        if "R-1" in mode.record_ids
    )
    assert set(start.record_ids) == {"R-1", "R-2", "R-3"}
    assert len(start.aliases) >= 2  # variants retained, not collapsed away
    oil = next(
        mode
        for mode in context.failure_modes.values()
        if "R-4" in mode.record_ids
    )
    assert oil.record_ids == ["R-4"]
    # Every record keeps its original / normalized / canonical triple.
    assert context.record_failure_mode["R-2"] == start.key


def test_modeless_records_attach_or_stay_explicit() -> None:
    context = _context_with(
        [
            _record("R-1", "روشن نشدن دستگاه", symptom="دستگاه روشن نمی‌شود"),
            _record("R-2", "", symptom="دستگاه روشن نمی‌شود"),
            _record("R-3", "", symptom="موضوع کاملا متفاوت دیگر"),
        ]
    )
    context = FailureModeAnalyzer().run(context)
    attached_mode = context.record_failure_mode["R-2"]
    assert context.record_failure_mode["R-1"] == attached_mode
    lonely = context.failure_modes[context.record_failure_mode["R-3"]]
    assert lonely.status == "unclassified"


def test_action_taxonomy_and_roles() -> None:
    assert classify_sentence("منبع تغذیه تعویض شد") is ActionCategory.REPLACE
    assert classify_sentence("checked pressure switch") is ActionCategory.CHECK
    assert classify_sentence("found loose wire") is ActionCategory.CONNECT
    assert split_sentences("a. b!\nخط اول؟ خط دوم") == ["a", "b", "خط اول", "خط دوم"]

    record = MaintenanceRecord(
        record_id="R-1",
        equipment_code="B104",
        request_description="x",
        repair_description=(
            "checked pressure switch. repaired connector. tested machine"
        ),
        technical_tree=TechnicalTree(),
    )
    context = PipelineContext()
    context.valid_records = [record]
    context.record_failure_mode = {"R-1": "FM-0001"}
    context.normalized = {
        "R-1": NormalizedRecord(record_id="R-1", equipment_code="B104")
    }
    context.evidence = [
        RepairEvidence(
            evidence_id="ev",
            record_id="R-1",
            equipment_code="B104",
            relevance_basis=RelevanceBasis.EXACT_EQUIPMENT,
            scope_equipment="B104",
            scope_failure_mode="FM-0001",
            weight=1.0,
        )
    ]
    context = RepairActionMiner().run(context)
    by_text = {action.action_text: action for action in context.repair_actions}
    assert by_text["checked pressure switch"].role is ActionRole.DIAGNOSTIC
    assert by_text["repaired connector"].role is ActionRole.CORRECTIVE
    assert by_text["tested machine"].role is ActionRole.VERIFICATION


def test_location_and_process_never_drive_similarity() -> None:
    """Same location/process, different technical trees → UNRELATED."""
    workshop = TechnicalTree(t1="ماشین‌ابزار", t2="فرز", t3="فرز عمودی")
    compressor = TechnicalTree(t1="تجهیزات تأسیساتی", t2="کمپرسور", t3="کمپرسور اسکرو")
    # Location/process trees are not even inputs to classification.
    assert classify_technical_similarity(workshop, compressor) is Cat.UNRELATED
    assert classify_technical_similarity(workshop, workshop) is Cat.SAME_EQUIPMENT_TYPE
