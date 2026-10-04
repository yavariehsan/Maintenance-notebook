"""Scope worker tests: six-field scopes, budgets, duplicates,
resume, preflight gate. Seam fakes use the 5-arg scope signature
(system, user, scope_id, model_id, max_tokens).
"""
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest

HEADERS = ["کد فرایندی", "شرح درخواست", "شرح تعمیر", "حالت خرابی",
           "تاریخ درخواست", "درخت تکنیکال"]


def _workbook_bytes() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(HEADERS)
    sheet.append(["B138", "گیر کردن تعویض ابزار", "پاکت تعویض شد",
                  "تعویض ابزار", "1402/09/01", "MACHINE TOOLS"])
    sheet.append(["B138", "لرزش اسپیندل", "بلبرینگ تعویض شد",
                  "خرابی اسپیندل", "1402/09/02", "MACHINE TOOLS"])
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def _guide_raw():
    return "\n".join([
        "# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی",
        "### مرحله 1 — توقف و ثبت آلارم",
        "# دسته‌بندی کانون‌های اصلی خرابی B138",
        "راهنمای کاربردی تعمیر:",
        "### موارد نامشخص / بدون علت قطعی",
    ])


def _build(status="queued"):
    return {
        "id": "llm_knowledge_build:1",
        "source_report_ids": ["repair_report:a"],
        "manifest": [{"report_id": "repair_report:a", "filename": "B.xlsx",
                      "analysis_key": "abc123"}],
        "status": status,
        "command_id": None,
        "model": "model:x",
        "prompt_version": "stageab-v1",
        "error": None,
        "warnings": [],
        "record_count": None,
        "failed_record_count": None,
        "created": "2026-09-30T00:00:00",
        "started_at": None,
        "finished_at": None,
    }


def _report():
    return {"id": "repair_report:a", "filename": "B.xlsx", "analysis_key": "abc123"}


def _run_worker(worker, fake, saved, finished, build=None, manifest=None):
    async def _save_guide(build_id, equipment, failure_mode, markdown, count,
                          batch_ids, source_ids, model, budget):
        saved.append({"scope_id": batch_ids[0], "equipment": equipment,
                      "failure_mode": failure_mode, "markdown": markdown,
                      "source_ids": source_ids})
        return {"id": f"g:{batch_ids[0]}"}

    internal = build or _build()
    if manifest is not None:
        internal = {**internal, "manifest": manifest}
    worker.set_generate_fn(fake)
    patches = (
        patch.object(worker.llm_knowledge, "_get_build_internal",
                     new=AsyncMock(return_value=internal)),
        patch.object(worker.llm_knowledge, "_existing_stage_b_scopes",
                     new=AsyncMock(return_value=set())),
        patch.object(worker.llm_knowledge, "mark_build_running", new=AsyncMock()),
        patch.object(worker.llm_knowledge, "save_stage_b_guide", new=_save_guide),
        patch.object(worker.llm_knowledge, "mark_build_finished",
                     new=AsyncMock(side_effect=lambda bid, **kw: finished.update(kw))),
        patch.object(worker.reports, "read_report_file",
                     new=AsyncMock(return_value=_workbook_bytes())),
        patch.object(worker.reports, "_get_report_internal",
                     new=AsyncMock(return_value=_report())),
        patch.object(worker.llm_knowledge, "resolve_llm_model_id",
                     new=AsyncMock(return_value="model:x")),
    )
    return patches


@pytest.mark.asyncio
async def test_stage_a_ids_preserved_end_to_end():
    from commands import llm_knowledge_commands as worker

    seen = {}

    async def _fake(system, user, scope_id, model_id, max_tokens):
        seen[scope_id] = user
        assert "تاریخ درخواست" not in user
        assert "MACHINE TOOLS" not in user
        assert "گیر کردن تعویض ابزار" in user or "لرزش اسپیندل" in user
        return _guide_raw()

    saved, finished = [], {}
    try:
        patches = _run_worker(worker, _fake, saved, finished)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            result = await worker.generate_llm_knowledge_command(
                worker.GenerateLLMKnowledgeInput(build_id="llm_knowledge_build:1")
            )
    finally:
        worker.set_generate_fn(worker._default_batch_generate_fn)
    assert result.success is True
    assert len(seen) == 2  # two failure modes → two scopes
    assert finished["status"] == "completed"
    for item in saved:
        assert item["markdown"] == _guide_raw()  # stored AS-IS


