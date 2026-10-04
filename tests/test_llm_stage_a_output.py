"""Stage A output contract tests (Task 2).

TDD RED step: StageARecordEvidence/StageAFocusCategory/StageAEvidencePackage,
parse_stage_a_evidence and save_stage_a_batch_record do not exist yet.
Structure-only assertions — never stochastic LLM wording.
"""
import json

MEMBERS = ["K1-LLMROW-Sheet1-2", "K1-LLMROW-Sheet1-3"]


def _record(rid, **overrides):
    entry = {
        "record_id": rid,
        "primary_focus": "Tool Pocket / Magazine",
        "symptoms": ["گیر کردن تعویض ابزار"],
        "observations": ["پاکت فرسوده"],
        "mechanism": "Tool Pocket",
        "cause": "8- استهلاک قطعه یدکی",
        "diagnostic_checks": ["بازدید پاکت"],
        "corrective_actions": ["پاکت تعویض شد"],
        "verification": ["تست و تحویل شد"],
        "unresolved": False,
    }
    entry.update(overrides)
    return entry


def _package(**overrides):
    payload = {
        "equipment": "B138",
        "failure_mode": "تعویض ابزار",
        "record_count": 2,
        "records": [_record(MEMBERS[0]), _record(MEMBERS[1])],
        "focus_categories": [{
            "name": "Tool Pocket / Magazine",
            "record_ids": list(MEMBERS),
            "record_count": 2,
            "percentage": 100.0,
            "subsystems": ["magazine"],
            "symptoms": ["گیر کردن"],
            "components": ["pocket"],
            "historical_actions": ["تعویض پاکت"],
            "verification_patterns": ["تست و تحویل"],
        }],
        "recurring_patterns": ["فرسودگی پاکت"],
        "unresolved_cases": [],
    }
    payload.update(overrides)
    return payload


def test_stage_a_output_preserves_source_record_ids():
    from api import llm_knowledge_service as svc

    package, errors = svc.parse_stage_a_evidence(
        json.dumps(_package()), MEMBERS)
    assert package is not None, errors
    assert errors == []
    assert [r.record_id for r in package.records] == MEMBERS
    assert package.focus_categories[0].record_ids == MEMBERS


def test_unknown_record_id_rejected():
    from api import llm_knowledge_service as svc

    bad = _package()
    bad["records"] = [_record("K1-LLMROW-Sheet1-999")]
    package, errors = svc.parse_stage_a_evidence(json.dumps(bad), MEMBERS)
    assert package is None
    assert any("record_id" in e for e in errors)


def test_unresolved_cases_remain_unresolved():
    from api import llm_knowledge_service as svc

    payload = _package(records=[_record(MEMBERS[0], cause="", unresolved=True)],
                       unresolved_cases=["علت نامشخص برای K1-LLMROW-Sheet1-2"])
    package, errors = svc.parse_stage_a_evidence(json.dumps(payload), MEMBERS)
    assert package is not None, errors
    assert package.records[0].unresolved is True
    assert package.records[0].cause == ""
    assert package.unresolved_cases == ["علت نامشخص برای K1-LLMROW-Sheet1-2"]


def test_nonstring_recurring_patterns_rejected_without_coercion():
    """Real Stage A outputs stay fail-closed: objects are never stringified."""
    from api import llm_knowledge_service as svc

    bad = _package()
    bad["recurring_patterns"] = [{"pattern": "تکرار خرابی پاکت"}]
    bad["unresolved_cases"] = [{"case": "علت نامشخص"}]
    package, errors = svc.parse_stage_a_evidence(json.dumps(bad), MEMBERS)
    assert package is None
    assert any("recurring_patterns" in e for e in errors)
    # Nothing was coerced: rejection carries no package to persist.
    assert not any("{" in e and "pattern" in e for e in errors)


def test_math_inconsistency_invalidates_batch():
    from api import llm_knowledge_service as svc

    bad = _package()
    bad["focus_categories"] = [
        {**bad["focus_categories"][0], "record_count": 2},
        {"name": "Sensors / Feedback", "record_ids": list(MEMBERS),
         "record_count": 2, "percentage": 100.0, "subsystems": [],
         "symptoms": [], "components": [], "historical_actions": [],
         "verification_patterns": []},
    ]
    package, errors = svc.parse_stage_a_evidence(json.dumps(bad), MEMBERS)
    assert package is None
    assert any("count" in e for e in errors)


def test_malformed_and_prose_rejected():
    from api import llm_knowledge_service as svc

    for raw in ("{not json", "```json\n" + json.dumps(_package()) + "\n```",
                "Here is the evidence:\n" + json.dumps(_package())):
        package, errors = svc.parse_stage_a_evidence(raw, MEMBERS)
        assert package is None, raw[:40]
        assert errors, raw[:40]
