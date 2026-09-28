"""Unit tests: failure clustering, action taxonomy, location exclusion."""

from maintenance_troubleshooting.domain import MaintenanceRecord, TechnicalTree
from maintenance_troubleshooting.domain.evidence import RelevanceBasis, RepairEvidence
from maintenance_troubleshooting.domain.normalized import NormalizedRecord
from maintenance_troubleshooting.domain.repairs import (
    ActionCategory,
    ActionRole,
    HandoverEventType,
    VerificationEventType,
)
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
    match_categories,
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


# ---------------------------------------------------------------------------
# M11C-6 repair-semantics regression tests.
#
# Conventions: synthetic Persian fixtures only (no customer data); each
# test names the approved decision it guards. Miner contexts are built by
# hand like test_action_taxonomy_and_roles so the admission gate,
# vocabulary induction, and HISTORY_ONLY paths are exercised directly.
# ---------------------------------------------------------------------------

from maintenance_troubleshooting.domain.equipment import Equipment  # noqa: E402


def _miner_run(entries: list[dict]) -> PipelineContext:
    """Run RepairActionMiner over synthetic record entries.

    Entry keys: id, repair, equipment (default QX-1), tree (default
    empty TechnicalTree), manufacturer (default None), symptom.
    """
    context = PipelineContext()
    records = []
    for entry in entries:
        tree = entry.get("tree") or TechnicalTree()
        code = entry.get("equipment", "QX-1")
        records.append(
            MaintenanceRecord(
                record_id=entry["id"],
                equipment_code=code,
                request_description=entry.get("symptom", "s"),
                repair_description=entry.get("repair"),
                technical_tree=tree,
            )
        )
        if code not in context.equipment:
            context.equipment[code] = Equipment(
                equipment_code=code,
                manufacturer=entry.get("manufacturer"),
                technical_tree=tree,
            )
    context.records = records
    context.valid_records = records
    context.evidence = [
        RepairEvidence(
            evidence_id=f"ev-{record.record_id}",
            record_id=record.record_id,
            equipment_code=record.equipment_code,
            relevance_basis=RelevanceBasis.EXACT_EQUIPMENT,
            scope_equipment=record.equipment_code,
            scope_failure_mode="FM-1",
            weight=1.0,
        )
        for record in records
    ]
    return RepairActionMiner().run(context)


def test_short_fragment_rejected() -> None:
    """M11C D1: `6 شد` is rejected as repair/action text."""
    context = _miner_run([{"id": "R-1", "repair": "6 شد"}])
    assert context.repair_actions == []
    assert context.technical_verifications == []
    assert context.post_repair_events == []


def test_short_component_admitted_with_tree() -> None:
    """M11C D1: short text naming a tree component is admitted."""
    admitted = _miner_run(
        [
            {
                "id": "R-1",
                "repair": "تعمیر پمپ",
                "tree": TechnicalTree(t3="پمپ هیدرولیک"),
            }
        ]
    )
    assert [action.action_text for action in admitted.repair_actions] == ["تعمیر پمپ"]
    dropped = _miner_run([{"id": "R-1", "repair": "تعمیر پمپ"}])
    assert dropped.repair_actions == []


def test_short_arbitrary_phrase_rejected() -> None:
    """M11C D1: short text without attributable vocabulary is rejected."""
    context = _miner_run([{"id": "R-1", "repair": "abc"}])
    assert context.repair_actions == []


def test_long_useful_action_passes() -> None:
    """M11C D1: existing useful actions >=10 characters continue to pass."""
    context = _miner_run([{"id": "R-1", "repair": "منبع تغذیه تعویض شد"}])
    assert len(context.repair_actions) == 1
    assert context.repair_actions[0].category is ActionCategory.REPLACE


def test_tahvil_shod_history_only() -> None:
    """M11C D2/D5: `تحویل شد` stays history, never a recommended action."""
    context = _miner_run([{"id": "R-1", "repair": "تحویل شد"}])
    assert context.repair_actions == []
    assert len(context.post_repair_events) == 1
    event = context.post_repair_events[0]
    assert event.event_type is HandoverEventType.HANDOVER
    assert event.record_id == "R-1"
    assert event.sentence == "تحویل شد"


def test_tahvil_gardid_history_only() -> None:
    """M11C D2/D5: `تحویل گردید` stays history, never a recommended action."""
    context = _miner_run([{"id": "R-1", "repair": "تحویل گردید"}])
    assert context.repair_actions == []
    assert len(context.post_repair_events) == 1
    assert context.post_repair_events[0].event_type is HandoverEventType.HANDOVER