@pytest.mark.asyncio
async def test_duplicate_source_record_ids_detected():
    from commands import llm_knowledge_commands as worker

    calls = []

    async def _fake(system, user, scope_id, model_id, max_tokens):
        calls.append(scope_id)
        return _guide_raw()

    saved, finished = [], {}
    dup_manifest = [
        {"report_id": "repair_report:a", "filename": "B.xlsx", "analysis_key": "abc123"},
        {"report_id": "repair_report:a", "filename": "B.xlsx", "analysis_key": "abc123"},
    ]
    warnings = {}

    async def _finish(build_id, **kwargs):
        finished.update(kwargs)
        warnings.update(kwargs)

    try:
        patches = _run_worker(worker, _fake, saved, finished, manifest=dup_manifest)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            # swap finish capture for warnings visibility
            with patch.object(worker.llm_knowledge, "mark_build_finished", new=_finish):
                await worker.generate_llm_knowledge_command(
                    worker.GenerateLLMKnowledgeInput(build_id="llm_knowledge_build:1")
                )
    finally:
        worker.set_generate_fn(worker._default_batch_generate_fn)
    assert len(calls) == 2  # duplicate manifest entry did not regenerate
    assert any("duplicate" in w for w in warnings.get("warnings", []))


@pytest.mark.asyncio
async def test_retry_resume_preserves_stage_a_and_lifecycle():
    from commands import llm_knowledge_commands as worker

    calls = []

    async def _fake(system, user, scope_id, model_id, max_tokens):
        calls.append(scope_id)
        return _guide_raw()

    finished = {}
    try:
        worker.set_generate_fn(_fake)
        with (
            patch.object(worker.llm_knowledge, "_get_build_internal",
                         new=AsyncMock(return_value=_build(status="running"))),
            patch.object(worker.llm_knowledge, "_existing_stage_b_scopes",
                         new=AsyncMock(return_value={("B138", "تعویض ابزار")})),
            patch.object(worker.llm_knowledge, "mark_build_running", new=AsyncMock()),
            patch.object(worker.llm_knowledge, "save_stage_b_guide",
                         new=AsyncMock(return_value={"id": "g:x"})) as mock_save,
            patch.object(worker.llm_knowledge, "mark_build_finished",
                         new=AsyncMock(side_effect=lambda bid, **kw: finished.update(kw))),
            patch.object(worker.reports, "read_report_file",
                         new=AsyncMock(return_value=_workbook_bytes())),
            patch.object(worker.reports, "_get_report_internal",
                         new=AsyncMock(return_value=_report())),
            patch.object(worker.llm_knowledge, "resolve_llm_model_id",
                         new=AsyncMock(return_value="model:x")),
        ):
            result = await worker.generate_llm_knowledge_command(
                worker.GenerateLLMKnowledgeInput(build_id="llm_knowledge_build:1")
            )
    finally:
        worker.set_generate_fn(worker._default_batch_generate_fn)
    assert len(calls) == 1  # guided scope skipped
    assert mock_save.await_count == 1
    assert result.records == 2  # 1 resumed + 1 fresh
    assert finished["status"] == "completed"


@pytest.mark.asyncio
async def test_preflight_failure_blocks_build():
    from unittest.mock import AsyncMock

    from api.llm_generation import preflight_llm_generation
    from open_notebook.exceptions import ConfigurationError

    with patch("api.llm_generation.LLMKnowledgeGenerator") as gen:
        gen.return_value.generate_from_messages = AsyncMock(return_value="prose, not json")
        with pytest.raises(ConfigurationError):
            await preflight_llm_generation("model:x")
        assert gen.return_value.generate_from_messages.await_count == 1
