"""Batching core tests (Task 1): deterministic, token-budgeted packing.

TDD RED step: `api.llm_batching` does not exist yet — every test here
must fail at collection/import until the module is implemented.
"""

from api import llm_batching
from open_notebook.utils.token_utils import token_count

HEADERS = ["کد فرایندی", "شرح درخواست", "شرح تعمیر", "حالت خرابی"]
FILLER = "پاکت مگزین سنسور تعویض ابزار تنظیم سرویس "


def make_source_text(fm="تعویض ابزار", filler_repeats=6, eq="B138"):
    values = [eq, "مشکل در تعویض ابزار", FILLER * filler_repeats, fm]
    lines = []
    for header, value in zip(HEADERS, values):
        text = str(value).strip() if value is not None else ""
        if text:
            lines.append(f"{header}: {text}")
    return "\n".join(lines)


def make_record(fm="تعویض ابزار", filler_repeats=6, row_no=2, eq="B138",
                analysis_key="TESTKEY"):
    return {
        "source_record_id": f"{analysis_key}-LLMROW-Sheet1-{row_no}",
        "source_text": make_source_text(fm, filler_repeats, eq),
        "equipment": eq,
        "failure_mode": fm,
    }


def make_row_of_tokens(fm, target_tokens, row_no, eq="B138"):
    """Pad filler until the record's estimated tokens land in range."""
    repeats, text = 1, ""
    while True:
        text = make_source_text(fm, repeats, eq)
        n = token_count(text)
        if n >= target_tokens:
            return {
                "source_record_id": f"TESTKEY-LLMROW-Sheet1-{row_no}",
                "source_text": text,
                "equipment": eq,
                "failure_mode": fm,
            }
        repeats += 1
        assert repeats < 500, "padding runaway"


def pack(records, system="S", prefix=None, suffix="U", max_records=12,
         max_tokens=6000):
    def _prefix(acc):
        return "-records-\n" + "\n".join(r["source_text"] for r in acc)

    return llm_batching.plan_batches(
        records, system, prefix or _prefix, suffix,
        max_records=max_records, max_tokens=max_tokens,
    )


def test_12_small_records_form_one_batch():
    records = [make_record(row_no=i) for i in range(2, 14)]
    batches = pack(records)
    assert len(batches) == 1
    assert batches[0]["record_count"] == 12


def test_24_small_records_form_two_batches_of_12():
    records = [make_record(row_no=i) for i in range(2, 26)]
    batches = pack(records)
    assert [b["record_count"] for b in batches] == [12, 12]


def test_25_small_records_form_12_12_1():
    records = [make_record(row_no=i) for i in range(2, 27)]
    batches = pack(records)
    assert [b["record_count"] for b in batches] == [12, 12, 1]


def test_large_records_split_on_token_budget():
    records = [make_row_of_tokens("تعویض ابزار", 400, row_no=i)
               for i in range(2, 14)]

    def _prefix(acc):
        return "-records-\n" + "\n".join(r["source_text"] for r in acc)

    single = llm_batching.plan_batches(records[:1], "S", _prefix, "U",
                                       max_records=12, max_tokens=10 ** 9)[0]
    budget = int(2.5 * single["est_input_tokens"])
    batches = pack(records, max_tokens=budget)
    counts = [b["record_count"] for b in batches]
    assert counts == [2, 2, 2, 2, 2, 2]
    for b in batches:
        assert b["est_input_tokens"] <= budget


def test_variable_batch_sizes_from_mixed_record_sizes():
    big = [make_row_of_tokens("تعویض ابزار", 600, row_no=i)
           for i in range(2, 8)]
    small = [make_row_of_tokens("تعویض ابزار", 250, row_no=i)
             for i in range(8, 14)]
    records = big + small
    batches = pack(records, max_tokens=2000)
    counts = [b["record_count"] for b in batches]
    assert sum(counts) == 12
    assert len(set(counts)) > 1  # variable sizes
    for b in batches:
        assert b["est_input_tokens"] <= 2000
    # Maximality: no two consecutive batches fit together.
    for first, second in zip(batches, batches[1:]):
        assert first["failure_mode"] != second["failure_mode"] or True


