"""Tests for the LLM troubleshooting-knowledge service (M12).

Covers the knowledge model, LLM-output validation, engine semantic
rules, source isolation, guide assembly, and build idempotency — all
without an LLM call or a database (repo_query is the single mock seam).
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from api import llm_knowledge_service as llm
from open_notebook.exceptions import NotFoundError

# --- fixtures ---------------------------------------------------------------


def _item(text, basis="DATA_SUPPORTED", quote=None):
    return {"text": text, "basis": basis, "source_quote": quote}


def _valid_payload(**overrides):
    payload = {
        "symptom": "Bed vibration",
        "findings": [_item("Gib wear observed", "DATA_SUPPORTED", "gib worn")],
        "candidate_causes": [_item("Worn gibs", "LLM_INFERRED")],
        "diagnostic_steps": [_item("Check gib clearance")],
        "corrective_actions": [_item("Gibs replaced", "DATA_SUPPORTED", "gibs replaced")],
        "verification_steps": [_item("Test run OK", "DATA_SUPPORTED", "test ok")],
    }
    payload.update(overrides)
    return payload


def _extraction(**overrides):
    extraction, errors = llm.parse_llm_extraction(json.dumps(_valid_payload(**overrides)))
    assert extraction is not None, errors
    return extraction


# --- structured output contract (§6, §11) -------------------------------------


class TestParseValidation:
    def test_valid_structured_response(self):
        extraction, errors = llm.parse_llm_extraction(json.dumps(_valid_payload()))
        assert errors == []
        assert extraction is not None
        assert extraction.symptom == "Bed vibration"
        assert extraction.candidate_causes[0].basis == "LLM_INFERRED"

    def test_markdown_fences_tolerated(self):
        raw = "```json\n" + json.dumps(_valid_payload()) + "\n```"
        extraction, errors = llm.parse_llm_extraction(raw)
        assert extraction is not None, errors

    def test_malformed_json_rejected(self):
        extraction, errors = llm.parse_llm_extraction("{not json")
        assert extraction is None
        assert any("malformed_json" in e for e in errors)

    def test_empty_response_rejected(self):
        for raw in (None, "", "   ", "```\n```"):
            extraction, errors = llm.parse_llm_extraction(raw)
            assert extraction is None
            assert errors == ["empty_response"]

    def test_top_level_list_rejected(self):
        extraction, errors = llm.parse_llm_extraction(json.dumps([_item("x")]))
        assert extraction is None
        assert any("unexpected_output_shape" in e for e in errors)

    def test_missing_required_field_rejected(self):
        payload = _valid_payload()
        del payload["corrective_actions"]
        extraction, errors = llm.parse_llm_extraction(json.dumps(payload))
        assert extraction is None
        assert errors == ["missing_required_field: corrective_actions"]

    def test_missing_symptom_key_rejected(self):
        payload = _valid_payload()
        del payload["symptom"]
        extraction, errors = llm.parse_llm_extraction(json.dumps(payload))
        assert extraction is None
        assert errors == ["missing_required_field: symptom"]

    def test_invalid_basis_rejected(self):
        payload = _valid_payload(
            findings=[{"text": "x", "basis": "HISTORICAL_FACT"}]
        )
        extraction, errors = llm.parse_llm_extraction(json.dumps(payload))
        assert extraction is None
        assert any("invalid_enum" in e and "basis" in e for e in errors)

    def test_empty_item_text_rejected(self):
        payload = _valid_payload(findings=[{"text": "  ", "basis": "DATA_SUPPORTED"}])
        extraction, errors = llm.parse_llm_extraction(json.dumps(payload))
        assert extraction is None
        assert any("text is empty" in e for e in errors)

    def test_explicit_empty_lists_are_valid_unknown(self):
        payload = _valid_payload(
            symptom=None,
            candidate_causes=[],
            corrective_actions=[],
        )
        extraction, errors = llm.parse_llm_extraction(json.dumps(payload))
        assert extraction is not None, errors
        assert extraction.symptom is None
        assert extraction.corrective_actions == []

    def test_extra_fields_warn_not_fail(self):
        payload = _valid_payload(some_future_field="kept-out")
        extraction, errors = llm.parse_llm_extraction(json.dumps(payload))
        assert extraction is not None
        assert errors == ["warning: unexpected_field_ignored: some_future_field"]

    def test_basis_values_never_collapsed(self):
        extraction, _ = llm.parse_llm_extraction(json.dumps(_valid_payload()))
        assert extraction is not None
        bases = {item.basis for item in extraction.findings + extraction.candidate_causes}
        assert bases == {"DATA_SUPPORTED", "LLM_INFERRED"}


# --- semantic rules (§8) -------------------------------------------------------


class TestSemanticRules:
    def test_standalone_test_note_is_verification_not_action(self):
        extraction = _extraction(corrective_actions=[_item("تست شد")])
        ruled = llm.apply_semantic_rules(extraction)
        assert ruled.corrective_actions == []
        assert [item.text for item in ruled.verification_steps] == [
            "Test run OK",
            "تست شد",
        ]

    def test_test_and_handover_produces_verification_plus_event(self):
        extraction = _extraction(corrective_actions=[_item("تست و تحویل شد")])
        ruled = llm.apply_semantic_rules(extraction)
        assert ruled.corrective_actions == []
        assert "تست و تحویل شد" in [item.text for item in ruled.verification_steps]
        assert "تست و تحویل شد" in [item.text for item in ruled.post_repair_events]

    def test_pure_handover_is_event_not_action(self):
        extraction = _extraction(corrective_actions=[_item("دستگاه تحویل شد")])
        ruled = llm.apply_semantic_rules(extraction)
        assert ruled.corrective_actions == []
        assert [item.text for item in ruled.post_repair_events] == ["دستگاه تحویل شد"]

    def test_outcome_only_is_verification_not_action(self):
        extraction = _extraction(corrective_actions=[_item("مشکل رفع شد")])
        ruled = llm.apply_semantic_rules(extraction)
        assert ruled.corrective_actions == []
        assert "مشکل رفع شد" in [item.text for item in ruled.verification_steps]

    def test_genuine_repair_action_survives(self):
        extraction = _extraction(
            corrective_actions=[_item("پالت تعویض و سوئیچ تنظیم گردید")]
        )
        ruled = llm.apply_semantic_rules(extraction)
        assert [item.text for item in ruled.corrective_actions] == [
            "پالت تعویض و سوئیچ تنظیم گردید"
        ]

    def test_provenance_preserved_through_refile(self):
        extraction = _extraction(
            corrective_actions=[_item("تست شد", basis="LLM_INFERRED")]
        )
        ruled = llm.apply_semantic_rules(extraction)
        moved = next(
            item for item in ruled.verification_steps if item.text == "تست شد"
        )
        assert moved.basis == "LLM_INFERRED"

    def test_prompt_encodes_generation_rules(self):
        system, user = llm.build_extraction_prompt("symptom: noise", "RID-1")
        for rule in (
            "ONLY the supplied source material",
            "Do not invent components",
            "Do not invent measurements",
            "NOT a corrective action",
            "verification step, never a corrective action",
            "DATA_SUPPORTED",
            "LLM_INFERRED",
            "JSON ONLY",
            "insufficient",
        ):
            assert rule in system
        assert "RID-1" in user and "symptom: noise" in user


# --- deterministic record extraction -------------------------------------------


class TestRecordExtraction:
    def test_source_text_verbatim_and_skips_empties(self):
        text = llm.build_record_source_text(
            ["عیب", "اقدام", "خالی"], ["لرزش بستر", "  ", None]
        )
        assert text == "عیب: لرزش بستر"

    def test_stable_record_ids_not_filenames(self):
        inputs = llm.extract_record_inputs(
            "abc123", "Sheet1", ["a", "b"], [["x", "y"], ["", None], ["z", "w"]]
        )
        assert [i["source_record_id"] for i in inputs] == [
            "abc123-LLMROW-Sheet1-2",
            "abc123-LLMROW-Sheet1-4",
        ]
        assert inputs[0]["source_text"] == "a: x\nb: y"


# --- build lifecycle + idempotency (§4, §12, §20) --------------------------------


def _build_row(build_id="llm_knowledge_build:1", status="queued", **overrides):
    row = {
        "id": build_id,
        "source_report_ids": ["repair_report:a"],
        "manifest": [],
        "status": status,
        "command_id": None,
        "model": "model:chat",
        "prompt_version": "m12-v1",
        "error": None,
        "warnings": [],
        "record_count": None,
        "failed_record_count": None,
        "created": "2026-09-28T10:00:00",
        "started_at": None,
        "finished_at": None,
    }
    row.update(overrides)
    return row


class TestBuildLifecycle:
    @pytest.mark.asyncio
    async def test_repeated_active_build_returns_same_build(self):
        live = _build_row(status="running", command_id="command:live")
        with patch.object(
            llm, "repo_query", new=AsyncMock(return_value=[live])
        ), patch(
            "api.repair_report_service._read_command",
            new=AsyncMock(
                return_value={"id": "command:live", "status": "new"}
            ),
        ):
            active = await llm.find_active_build_for_reports(["repair_report:a"])
        assert active is not None
        assert active["id"] == "llm_knowledge_build:1"

    @pytest.mark.asyncio
    async def test_different_report_set_does_not_block(self):
        live = _build_row(status="running", command_id="command:live")
        with patch.object(
            llm, "repo_query", new=AsyncMock(return_value=[live])
        ), patch(
            "api.repair_report_service._read_command",
            new=AsyncMock(return_value={"id": "command:live", "status": "new"}),
        ):
            active = await llm.find_active_build_for_reports(["repair_report:b"])
        assert active is None

    @pytest.mark.asyncio
    async def test_stale_build_finalized_not_returned(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        stale = _build_row(
            status="running",
            command_id="command:dead",
            started_at=old,
            created=old,
        )
        updates = []

        async def _repo(query, params=None):
            if "FROM llm_knowledge_build" in query:
                return [stale]
            if query.startswith("UPDATE"):
                updates.append((query, params))
                return []
            raise AssertionError(f"unexpected query: {query}")

        with patch.object(
            llm, "repo_query", new=AsyncMock(side_effect=_repo)
        ), patch(
            "api.repair_report_service._read_command",
            new=AsyncMock(
                return_value={
                    "id": "command:dead",
                    "status": "running",
                    "updated_at": old,
                }
            ),
        ):
            active = await llm.find_active_build_for_reports(["repair_report:a"])
        assert active is None
        assert any(
            params.get("status") == "failed" for _, params in updates
        ), "stale build must be failed explicitly"

    @pytest.mark.asyncio
    async def test_completed_build_remains_queryable(self):
        done = _build_row(status="completed", record_count=3)
        with patch.object(llm, "repo_query", new=AsyncMock(return_value=[done])):
            build = await llm.get_build("llm_knowledge_build:1")
        assert build["status"] == "completed"
        assert build["record_count"] == 3

    @pytest.mark.asyncio
    async def test_unknown_build_404(self):
        with patch.object(llm, "repo_query", new=AsyncMock(return_value=[])):
            with pytest.raises(NotFoundError):
                await llm.get_build("llm_knowledge_build:missing")


# --- source isolation + guide assembly (§5, §15–§18) -------------------------------


def _stored_record(build="llm_knowledge_build:1", report="repair_report:a", rid="k-ROW-2"):
    return {
        "id": "llm_knowledge_record:1",
        "build_id": build,
        "source_report_id": report,
        "source_record_id": rid,
        "source_text": "عیب: لرزش",
        "symptom": "لرزش بستر",
        "findings": [_item("wear", "DATA_SUPPORTED", "worn")],
        "candidate_causes": [_item("worn gibs", "LLM_INFERRED")],
        "diagnostic_steps": [],
        "corrective_actions": [],
        "verification_steps": [],
        "post_repair_events": [],
        "record_error": None,
        "created": "2026-09-28T10:00:00",
    }


class TestGuideAssembly:
    @pytest.mark.asyncio
    async def test_only_selected_source_returned(self):
        build = _build_row(status="completed")
        record_a = _stored_record()

        async def _repo(query, params=None):
            if "FROM llm_knowledge_build" in query:
                return [build]
            if "FROM llm_knowledge_record" in query:
                # Scoped query must carry the report filter.
                assert "source_report_id" in query
                assert str(params.get("sid")) == "repair_report:a"
                return [record_a]
            raise AssertionError(f"unexpected query: {query}")

        internal = {"id": "repair_report:a", "filename": "Machine Bed.pdf"}
        with patch.object(llm, "repo_query", new=AsyncMock(side_effect=_repo)), patch(
            "api.repair_report_service._get_report_internal",
            new=AsyncMock(return_value=internal),
        ):
            guide = await llm.assemble_llm_guide("llm_knowledge_build:1", "repair_report:a")
        assert guide["knowledge_source"] == "LLM"
        assert guide["build_id"] == "llm_knowledge_build:1"
        assert guide["source_deleted"] is False
        assert [r["source_record_id"] for r in guide["records"]] == ["k-ROW-2"]
        assert guide["warnings"] == []

    @pytest.mark.asyncio
    async def test_empty_source_has_explicit_empty_state(self):
        build = _build_row(status="completed")

        async def _repo(query, params=None):
            if "FROM llm_knowledge_build" in query:
                return [build]
            if "FROM llm_knowledge_record" in query:
                return []
            raise AssertionError(f"unexpected query: {query}")

        internal = {"id": "repair_report:b", "filename": "Other.pdf"}
        with patch.object(llm, "repo_query", new=AsyncMock(side_effect=_repo)), patch(
            "api.repair_report_service._get_report_internal",
            new=AsyncMock(return_value=internal),
        ):
            guide = await llm.assemble_llm_guide("llm_knowledge_build:1", "repair_report:b")
        assert guide["records"] == []
        assert guide["warnings"] == ["no_records_for_source"]

    @pytest.mark.asyncio
    async def test_deleted_source_never_remaps(self):
        build = _build_row(status="completed")
        record_a = _stored_record()

        async def _repo(query, params=None):
            if "FROM llm_knowledge_build" in query:
                return [build]
            if "FROM llm_knowledge_record" in query:
                return [record_a]
            raise AssertionError(f"unexpected query: {query}")

        with patch.object(llm, "repo_query", new=AsyncMock(side_effect=_repo)), patch(
            "api.repair_report_service._get_report_internal",
            new=AsyncMock(side_effect=NotFoundError("gone")),
        ):
            guide = await llm.assemble_llm_guide(
                "llm_knowledge_build:1", "repair_report:deleted"
            )
        assert guide["source_deleted"] is True
        assert guide["source_report_id"] == "repair_report:deleted"
        assert guide["warnings"] == ["source_deleted"]

    @pytest.mark.asyncio
    async def test_builds_versioned_not_destroyed(self):
        builds = [
            _build_row(build_id="llm_knowledge_build:1", status="completed"),
            _build_row(build_id="llm_knowledge_build:2", status="completed"),
        ]
        with patch.object(llm, "repo_query", new=AsyncMock(return_value=builds)):
            listed = await llm.list_builds()
        assert [b["id"] for b in listed] == [
            "llm_knowledge_build:1",
            "llm_knowledge_build:2",
        ]