def test_tahvil_gerefte_history_only() -> None:
    """M11C D2: genuine logistics phrasing is still not a RepairAction."""
    context = _miner_run([{"id": "R-1", "repair": "تحویل گرفته شد"}])
    assert context.repair_actions == []
    assert len(context.post_repair_events) == 1


def test_moshkel_raf_shod_history_only() -> None:
    """M11C D2/D5: `مشکل رفع شد` is an outcome event, not an action."""
    context = _miner_run([{"id": "R-1", "repair": "مشکل رفع شد"}])
    assert context.repair_actions == []
    assert len(context.post_repair_events) == 1
    assert context.post_repair_events[0].event_type is HandoverEventType.OUTCOME


def test_bartaraf_gardid_history_only() -> None:
    """M11C D2/D5: `برطرف گردید` is an outcome event, not an action."""
    context = _miner_run([{"id": "R-1", "repair": "برطرف گردید"}])
    assert context.repair_actions == []
    assert len(context.post_repair_events) == 1
    assert context.post_repair_events[0].event_type is HandoverEventType.OUTCOME


def test_test_tahvil_produces_verification_and_event() -> None:
    """M11C D4/D5: `تست و تحویل شد` → Verification + handover, no action."""
    context = _miner_run([{"id": "R-1", "repair": "تست و تحویل شد"}])
    assert context.repair_actions == []
    assert len(context.technical_verifications) == 1
    verification = context.technical_verifications[0]
    assert verification.event_type is VerificationEventType.TEST
    assert verification.record_id == "R-1"
    assert verification.sentence == "تست و تحویل شد"
    assert len(context.post_repair_events) == 1
    assert context.post_repair_events[0].event_type is HandoverEventType.HANDOVER


def test_standalone_test_emits_verification_only() -> None:
    """M11C-6R2 final: standalone `تست شد` → history + Verification, no action."""
    context = _miner_run([{"id": "R-1", "repair": "تست شد"}])
    assert context.repair_actions == []
    assert len(context.technical_verifications) == 1
    verification = context.technical_verifications[0]
    assert verification.event_type is VerificationEventType.TEST
    assert verification.record_id == "R-1"
    assert verification.sentence == "تست شد"
    assert verification.repair_action_id is None
    assert context.post_repair_events == []


def test_mixed_sentence_keeps_technical_action() -> None:
    """M11C D3/D5: technical action retained; verification+event linked."""
    sentence = "تعویض پالت انجام نمیشد که سوئیچ تنظیم و تست و تحویل گردید"
    context = _miner_run([{"id": "R-1", "repair": sentence}])
    assert [action.action_text for action in context.repair_actions] == [sentence]
    action = context.repair_actions[0]
    assert action.category is ActionCategory.REPLACE
    assert ActionCategory.ADJUST in action.secondary_categories
    assert ActionCategory.TEST in action.secondary_categories
    assert len(context.technical_verifications) == 1
    verification = context.technical_verifications[0]
    assert verification.event_type is VerificationEventType.TEST
    assert verification.repair_action_id == action.action_id
    assert len(context.post_repair_events) == 1
    event = context.post_repair_events[0]
    assert event.event_type is HandoverEventType.HANDOVER
    assert event.repair_action_id == action.action_id
    # No invented switch replacement; the sentence itself is the action.
    assert [action.action_text for action in context.repair_actions] == [sentence]
    assert "تعویض سوئیچ" not in {action.action_text for action in context.repair_actions}


def test_mixed_outcome_registers_verification() -> None:
    """M11C D5 case B: technical action + outcome marker → verification."""
    sentence = "پمپ تعویض شد و مشکل برطرف شد"
    context = _miner_run([{"id": "R-1", "repair": sentence}])
    assert len(context.repair_actions) == 1
    assert context.repair_actions[0].category is ActionCategory.REPLACE
    assert len(context.technical_verifications) == 1
    assert context.technical_verifications[0].event_type is VerificationEventType.OUTCOME


def test_qateh_does_not_trigger_disconnect() -> None:
    """M11C D6: `قطعه` must not match `قطع`/disconnect (token-aware)."""
    assert match_categories("بعلت فورس بودن قطعه") == []
    assert classify_sentence("بعلت فورس بودن قطعه") is ActionCategory.OBSERVED_ISSUE
    context = _miner_run([{"id": "R-1", "repair": "بعلت فورس بودن قطعه"}])
    assert context.repair_actions[0].category is ActionCategory.OBSERVED_ISSUE


