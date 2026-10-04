"""Isolated E2E contract (M16): analysis worker → LLM seams → guide identity.

No database, no LLM call. Mining is stubbed; Stage A generation is
represented by schema-valid evidence verified through the REAL Stage A
parser. These tests pin the exact identifiers and outcome contract the
analysis worker relies on, so a silent mismatch between the stored LLM
identity and the identity Repair Guide expects fails here first.

DB-level persistence/discovery/guide-assembly are covered by
``test_llm_knowledge_service.py`` (scoping, ``assemble_llm_guide``,
deleted-source, ``no_records_for_source``); the live runtime proof runs
against an isolated DB + real UI (plan Task 5).
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api import llm_knowledge_service as llm


def test_record_identity_is_stable_and_never_filename():
    headers = ["کد فرایندی", "شرح درخواست", "شرح تعمیر", "مکانیزم خرابی",
               "دلیل بروز عیب", "حالت خرابی"]
    rows = [
        ["B138", "لرزش بستر", "گاید تعویض شد", "Tool Pocket", "استهلاک", "تعویض ابزار"],
        ["", "", "", "", "", ""],
        ["B138", "تست شد", "تحویل شد", "-", "", "تعویض ابزار"],
    ]
    plans = llm.plan_stage_a_batches("a3f9c2e1", "Sheet1", headers, rows)
    ids = [rid for plan in plans for rid in plan["source_record_ids"]]
    # Empty six-field row skipped; Excel rows are 1-based (+header).
    assert ids == [
        "a3f9c2e1-LLMROW-Sheet1-2",
        "a3f9c2e1-LLMROW-Sheet1-4",
    ]
    members = llm.plan_stage_a_records(plans[0], headers, rows)
    # Faithful six-field values, traceable to the workbook — never rewritten.
    assert members[0]["fields"]["شرح درخواست"] == "لرزش بستر"
    assert "cmms.xlsx" not in members[0]["source_record_id"]


def test_stub_evidence_passes_real_stage_a_validation():
    raw = json.dumps({
        "equipment": "B138", "failure_mode": "تعویض ابزار", "record_count": 1,
        "records": [{
            "record_id": "a3f9c2e1-LLMROW-Sheet1-2",
            "primary_focus": "Tool Pocket / Magazine",
            "symptoms": ["لرزش بستر"], "observations": [],
            "mechanism": "Tool Pocket", "cause": "استهلاک",
            "diagnostic_checks": [], "corrective_actions": ["گاید تعویض شد"],
            "verification": ["تست شد"], "unresolved": False,
        }],
        "focus_categories": [], "recurring_patterns": [],
        "unresolved_cases": [],
    }, ensure_ascii=False)
    package, errors = llm.parse_stage_a_evidence(
        raw, ["a3f9c2e1-LLMROW-Sheet1-2"])
    assert errors == []
    assert package is not None
    assert package.records[0].cause == "استهلاک"
    assert package.records[0].verification == ["تست شد"]


@pytest.mark.asyncio
async def test_run_llm_phase_maps_outcome_status():
    from commands import repair_report_commands as worker_commands

    outcome = SimpleNamespace(
        success=True, build_id="llm_knowledge_build:b1", records=1,
        failed_records=2,
    )
    with (
        patch(
            "api.llm_knowledge_service.start_build",
            new=AsyncMock(
                return_value={"id": "llm_knowledge_build:b1", "status": "queued"}
            ),
        ),
        patch.object(
            worker_commands, "_run_llm_command", new=AsyncMock(return_value=outcome)
        ),
    ):
        result = await worker_commands._run_llm_phase(["repair_report:abc123"])
    # Partial build (1 ok / 2 failed) keeps its own honest status.
    assert result == {
        "build_id": "llm_knowledge_build:b1",
        "status": "partial",
        "records": 1,
        "failed_records": 2,
    }


@pytest.mark.asyncio
async def test_run_llm_phase_reports_failed_command_explicitly():
    from commands import repair_report_commands as worker_commands

    outcome = SimpleNamespace(
        success=False, build_id="llm_knowledge_build:b1", records=0,
        failed_records=0,
    )
    with (
        patch(
            "api.llm_knowledge_service.start_build",
            new=AsyncMock(
                return_value={"id": "llm_knowledge_build:b1", "status": "queued"}
            ),
        ),
        patch.object(
            worker_commands, "_run_llm_command", new=AsyncMock(return_value=outcome)
        ),
    ):
        result = await worker_commands._run_llm_phase(["repair_report:abc123"])
    assert result is not None
    assert result["build_id"] == "llm_knowledge_build:b1"
    assert result["status"] == "failed"
