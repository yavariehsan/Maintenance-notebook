"""Final-guide contract tests (Task 5): Stage B syntheses are the
primary Guide output; Stage A evidence rows stay available.

TDD RED step: assemble_llm_guide has no final_guides support yet.
"""
from unittest.mock import AsyncMock, patch

import pytest

GUIDE_MD = (
    "# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی\n"
    "### مرحله 1 — بررسی پاکت\n"
    "# دسته‌بندی کانون‌های اصلی خرابی B138\n"
    "راهنمای کاربردی تعمیر:\n"
    "### موارد نامشخص / بدون علت قطعی\n"
)


def _assembly(build=None, report=None, records=None, syntheses=None):
    from api import llm_knowledge_service as svc

    build = build or {"id": "llm_knowledge_build:1", "model": "model:x",
                      "prompt_version": "stageab-v1"}
    report = report or {"id": "repair_report:a", "filename": "B.xlsx"}
    if records is None:
        records = [{
            "source_record_id": "K1-LLMBATCH-aa-000",
            "batch_record_ids": ["K1-LLMROW-Sheet1-2", "K1-LLMROW-Sheet1-3"],
        }]

    async def _repo(query, params=None):
        if "llm_stage_b_guide" in query:
            return syntheses or []
        raise AssertionError(f"unexpected query: {query}")

    return (
        patch.object(svc, "get_build", new=AsyncMock(return_value=build)),
        patch("api.repair_report_service._get_report_internal",
              new=AsyncMock(return_value=report)),
        patch.object(svc, "list_records",
                     new=AsyncMock(return_value=records)),
        patch.object(svc, "repo_query", new=AsyncMock(side_effect=_repo)),
    )


def _synthesis():
    return {
        "id": "llm_stage_b_guide:s1",
        "build_id": "llm_knowledge_build:1",
        "equipment": "B138",
        "failure_mode": "تعویض ابزار",
        "guide_markdown": GUIDE_MD,
        "record_count": 2,
        "batch_ids": ["K1-LLMBATCH-aa-000"],
        "source_record_ids": ["K1-LLMROW-Sheet1-2", "K1-LLMROW-Sheet1-3"],
        "model": "model:x",
        "prompt_version": "stageab-v1",
        "stage_b_budget": 12000,
    }


@pytest.mark.asyncio
async def test_final_guide_primary_contract():
    from api import llm_knowledge_service as svc

    patches = _assembly(syntheses=[_synthesis()])
    with patches[0], patches[1], patches[2], patches[3]:
        guide = await svc.assemble_llm_guide(
            "llm_knowledge_build:1", "repair_report:a")
    assert guide["final_guides"][0]["guide_markdown"] == GUIDE_MD
    assert guide["final_guides"][0]["equipment"] == "B138"
    assert guide["final_guides"][0]["failure_mode"] == "تعویض ابزار"
    assert guide["final_guides"][0]["record_count"] == 2
    assert guide["final_guides"][0]["synthesis_id"] == "llm_stage_b_guide:s1"


@pytest.mark.asyncio
async def test_guide_persian_sections_present():
    from api import llm_knowledge_service as svc

    patches = _assembly(syntheses=[_synthesis()])
    with patches[0], patches[1], patches[2], patches[3]:
        guide = await svc.assemble_llm_guide(
            "llm_knowledge_build:1", "repair_report:a")
    markdown = guide["final_guides"][0]["guide_markdown"]
    for marker in ("# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی",
                   "# دسته‌بندی کانون‌های اصلی خرابی",
                   "راهنمای کاربردی تعمیر:",
                   "### موارد نامشخص / بدون علت قطعی"):
        assert marker in markdown


@pytest.mark.asyncio
async def test_provenance_available_guide_to_source():
    from api import llm_knowledge_service as svc

    synthesis = _synthesis()
    patches = _assembly(syntheses=[synthesis])
    with patches[0], patches[1], patches[2], patches[3]:
        guide = await svc.assemble_llm_guide(
            "llm_knowledge_build:1", "repair_report:a")
    entry = guide["final_guides"][0]
    assert entry["batch_ids"] == ["K1-LLMBATCH-aa-000"]
    assert entry["source_record_ids"] == ["K1-LLMROW-Sheet1-2",
                                          "K1-LLMROW-Sheet1-3"]
    assert entry["synthesis_id"] == synthesis["id"]


@pytest.mark.asyncio
async def test_final_guides_scoped_to_selected_source():
    from api import llm_knowledge_service as svc

    other = _synthesis()
    other = {**other, "id": "llm_stage_b_guide:s9",
             "source_record_ids": ["Z9-LLMROW-Sheet1-9"]}
    record = {"source_record_id": "K1-LLMROW-Sheet1-2"}
    patches = _assembly(records=[record], syntheses=[_synthesis(), other])
    with patches[0], patches[1], patches[2], patches[3]:
        guide = await svc.assemble_llm_guide(
            "llm_knowledge_build:1", "repair_report:a")
    assert [g["synthesis_id"] for g in guide["final_guides"]] == [
        "llm_stage_b_guide:s1"]