def test_genuine_disconnect_still_matches() -> None:
    """M11C D6: a real disconnect phrase keeps matching."""
    assert match_categories("سیم برق قطع شد") == [ActionCategory.DISCONNECT]
    context = _miner_run([{"id": "R-1", "repair": "سیم برق قطع شد"}])
    assert context.repair_actions[0].category is ActionCategory.DISCONNECT


def test_zwnj_spacing_equivalence() -> None:
    """M11C D6: `می‌شود` and `می شود` match equivalently (shared contract)."""
    from maintenance_troubleshooting.text import SimpleTokenizer

    tokenizer = SimpleTokenizer()
    assert tokenizer.tokenize("می‌شود") == tokenizer.tokenize("می شود") == ["می", "شود"]
    assert classify_sentence("پمپ تست می‌شود") is ActionCategory.TEST
    assert classify_sentence("پمپ تست می شود") is ActionCategory.TEST


def test_zwnj_miner_admission_equivalence() -> None:
    """M11C D6: ZWNJ variants behave identically through the miner."""
    from maintenance_troubleshooting.stages.repairs import _tokens

    assert _tokens("می‌شود") == _tokens("می شود")
    # Short component-bearing sentences admit regardless of ZWNJ form;
    # the admitted text is the verbatim original (no silent rewrite).
    admitted_zwnj = _miner_run(
        [
            {
                "id": "R-1",
                "repair": "تعمیر پمپ می‌شود",
                "tree": TechnicalTree(t3="پمپ هیدرولیک"),
            }
        ]
    )
    admitted_spaced = _miner_run(
        [
            {
                "id": "R-1",
                "repair": "تعمیر پمپ می شود",
                "tree": TechnicalTree(t3="پمپ هیدرولیک"),
            }
        ]
    )
    assert [a.action_text for a in admitted_zwnj.repair_actions] == ["تعمیر پمپ می‌شود"]
    assert [a.action_text for a in admitted_spaced.repair_actions] == ["تعمیر پمپ می شود"]


def test_leading_waw_stripped_for_matching() -> None:
    """M11C D6: attached `و` conjunction never blocks a keyword match."""
    from maintenance_troubleshooting.stages.repairs import _token_matches

    assert _token_matches("تعویض", ["وتعویض"])
    # A token that already is a keyword still matches exactly first.
    assert _token_matches("وصل", ["وصل"])
    assert classify_sentence("وتعویض قطعه انجام شد") is ActionCategory.REPLACE


def test_ascii_inflection_only_for_latin_keywords() -> None:
    """M11C D6: `checked`→`check`, but Persian forms never stem."""
    from maintenance_troubleshooting.stages.repairs import _token_matches

    assert _token_matches("check", ["checked"])
    assert _token_matches("check", ["checks"])
    assert not _token_matches("قطع", ["قطعه"])
    assert not _token_matches("تست", ["تستها"])


def test_admission_tier_precedence() -> None:
    """M11C D1: tree → alias → induced precedence is explicit."""
    from maintenance_troubleshooting.stages.repairs import _admission_tier

    assert _admission_tier({"پمپ"}, {"پمپ"}, {"دیگر"}, set()) == "tree"
    assert _admission_tier({"پمپ"}, set(), {"پمپ"}, {"پمپ"}) == "alias"
    assert _admission_tier({"پمپ"}, set(), set(), {"پمپ"}) == "induced"
    assert _admission_tier({"غریب"}, set(), set(), set()) is None


def test_guide_bundle_traceability() -> None:
    """M11C §2: procedure bundle is traceable; nothing invented."""
    sentence = "تعویض پالت انجام نمیشد که سوئیچ تنظیم و تست و تحویل گردید"
    context = _miner_run([{"id": "R-7", "repair": sentence}])
    action = context.repair_actions[0]
    verification = context.technical_verifications[0]
    event = context.post_repair_events[0]
    # Every object points at the same historical sentence and record.
    assert verification.record_id == event.record_id == action.source_record_ids[0] == "R-7"
    assert verification.sentence == event.sentence == sentence
    assert verification.repair_action_id == event.repair_action_id == action.action_id
    # No closure-only action and no invented replacement text.
    assert [action.action_text for action in context.repair_actions] == [sentence]
    assert "تعویض سوئیچ" not in {action.action_text for action in context.repair_actions}


