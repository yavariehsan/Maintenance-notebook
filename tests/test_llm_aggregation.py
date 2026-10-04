"""Aggregation tests (Task 3): batch rows combine into one knowledge
entry per failure mode; legacy per-record rows pass through untouched.

TDD RED step: `aggregate_failure_mode_records` does not exist yet.
"""


def _batch_row(batch_id, fm, index, items_field="findings", items=None,
               symptom=None, error=None, equipment="B138"):
    return {
        "id": f"rec:{batch_id}",
        "build_id": "llm_knowledge_build:1",
        "source_report_id": "repair_report:a",
        "source_record_id": batch_id,
        "source_text": "combined",
        "symptom": symptom,
        "findings": [],
        "candidate_causes": [],
        "diagnostic_steps": [],
        "corrective_actions": [],
        "verification_steps": [],
        "post_repair_events": [],
        "record_error": error,
        "created": "2026-09-30T00:00:00",
        "batch_index": index,
        "equipment": equipment,
        "failure_mode": fm,
        "batch_record_ids": [f"r{index}a", f"r{index}b"],
        "est_input_tokens": 500,
        "batch_config": {},
        "oversized": False,
        items_field: items or [],
    }


def _item(text, basis="DATA_SUPPORTED", quote=None, supports=None):
    return {"text": text, "basis": basis, "source_quote": quote,
            "support_ids": supports or []}


def test_batches_combine_into_one_failure_mode_entry():
    from api import llm_knowledge_service as svc

    rows = [
        _batch_row("K-LLMBATCH-aaaabbbb-000", "تعویض ابزار", 0,
                   items=[_item("پاکت فرسوده", supports=["r0a"])]),
        _batch_row("K-LLMBATCH-aaaabbbb-001", "تعویض ابزار", 1,
                   items=[_item("سنسور تنظیم شد", supports=["r1a"])]),
        _batch_row("K-LLMBATCH-aaaabbbb-002", "خرابی اسپیندل", 0,
                   items=[_item("بلبرینگ خراب", supports=["r2a"])]),
    ]
    entries = svc.aggregate_failure_mode_records(rows)
    assert len(entries) == 2
    by_fm = {e["failure_mode"]: e for e in entries}
    assert len(by_fm["تعویض ابزار"]["findings"]) == 2
    assert by_fm["تعویض ابزار"]["batch_ids"] == [
        "K-LLMBATCH-aaaabbbb-000", "K-LLMBATCH-aaaabbbb-001"]
    supports = [s for item in by_fm["تعویض ابزار"]["findings"]
                for s in item["support_ids"]]
    assert sorted(supports) == ["r0a", "r1a"]
    assert len(by_fm["خرابی اسپیندل"]["findings"]) == 1
    # Aggregated entries keep the record shape the Guide renders.
    assert by_fm["تعویض ابزار"]["source_record_id"].startswith("K-LLMFM-")


def test_aggregation_dedupes_exact_duplicates_only():
    from api import llm_knowledge_service as svc

    dup = _item("پاکت فرسوده", supports=["r0a"])
    near = _item("پاکت فرسوده است", supports=["r1a"])
    rows = [
        _batch_row("K-LLMBATCH-aaaabbbb-000", "تعویض ابزار", 0, items=[dup]),
        _batch_row("K-LLMBATCH-aaaabbbb-001", "تعویض ابزار", 1,
                   items=[_item("پاکت فرسوده", supports=["r1a"]), near]),
    ]
    entries = svc.aggregate_failure_mode_records(rows)
    assert len(entries) == 1
    findings = entries[0]["findings"]
    assert len(findings) == 2  # exact dupe merged (supports united), near kept
    merged = next(i for i in findings if i["text"] == "پاکت فرسوده")
    assert sorted(merged["support_ids"]) == ["r0a", "r1a"]


def test_legacy_per_record_rows_pass_through_aggregation():
    from api import llm_knowledge_service as svc

    legacy = {
        "id": "rec:old", "build_id": "llm_knowledge_build:9",
        "source_report_id": "repair_report:z",
        "source_record_id": "abc123-LLMROW-Sheet1-2",
        "source_text": "raw", "symptom": "s",
        "findings": [_item("x")], "candidate_causes": [],
        "diagnostic_steps": [], "corrective_actions": [],
        "verification_steps": [], "post_repair_events": [],
        "record_error": None, "created": "2026-09-30T00:00:00",
    }
    entries = svc.aggregate_failure_mode_records([legacy])
    assert entries == [legacy]


def test_stage_a_rows_pass_through_aggregation_untouched():
    from api import llm_knowledge_service as svc

    stage_a = _batch_row("K-LLMBATCH-aaaabbbb-000", "تعویض ابزار", 0,
                         items=[_item("پاکت فرسوده", supports=["r0a"])])
    stage_a["stage_a_evidence"] = {"equipment": "B138",
                                   "failure_mode": "تعویض ابزار",
                                   "records": []}
    entries = svc.aggregate_failure_mode_records([stage_a])
    assert entries == [stage_a]


def test_failed_batch_members_keep_error_trace():
    from api import llm_knowledge_service as svc

    rows = [
        _batch_row("K-LLMBATCH-aaaabbbb-000", "تعویض ابزار", 0,
                   items=[_item("پاکت فرسوده", supports=["r0a"])]),
        _batch_row("K-LLMBATCH-aaaabbbb-001", "تعویض ابزار", 1,
                   error="provider_error: boom"),
    ]
    entries = svc.aggregate_failure_mode_records(rows)
    assert len(entries) == 1
    assert len(entries[0]["findings"]) == 1
    assert entries[0]["record_error"] == "provider_error: boom"


def test_aggregation_entries_distinct_across_equipment():
    from api import llm_knowledge_service as svc

    rows = [
        _batch_row("K-LLMBATCH-aaaabbbb-000", "تعویض ابزار", 0,
                   items=[_item("x", supports=["r0"])], equipment="B138"),
        _batch_row("K-LLMBATCH-aaaabbbb-000", "تعویض ابزار", 0,
                   items=[_item("y", supports=["r1"])], equipment="B139"),
    ]
    entries = svc.aggregate_failure_mode_records(rows)
    assert len(entries) == 2
    ids = [e["source_record_id"] for e in entries]
    assert len(set(ids)) == 2
