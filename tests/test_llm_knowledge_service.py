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


def _item(text, basis="DATA_SUPPORTED", quote=None):
    return {"text": text, "basis": basis, "source_quote": quote}


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
            if "FROM llm_stage_b_guide" in query:
                return []
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
        assert guide["final_guides"] == []
        assert guide["warnings"] == []

    @pytest.mark.asyncio
    async def test_empty_source_has_explicit_empty_state(self):
        build = _build_row(status="completed")

        async def _repo(query, params=None):
            if "FROM llm_knowledge_build" in query:
                return [build]
            if "FROM llm_knowledge_record" in query:
                return []
            if "FROM llm_stage_b_guide" in query:
                return []
            raise AssertionError(f"unexpected query: {query}")

        internal = {"id": "repair_report:b", "filename": "Other.pdf"}
        with patch.object(llm, "repo_query", new=AsyncMock(side_effect=_repo)), patch(
            "api.repair_report_service._get_report_internal",
            new=AsyncMock(return_value=internal),
        ):
            guide = await llm.assemble_llm_guide("llm_knowledge_build:1", "repair_report:b")
        assert guide["records"] == []
        assert guide["final_guides"] == []
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
            if "FROM llm_stage_b_guide" in query:
                return []
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