def test_switch_adjustment_guide_synthesis() -> None:
    """M11C-6R2 Part B: approved source yields the exact guide instruction."""
    sentence = "تعویض پالت انجام نمیشد که سوئیچ تنظیم و تست و تحویل گردید"
    context = _miner_run([{"id": "R-7", "repair": sentence}])
    action = context.repair_actions[0]
    assert action.guide_instruction == (
        "در صورت عدم تعویض پالت، سوئیچ بررسی و در صورت لزوم تنظیم گردد."
    )
    # Original text untouched; instruction linked to the same action/record.
    assert action.action_text == sentence
    assert action.source_record_ids == ["R-7"]
    verification = context.technical_verifications[0]
    event = context.post_repair_events[0]
    assert verification.repair_action_id == action.action_id
    assert event.repair_action_id == action.action_id


def test_guide_synthesis_only_for_approved_shape() -> None:
    """M11C-6R2 Part B: no instruction outside the narrow approved shape."""
    # Affirmed replacement (no negation) → no instruction.
    affirmed = _miner_run([{"id": "R-1", "repair": "پمپ تعویض شد و مشکل برطرف شد"}])
    assert affirmed.repair_actions
    assert all(action.guide_instruction is None for action in affirmed.repair_actions)
    # No adjustment present → no instruction.
    no_adjust = _miner_run([{"id": "R-1", "repair": "پمپ تعویض نشد و دستگاه تست و تحویل شد"}])
    assert all(action.guide_instruction is None for action in no_adjust.repair_actions)
    # No test/handover context → no instruction.
    no_test = _miner_run([{"id": "R-1", "repair": "تعویض پالت انجام نمیشد که سوئیچ تنظیم شد"}])
    assert all(action.guide_instruction is None for action in no_test.repair_actions)
    # Non-replace primary (observed issue) → no instruction, nothing invented.
    observed = _miner_run([{"id": "R-1", "repair": "بعلت فورس بودن قطعه"}])
    assert all(action.guide_instruction is None for action in observed.repair_actions)


def _clustered(modes: list[tuple[str, str]]) -> dict[str, str]:
    """Cluster (record_id, raw_mode) pairs; return record → mode key."""
    records = [
        MaintenanceRecord(
            record_id=rid,
            equipment_code="B104",
            request_description="متن",
            failure_mode_recorded=mode,
            technical_tree=TechnicalTree(t1="c", t2="s", t3="t", t4="m", t5="x"),
        )
        for rid, mode in modes
    ]
    context = _context_with(records)
    context = FailureModeAnalyzer().run(context)
    return dict(context.record_failure_mode)


def test_real_sample_merge_equivalent_tool_change_wordings() -> None:
    """'تعویض ابزار' and 'مشکل در تعویض ابزار (تعویض ابزار)' must merge."""
    assignment = _clustered(
        [("R-1", "تعویض ابزار"), ("R-2", "مشکل در تعویض ابزار (تعویض ابزار)")]
    )
    assert assignment["R-1"] == assignment["R-2"]


def test_real_sample_split_tool_vs_pallet() -> None:
    """Tool-change and pallet-change wordings must stay separate."""
    assignment = _clustered(
        [
            ("R-1", "مشکل در تعویض ابزار (تعویض ابزار)"),
            ("R-2", "مشکل در تعویض پالت (تعویض پالت)"),
        ]
    )
    assert assignment["R-1"] != assignment["R-2"]


def test_real_sample_tag_veto_blocks_monitoring_tool_chain() -> None:
    """Monitoring errors must not chain into the tool-change cluster."""
    assignment = _clustered(
        [
            ("R-1", "مشکل در تعویض ابزار (تعویض ابزار)"),
            ("R-2", "A - contour monitoring error (محور A)"),
            ("R-3", "Conter Monitoring Error (اسپیندل و رم)"),
        ]
    )
    assert assignment["R-2"] != assignment["R-1"]
    assert assignment["R-3"] != assignment["R-1"]


def test_real_sample_weak_pair_not_boosted_by_same_machine() -> None:
    """Lexically unrelated modes on identical trees must not merge."""
    assignment = _clustered(
        [
            ("R-1", "مشکل در تعویض ابزار (تعویض ابزار)"),
            ("R-2", "Encoder Fault (اسپیندل و رم)"),
        ]
    )
    assert assignment["R-1"] != assignment["R-2"]
