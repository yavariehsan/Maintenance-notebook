"""Isolated E2E contract (M16): analysis worker → LLM seams → guide identity.

No database, no LLM call. Mining is stubbed; generation is represented
by schema-valid JSON verified through the REAL parser + semantic rules.
These tests pin the exact identifiers and outcome contract the analysis
worker relies on, so a silent mismatch between the stored LLM identity
and the identity Repair Guide expects fails here first.

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


def _payload(**overrides):
    payload = {
        "symptom": "لرزش بستر",
        "findings": [
            {
                "text": "سایش گاید",
                "basis": "DATA_SUPPORTED",
                "source_quote": "سایش",
            }
        ],
        "candidate_causes": [
            {"text": "خرابی گایدها", "basis": "LLM_INFERRED",
             "source_quote": None}
        ],
        "diagnostic_steps": [
            {"text": "لقی گاید کنترل شود", "basis": "LLM_INFERRED",
             "source_quote": None}
        ],
        "corrective_actions": [
            {
                "text": "گاید تعویض شد",
                "basis": "DATA_SUPPORTED",
                "source_quote": "گاید تعویض شد",
            }
        ],
        "verification_steps": [
            {
                "text": "تست شد",
                "basis": "DATA_SUPPORTED",
                "source_quote": "تست شد",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_record_identity_is_stable_and_never_filename():
    headers = ["عیب", "تعمیر"]
    rows = [["لرزش بستر", "گاید تعویض شد"], ["", None], ["تست شد", "تحویل شد"]]
    inputs = llm.extract_record_inputs("a3f9c2e1", "Sheet1", headers, rows)
    # Empty row skipped; Excel rows are 1-based (+header).
    assert [i["source_record_id"] for i in inputs] == [
        "a3f9c2e1-LLMROW-Sheet1-2",
        "a3f9c2e1-LLMROW-Sheet1-4",
    ]
    # Verbatim column text, traceable to the workbook — never rewritten.
    assert inputs[0]["source_text"] == "عیب: لرزش بستر\nتعمیر: گاید تعویض شد"
    assert "cmms.xlsx" not in inputs[0]["source_record_id"]


def test_stub_extraction_passes_real_validation_and_rules():
    raw = json.dumps(_payload(), ensure_ascii=False)
    extraction, errors = llm.parse_llm_extraction(raw)
    assert errors == []
    assert extraction is not None
    ruled = llm.apply_semantic_rules(extraction)
    assert ruled.symptom == "لرزش بستر"
    assert ruled.corrective_actions[0].basis == "DATA_SUPPORTED"
    assert ruled.verification_steps[0].text == "تست شد"


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
