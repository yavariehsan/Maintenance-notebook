"""Stage B synthesis tests (Task 4): orchestration, scope isolation,
validation, persistence. LLM faked; repo_query faked. No provider calls.

TDD RED step: run_stage_b_for_build, build_stage_b_prompt and the
llm_stage_b_guide table do not exist yet.
"""
from unittest.mock import AsyncMock, patch

import pytest

EQ, FM_A, FM_B, EQ2 = "B138", "تعویض ابزار", "خرابی اسپیندل", "B139"


def _evidence_row(batch_id, eq=EQ, fm=FM_A, members=None, error=None):
    members = members if members is not None else [f"{batch_id}-r1"]
    return {
        "id": f"rec:{batch_id}",
        "build_id": "llm_knowledge_build:1",
        "source_report_id": "repair_report:a",
        "source_record_id": batch_id,
        "source_text": "six-field blocks",
        "symptom": None,
        "findings": [],
        "candidate_causes": [],
        "diagnostic_steps": [],
        "corrective_actions": [],
        "verification_steps": [],
        "post_repair_events": [],
        "stage_a_evidence": None if error else {
            "equipment": eq, "failure_mode": fm, "record_count": len(members),
            "records": [{
                "record_id": rid, "primary_focus": "Tool Pocket / Magazine",
                "symptoms": ["گیر کردن"], "observations": [], "mechanism": "",
                "cause": "", "diagnostic_checks": [], "corrective_actions": [],
                "verification": [], "unresolved": False,
            } for rid in members],
            "focus_categories": [{
                "name": "Tool Pocket / Magazine", "record_ids": members,
                "record_count": len(members), "percentage": 100.0,
                "subsystems": [], "symptoms": [], "components": [],
                "historical_actions": [], "verification_patterns": [],
            }],
            "recurring_patterns": [],
            "unresolved_cases": [],
        },
        "record_error": error,
        "created": "2026-09-30T00:00:00",
        "batch_index": 0,
        "equipment": eq,
        "failure_mode": fm,
        "batch_record_ids": members,
        "est_input_tokens": 500,
        "batch_config": {},
        "oversized": False,
    }


def _guide_markdown(percent=100.0, unresolved=True):
    sections = [
        "# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی",
        "### مرحله 1 — بررسی پاکت",
        "# دسته‌بندی کانون‌های اصلی خرابی B138",
        "| کانون اصلی | سهم تاریخی |",
        f"| پاکت | {percent} |",
        "راهنمای کاربردی تعمیر:",
        "| اولویت بررسی | سهم در سوابق |",
    ]
    if unresolved:
        sections.append("### موارد نامشخص / بدون علت قطعی")
    return "\n".join(sections)


def _repo_router(evidence_rows, saved):
    async def _repo(query, params=None):
        if "FROM llm_stage_b_guide" in query and query.strip().upper().startswith("SELECT"):
            return []
        if "FROM llm_knowledge_record" in query:
            return evidence_rows
        if query.startswith("CREATE llm_stage_b_guide"):
            saved.append(params)
            return [{"id": "llm_stage_b_guide:x"}]
        raise AssertionError(f"unexpected query: {query}")
    return _repo


def _run(evidence_rows, fake_markdown, saved=None, calls=None):
    from api import llm_knowledge_service as svc

    saved = saved if saved is not None else []
    calls = calls if calls is not None else []

    async def _fake_generate(self, system, user, max_tokens=None, structured="json"):
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        return fake_markdown() if callable(fake_markdown) else fake_markdown

    build = {"id": "llm_knowledge_build:1", "model": "model:x",
             "prompt_version": "stageab-v1"}
    return svc, _repo_router(evidence_rows, saved), _fake_generate, build, calls, saved


@pytest.mark.asyncio
async def test_all_batches_passed_to_stage_b():
    svc, router, fake, build, calls, saved = _run(
        [_evidence_row("B-A-000", members=["r1", "r2"]),
         _evidence_row("B-A-001", members=["r3"]),
         _evidence_row("B-A-002", members=["r4", "r5"])],
        _guide_markdown())
    with (
        patch.object(svc, "repo_query", new=AsyncMock(side_effect=router)),
        patch.object(svc, "_get_build_internal", new=AsyncMock(return_value=build)),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=fake),
    ):
        warnings = await svc.run_stage_b_for_build("llm_knowledge_build:1", "model:x")
    assert len(calls) == 1
    for rid in ("r1", "r2", "r3", "r4", "r5"):
        assert rid in calls[0]["user"]
    assert warnings == []
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_stage_b_receives_no_mining_output():
    svc, router, fake, build, calls, saved = _run(
        [_evidence_row("B-A-000", members=["r1"])], _guide_markdown())
    with (
        patch.object(svc, "repo_query", new=AsyncMock(side_effect=router)),
        patch.object(svc, "_get_build_internal", new=AsyncMock(return_value=build)),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=fake),
    ):
        await svc.run_stage_b_for_build("llm_knowledge_build:1", "model:x")
    blob = calls[0]["user"].lower()
    assert "troubleshootingrepository" not in blob
    assert "canonical cause" not in blob
    assert "mining" not in blob
    # The system prompt explicitly forbids these sources — the ban itself
    # is pinned here; user evidence must stay clean (asserted above).
    assert "Text Mining output" in calls[0]["system"]