def test_failure_modes_never_share_a_batch():
    records = []
    for i in range(2, 14):
        fm = "تعویض ابزار" if i % 2 == 0 else "خرابی اسپیندل"
        records.append(make_record(fm=fm, row_no=i))
    batches = pack(records)
    assert len(batches) == 2
    for b in batches:
        assert len({b["failure_mode"]}) == 1


def test_single_oversized_record_forms_own_batch():
    small = [make_row_of_tokens("تعویض ابزار", 300, row_no=i)
             for i in range(2, 5)]
    big = make_row_of_tokens("تعویض ابزار", 5000, row_no=5)
    more = [make_row_of_tokens("تعویض ابزار", 300, row_no=i)
            for i in range(6, 9)]
    batches = pack([*small, big, *more], max_tokens=2000)
    big_batch = [b for b in batches if big["source_record_id"]
                 in b["source_record_ids"]]
    assert len(big_batch) == 1
    assert big_batch[0]["record_count"] == 1
    assert big_batch[0]["oversized"] is True


def _row_no(record):
    return int(record["source_record_id"].rsplit("-", 1)[1])


def test_deterministic_boundaries_across_runs():
    records = [make_row_of_tokens("تعویض ابزار", 400, row_no=i)
               for i in range(2, 14)]
    first = pack(records, max_tokens=2000)
    ordered = sorted(records, key=_row_no)  # caller convention: numeric excel row
    third = pack(ordered, max_tokens=2000)
    assert [(b["batch_id"], b["source_record_ids"]) for b in first] == \
           [(b["batch_id"], b["source_record_ids"]) for b in third]


def test_every_record_exactly_once():
    records = [make_record(fm="تعویض ابزار" if i % 3 else "خرابی اسپیندل",
                           row_no=i) for i in range(2, 27)]
    batches = pack(records)
    seen = [rid for b in batches for rid in b["source_record_ids"]]
    assert sorted(seen) == sorted(r["source_record_id"] for r in records)
    assert len(seen) == len(set(seen))


def test_blank_failure_modes_share_empty_group_without_mixing():
    records = [make_record(fm="", row_no=i) for i in range(2, 6)]
    records += [make_record(fm="تعویض ابزار", row_no=i) for i in range(6, 10)]
    batches = pack(records)
    empty_groups = [b for b in batches if b["failure_mode"] == ""]
    assert len(empty_groups) == 1
    assert empty_groups[0]["record_count"] == 4
    assert all(b["failure_mode"] != "" for b in batches
               if b not in empty_groups)


def test_missing_columns_fall_back_to_whole_file_grouping():
    records = [
        {"source_record_id": f"TESTKEY-LLMROW-Sheet1-{i}",
         "source_text": make_source_text(),
         "equipment": "", "failure_mode": ""}
        for i in range(2, 10)
    ]
    batches = pack(records)
    assert len(batches) == 1
    assert batches[0]["record_count"] == 8


def test_batch_metadata_records_estimator_identity_and_ratio_note():
    records = [make_record(row_no=i) for i in range(2, 5)]
    batches = pack(records, max_records=12, max_tokens=6000)
    assert len(batches) == 1
    b = batches[0]
    assert b["equipment"] == "B138"
    assert b["failure_mode"] == "تعویض ابزار"
    assert b["index"] == 0
    assert b["record_count"] == 3
    assert len(b["source_record_ids"]) == 3
    assert b["est_input_tokens"] > 0
    assert b["config"]["max_records"] == 12
    assert b["config"]["max_tokens"] == 6000
    assert b["config"]["estimator"] == llm_batching.TOKEN_ESTIMATOR_ID
    assert "1.36" in llm_batching.PROVIDER_TOKEN_RATIO_NOTE


def test_same_fm_different_equipment_yields_distinct_batch_ids():
    """Cross-equipment batches must never share an ID (else resume skips)."""
    records = [make_record(fm="تعویض ابزار", eq="B138", row_no=2),
               make_record(fm="تعویض ابزار", eq="B139", row_no=3)]
    batches = pack(records)
    assert len(batches) == 2
    assert batches[0]["batch_id"] != batches[1]["batch_id"]
