"""Stage A six-field input contract tests (Task 1).

TDD RED step: STAGE_A_FIELDS, extract_stage_a_values,
serialize_stage_a_record, build_stage_a_prompt and plan_stage_a_batches
do not exist yet — these tests must fail until implemented.
"""

SIX = ["کد فرایندی", "شرح درخواست", "شرح تعمیر",
       "مکانیزم خرابی", "دلیل بروز عیب", "حالت خرابی"]

# Real B138 values (Sample-1.xlsx rows 27-29: تعویض ابزار scope), six fields only.
B138_ROWS = [
    {"کد فرایندی": "B138", "شرح درخواست": "گیر کردن تعویض ابزار",
     "شرح تعمیر": "پاکت مگزین تعویض شد", "مکانیزم خرابی": "Tool Pocket",
     "دلیل بروز عیب": "8- استهلاک قطعه یدکی", "حالت خرابی": "تعویض ابزار"},
    {"کد فرایندی": "B138", "شرح درخواست": "مشکل در تعویض ابزار",
     "شرح تعمیر": "سنسور تنظیم شد", "مکانیزم خرابی": "-",
     "دلیل بروز عیب": "8- استهلاک قطعه یدکی", "حالت خرابی": "تعویض ابزار"},
    {"کد فرایندی": "B138", "شرح درخواست": "عدم تعویض ابزار",
     "شرح تعمیر": "تست و تحویل شد", "مکانیزم خرابی": "",
     "دلیل بروز عیب": "", "حالت خرابی": "تعویض ابزار"},
]


def _headers(extra=None):
    heads = list(SIX) + ["تاریخ درخواست", "درخت تکنیکال", "t1"]
    if extra:
        heads.append(extra)
    return heads


def _row(values, headers):
    return [values.get(h, "") for h in headers]


def _b138_sheet_rows(n, fm="تعویض ابزار"):
    headers = _headers()
    rows = []
    for i in range(n):
        base = dict(B138_ROWS[i % len(B138_ROWS)])
        base["حالت خرابی"] = fm
        rows.append(_row(base, headers))
    return headers, rows


def test_only_six_columns_enter_stage_a():
    from api import llm_knowledge_service as svc

    headers = _headers()
    values = _row({**B138_ROWS[0], "تاریخ درخواست": "1402/09/01",
                   "درخت تکنیکال": "MACHINE TOOLS", "t1": "MACHINE TOOLS"},
                  headers)
    extracted = svc.extract_stage_a_values(headers, values)
    assert set(extracted) == set(SIX)
    text = svc.serialize_stage_a_record(extracted)
    assert "1402/09/01" not in text
    assert "MACHINE TOOLS" not in text
    assert "گیر کردن تعویض ابزار" in text
    assert text.count("\n") == 5  # exactly six lines


def test_no_seventh_field_possible():
    from api import llm_knowledge_service as svc

    headers = _headers(extra="حالت خرابی پیشنهادی")
    values = _row({**B138_ROWS[0], "حالت خرابی پیشنهادی": "تعویض ابزار (پیشنهادی)"},
                  headers)
    extracted = svc.extract_stage_a_values(headers, values)
    assert set(extracted) == set(SIX)
    assert "پیشنهادی" not in svc.serialize_stage_a_record(extracted)


def test_blank_fields_emitted_empty_not_dropped():
    from api import llm_knowledge_service as svc

    extracted = svc.extract_stage_a_values(SIX, ["B138", "", "", "", "", ""])
    text = svc.serialize_stage_a_record(extracted)
    lines = text.split("\n")
    assert len(lines) == 6
    assert lines[1] == "شرح درخواست: "


def test_dash_literal_preserved():
    from api import llm_knowledge_service as svc

    extracted = svc.extract_stage_a_values(SIX, ["B138", "x", "y", "-", "z", "w"])
    text = svc.serialize_stage_a_record(extracted)
    assert "مکانیزم خرابی: -" in text
    assert "unknown" not in text.lower()


def test_same_fm_stays_one_semantic_group():
    from api import llm_knowledge_service as svc

    headers, rows = _b138_sheet_rows(32)
    plans = svc.plan_stage_a_batches("K1", "Sheet1", headers, rows)
    assert plans, "expected batches for 32 same-FM rows"
    assert {p["failure_mode"] for p in plans} == {"تعویض ابزار"}
    assert {p["equipment"] for p in plans} == {"B138"}
    seen = [rid for p in plans for rid in p["source_record_ids"]]
    assert len(seen) == 32 and len(set(seen)) == 32


def test_24_records_become_12_plus_12():
    from api import llm_knowledge_service as svc

    headers, rows = _b138_sheet_rows(24)
    plans = svc.plan_stage_a_batches("K1", "Sheet1", headers, rows)
    assert [p["record_count"] for p in plans] == [12, 12]


def test_25_records_become_12_12_1():
    from api import llm_knowledge_service as svc

    headers, rows = _b138_sheet_rows(25)
    plans = svc.plan_stage_a_batches("K1", "Sheet1", headers, rows)
    assert [p["record_count"] for p in plans] == [12, 12, 1]


def test_fm_fitting_capacity_sent_as_one_batch():
    from api import llm_knowledge_service as svc

    headers, rows = _b138_sheet_rows(5)
    plans = svc.plan_stage_a_batches("K1", "Sheet1", headers, rows)
    assert len(plans) == 1
    assert plans[0]["record_count"] == 5


def test_deterministic_ordering_preserved():
    from api import llm_knowledge_service as svc

    headers, rows = _b138_sheet_rows(14)
    first = svc.plan_stage_a_batches("K1", "Sheet1", headers, rows)
    second = svc.plan_stage_a_batches("K1", "Sheet1", headers, rows)
    assert [(p["batch_id"], p["source_record_ids"]) for p in first] == \
           [(p["batch_id"], p["source_record_ids"]) for p in second]
    ids = [rid for p in first for rid in p["source_record_ids"]]
    assert ids == sorted(ids, key=lambda r: int(r.rsplit("-", 1)[1]))


def test_est_matches_built_prompt():
    from api import llm_batching as batching
    from api import llm_knowledge_service as svc

    headers, rows = _b138_sheet_rows(4)
    plans = svc.plan_stage_a_batches("K1", "Sheet1", headers, rows)
    assert len(plans) == 1
    members = svc.plan_stage_a_records(plans[0], headers, rows)
    system, user = svc.build_stage_a_prompt(
        plans[0]["equipment"], plans[0]["failure_mode"], members)
    assert plans[0]["est_input_tokens"] == batching.estimate_batch_tokens(system, user)