@pytest.mark.asyncio
async def test_stage_b_scope_isolation():
    svc, router, fake, build, calls, saved = _run(
        [_evidence_row("B-A-000", fm=FM_A, members=["ra1"]),
         _evidence_row("B-B-000", fm=FM_B, members=["rb1"]),
         _evidence_row("B-C-000", eq=EQ2, fm=FM_A, members=["rc1"])],
        _guide_markdown())
    with (
        patch.object(svc, "repo_query", new=AsyncMock(side_effect=router)),
        patch.object(svc, "_get_build_internal", new=AsyncMock(return_value=build)),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=fake),
    ):
        await svc.run_stage_b_for_build("llm_knowledge_build:1", "model:x")
    assert len(calls) == 3
    users = " ||| ".join(c["user"] for c in calls)
    assert "ra1" in users and "rb1" in users and "rc1" in users
    for call in calls:
        others = [c for c in calls if c is not call]
        for other in others:
            assert call["user"] not in other["user"]


@pytest.mark.asyncio
async def test_denominator_uses_unique_records():
    svc, router, fake, build, calls, saved = _run(
        [_evidence_row("B-A-000", members=["r1", "r2"]),
         _evidence_row("B-A-001", members=["r2", "r3"])],
        _guide_markdown())
    with (
        patch.object(svc, "repo_query", new=AsyncMock(side_effect=router)),
        patch.object(svc, "_get_build_internal", new=AsyncMock(return_value=build)),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=fake),
    ):
        await svc.run_stage_b_for_build("llm_knowledge_build:1", "model:x")
    assert len(calls) == 1
    assert "3" in calls[0]["user"]  # unique denominator surfaced
    persisted = saved[0]
    assert sorted(persisted["val_source_record_ids"]) == ["r1", "r2", "r3"]


@pytest.mark.asyncio
async def test_stage_b_math_inconsistency_marks_invalid():
    svc, router, fake, build, calls, saved = _run(
        [_evidence_row("B-A-000", members=["r1"])],
        "# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی\n"
        "### مرحله 1 — بررسی\n"
        "# دسته‌بندی کانون‌های اصلی خرابی B138\n"
        "راهنمای کاربردی تعمیر:\n"
        "| اولویت بررسی | سهم در سوابق |\n"
        "| الف | 70 |\n| ب | 70 |\n"
        "### موارد نامشخص / بدون علت قطعی\n")
    with (
        patch.object(svc, "repo_query", new=AsyncMock(side_effect=router)),
        patch.object(svc, "_get_build_internal", new=AsyncMock(return_value=build)),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=fake),
    ):
        warnings = await svc.run_stage_b_for_build("llm_knowledge_build:1", "model:x")
    assert saved == []
    assert any("math" in w for w in warnings)


def test_stage_b_math_detects_persian_digits():
    from api import llm_knowledge_service as svc

    assert svc._check_share_table_math(
        "| اولویت بررسی | سهم در سوابق |\n| الف | ۷۰ |\n| ب | ۷۰ |"
    ) != []
    assert svc._check_share_table_math(
        "| اولویت بررسی | سهم در سوابق |\n| الف | ۱۰۰ |"
    ) == []


@pytest.mark.asyncio
async def test_unresolved_section_required():
    from api import llm_knowledge_service as svc

    system, user = svc.build_stage_b_prompt(EQ, FM_A, 2, [{"evidence": {}}])
    assert "موارد نامشخص / بدون علت قطعی" in system

    svc2, router, fake, build, calls, saved = _run(
        [_evidence_row("B-A-000", members=["r1"])],
        _guide_markdown(unresolved=False))
    with (
        patch.object(svc2, "repo_query", new=AsyncMock(side_effect=router)),
        patch.object(svc2, "_get_build_internal", new=AsyncMock(return_value=build)),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=fake),
    ):
        warnings = await svc2.run_stage_b_for_build("llm_knowledge_build:1", "model:x")
    assert saved == []
    assert any("موارد نامشخص" in w for w in warnings)


@pytest.mark.asyncio
async def test_failed_batch_skips_stage_b_with_warning():
    svc, router, fake, build, calls, saved = _run(
        [_evidence_row("B-A-000", members=["r1"], error="provider_error: boom"),
         _evidence_row("B-B-000", fm=FM_B, members=["rb1"])],
        _guide_markdown())
    with (
        patch.object(svc, "repo_query", new=AsyncMock(side_effect=router)),
        patch.object(svc, "_get_build_internal", new=AsyncMock(return_value=build)),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=fake),
    ):
        warnings = await svc.run_stage_b_for_build("llm_knowledge_build:1", "model:x")
    assert len(calls) == 1  # only the clean FM-B group synthesized
    assert "rb1" in calls[0]["user"]
    assert any("skipped" in w and FM_A in w for w in warnings)
