"""API + worker tests for LLM troubleshooting knowledge (M12).

Router contract (mocked service seam): build creation, idempotency
(409), validation errors, record scoping, guide provenance/empty
states. Worker behavior (injected fake LLM): partial completion,
provider failure isolation, resume without duplicates.

No live LLM calls, no database writes.
"""

import json
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api import llm_knowledge_service as llm


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _build(build_id="llm_knowledge_build:1", status="queued"):
    return {
        "id": build_id,
        "source_report_ids": ["repair_report:a"],
        "manifest": [
            {
                "report_id": "repair_report:a",
                "filename": "Sample.xlsx",
                "analysis_key": "abc123",
            }
        ],
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


def _record(report="repair_report:a", rid="abc123-LLMROW-Sheet1-2"):
    return {
        "id": "llm_knowledge_record:1",
        "build_id": "llm_knowledge_build:1",
        "source_report_id": report,
        "source_record_id": rid,
        "source_text": "عیب: لرزش",
        "symptom": "لرزش بستر",
        "findings": [],
        "candidate_causes": [],
        "diagnostic_steps": [],
        "corrective_actions": [],
        "verification_steps": [],
        "post_repair_events": [],
        "record_error": None,
        "created": "2026-09-28T10:00:00",
    }


# --- router -------------------------------------------------------------------


class TestCreateBuild:
    def test_create_build_201(self, client):
        with patch.object(
            llm, "start_build", new=AsyncMock(return_value=_build())
        ):
            resp = client.post(
                "/api/repair-reports/llm-builds",
                json={"report_ids": ["repair_report:a"]},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["build"]["id"] == "llm_knowledge_build:1"
        assert body["build"]["status"] == "queued"
        assert body["build"]["prompt_version"] == "m12-v1"

    def test_duplicate_active_build_409_with_live_id(self, client):
        with patch.object(
            llm,
            "start_build",
            new=AsyncMock(
                side_effect=llm.BuildInProgressError(
                    "llm_knowledge_build:9", "An equivalent LLM knowledge build is already in progress."
                )
            ),
        ):
            resp = client.post(
                "/api/repair-reports/llm-builds",
                json={"report_ids": ["repair_report:a"]},
            )
        assert resp.status_code == 409
        assert resp.json()["detail"]["build_id"] == "llm_knowledge_build:9"

    def test_empty_selection_400(self, client):
        from open_notebook.exceptions import InvalidInputError

        with patch.object(
            llm,
            "start_build",
            new=AsyncMock(side_effect=InvalidInputError("Select at least one.")),
        ):
            resp = client.post(
                "/api/repair-reports/llm-builds", json={"report_ids": []}
            )
        assert resp.status_code == 400

    def test_unknown_report_404(self, client):
        from open_notebook.exceptions import NotFoundError

        with patch.object(
            llm,
            "start_build",
            new=AsyncMock(side_effect=NotFoundError("Unknown repair report.")),
        ):
            resp = client.post(
                "/api/repair-reports/llm-builds",
                json={"report_ids": ["repair_report:missing"]},
            )
        assert resp.status_code == 404

    def test_unconfigured_model_422(self, client):
        from open_notebook.exceptions import ConfigurationError

        with patch.object(
            llm,
            "start_build",
            new=AsyncMock(side_effect=ConfigurationError("No language model.")),
        ):
            resp = client.post(
                "/api/repair-reports/llm-builds",
                json={"report_ids": ["repair_report:a"]},
            )
        assert resp.status_code == 422


class TestBuildReads:
    def test_list_builds_coexist(self, client):
        builds = [
            _build(build_id="llm_knowledge_build:1", status="completed"),
            _build(build_id="llm_knowledge_build:2", status="partial"),
        ]
        with patch.object(llm, "list_builds", new=AsyncMock(return_value=builds)):
            resp = client.get("/api/repair-reports/llm-builds")
        assert resp.status_code == 200
        assert [b["id"] for b in resp.json()] == [
            "llm_knowledge_build:1",
            "llm_knowledge_build:2",
        ]

    def test_get_build_and_404(self, client):
        with patch.object(llm, "get_build", new=AsyncMock(return_value=_build())):
            assert (
                client.get("/api/repair-reports/llm-builds/llm_knowledge_build:1").status_code
                == 200
            )
        from open_notebook.exceptions import NotFoundError

        with patch.object(
            llm, "get_build", new=AsyncMock(side_effect=NotFoundError("nope"))
        ):
            assert (
                client.get("/api/repair-reports/llm-builds/missing").status_code == 404
            )

    def test_records_scoped_to_source(self, client):
        seen = {}

        async def _list(build_id, source_report_id=None):
            seen["build_id"] = build_id
            seen["source_report_id"] = source_report_id
            return [_record()]

        with (
            patch.object(llm, "get_build", new=AsyncMock(return_value=_build())),
            patch.object(llm, "list_records", new=_list),
        ):
            resp = client.get(
                "/api/repair-reports/llm-builds/llm_knowledge_build:1/records",
                params={"source_report_id": "repair_report:a"},
            )
        assert resp.status_code == 200
        assert seen == {
            "build_id": "llm_knowledge_build:1",
            "source_report_id": "repair_report:a",
        }
        assert resp.json()[0]["source_record_id"] == "abc123-LLMROW-Sheet1-2"


class TestLLMGuideEndpoint:
    def _guide(self, **overrides):
        guide = {
            "knowledge_source": "LLM",
            "build_id": "llm_knowledge_build:1",
            "model": "model:chat",
            "prompt_version": "m12-v1",
            "source_report_id": "repair_report:a",
            "source_filename": "Sample.xlsx",
            "source_deleted": False,
            "records": [_record()],
            "final_guides": [],
            "warnings": [],
        }
        guide.update(overrides)
        return guide

    def test_guide_provenance(self, client):
        with patch.object(
            llm, "assemble_llm_guide", new=AsyncMock(return_value=self._guide())
        ):
            resp = client.get(
                "/api/troubleshooting/llm/guide",
                params={
                    "build_id": "llm_knowledge_build:1",
                    "source_report_id": "repair_report:a",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["knowledge_source"] == "LLM"
        assert body["build_id"] == "llm_knowledge_build:1"
        assert body["model"] == "model:chat"
        assert body["prompt_version"] == "m12-v1"
        assert body["records"][0]["source_text"] == "عیب: لرزش"

    def test_guide_empty_source_state(self, client):
        with patch.object(
            llm,
            "assemble_llm_guide",
            new=AsyncMock(
                return_value=self._guide(records=[], warnings=["no_records_for_source"])
            ),
        ):
            resp = client.get(
                "/api/troubleshooting/llm/guide",
                params={
                    "build_id": "llm_knowledge_build:1",
                    "source_report_id": "repair_report:b",
                },
            )
        assert resp.status_code == 200
        assert resp.json() == {
            **self._guide(records=[], warnings=["no_records_for_source"]),
        }

    def test_guide_deleted_source_state(self, client):
        with patch.object(
            llm,
            "assemble_llm_guide",
            new=AsyncMock(
                return_value=self._guide(
                    source_report_id="repair_report:gone",
                    source_filename=None,
                    source_deleted=True,
                    records=[],
                    warnings=["source_deleted"],
                )
            ),
        ):
            resp = client.get(
                "/api/troubleshooting/llm/guide",
                params={
                    "build_id": "llm_knowledge_build:1",
                    "source_report_id": "repair_report:gone",
                },
            )
        body = resp.json()
        assert body["source_deleted"] is True
        assert body["source_report_id"] == "repair_report:gone"

    def test_guide_unknown_build_404(self, client):
        from open_notebook.exceptions import NotFoundError

        with patch.object(
            llm,
            "assemble_llm_guide",
            new=AsyncMock(side_effect=NotFoundError("Unknown LLM knowledge build.")),
        ):
            resp = client.get(
                "/api/troubleshooting/llm/guide",
                params={"build_id": "missing", "source_report_id": "repair_report:a"},
            )
        assert resp.status_code == 404


# --- worker ---------------------------------------------------------------------


def _workbook_bytes() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(["کد فرایندی", "شرح درخواست", "شرح تعمیر", "مکانیزم خرابی",
                  "دلیل بروز عیب", "حالت خرابی"])
    sheet.append(["B138", "لرزش بستر", "پالت تعویض گردید", "Tool Pocket",
                  "8- استهلاک قطعه یدکی", "تعویض ابزار"])
    sheet.append(["B138", "صدای غیرعادی", "تست شد", "-",
                  "نامشخص", "خرابی بلبرینگ"])
    sheet.append(["B138", "داغ شدن", "موتور بررسی شد", "Overheating",
                  "نامشخص", "خرابی موتور"])  # provider failure below
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def _good_raw() -> str:
    return _stage_a_raw([
        "abc123-LLMROW-Sheet1-2",
    ])


def _stage_a_raw(member_ids):
    return json.dumps(
        {
            "equipment": "B138",
            "failure_mode": "تعویض ابزار",
            "record_count": len(member_ids),
            "records": [{
                "record_id": rid, "primary_focus": "Tool Pocket / Magazine",
                "symptoms": ["لرزش بستر"], "observations": [],
                "mechanism": "Tool Pocket", "cause": "8- استهلاک قطعه یدکی",
                "diagnostic_checks": [], "corrective_actions": ["پالت تعویض گردید"],
                "verification": [], "unresolved": False,
            } for rid in member_ids],
            "focus_categories": [],
            "recurring_patterns": [],
            "unresolved_cases": [],
        }
    )


@pytest.mark.asyncio
async def test_worker_partial_on_mixed_record_outcomes():
    """Valid + invalid + provider-error scopes → partial, all traceable."""
    from commands import llm_knowledge_commands as worker

    guide = "\n".join([
        "# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی",
        "مرحله 1.",
        "# دسته‌بندی کانون‌های اصلی خرابی B138",
        "راهنمای کاربردی تعمیر:",
        "### موارد نامشخص / بدون علت قطعی",
    ])

    async def _fake_generate(system, user, scope_id, model_id, max_tokens=None):
        if "تعویض ابزار" in user:
            return guide
        if "خرابی بلبرینگ" in user:
            return "متن بدون ساختار راهنما"
        raise RuntimeError("provider exploded")

    saved = []
    finished = {}

    async def _save(build_id, equipment, failure_mode, markdown, count,
                    batch_ids, source_ids, model, budget):
        saved.append(
            {
                "scope_id": batch_ids[0],
                "failure_mode": failure_mode,
                "markdown": markdown,
                "source_ids": source_ids,
            }
        )
        return {"id": f"g:{failure_mode}"}

    async def _finish(build_id, **kwargs):
        finished.update(kwargs)

    internal_build = _build(status="queued")
    internal_report = {
        "id": "repair_report:a",
        "filename": "Sample.xlsx",
        "analysis_key": "abc123",
    }

    worker.set_generate_fn(_fake_generate)
    try:
        with (
            patch.object(
                worker.llm_knowledge,
                "_get_build_internal",
                new=AsyncMock(return_value=internal_build),
            ),
            patch.object(
                worker.llm_knowledge,
                "_existing_stage_b_scopes",
                new=AsyncMock(return_value=set()),
            ),
            patch.object(
                worker.llm_knowledge, "mark_build_running", new=AsyncMock()
            ),
            patch.object(worker.llm_knowledge, "save_stage_b_guide", new=_save),
            patch.object(worker.llm_knowledge, "mark_build_finished", new=_finish),
            patch.object(
                worker.reports,
                "read_report_file",
                new=AsyncMock(return_value=_workbook_bytes()),
            ),
            patch.object(
                worker.reports,
                "_get_report_internal",
                new=AsyncMock(return_value=internal_report),
            ),
        ):
            result = await worker.generate_llm_knowledge_command(
                worker.GenerateLLMKnowledgeInput(build_id="llm_knowledge_build:1")
            )
    finally:
        worker.set_generate_fn(worker._default_batch_generate_fn)

    assert result.success is True
    assert result.records == 1
    assert result.failed_records == 2
    assert finished["status"] == "partial"
    assert len(saved) == 1
    assert saved[0]["markdown"] == guide  # stored AS-IS
    assert saved[0]["source_ids"] == ["abc123-LLMROW-Sheet1-2"]
    assert any("خرابی بلبرینگ" in w for w in finished.get("warnings", []))
    assert any("خرابی موتور" in w for w in finished.get("warnings", []))


@pytest.mark.asyncio
async def test_worker_skips_already_persisted_records():
    """Retry resumes: guided scopes are never generated or saved again."""
    from commands import llm_knowledge_commands as worker

    calls = []

    guide = "\n".join([
        "# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی",
        "مرحله 1.",
    ])

    async def _fake_generate(system, user, scope_id, model_id, max_tokens=None):
        calls.append(scope_id)
        return guide

    internal_build = _build(status="running")
    internal_report = {
        "id": "repair_report:a",
        "filename": "Sample.xlsx",
        "analysis_key": "abc123",
    }

    worker.set_generate_fn(_fake_generate)
    try:
        with (
            patch.object(
                worker.llm_knowledge,
                "_get_build_internal",
                new=AsyncMock(return_value=internal_build),
            ),
            patch.object(
                worker.llm_knowledge,
                "_existing_stage_b_scopes",
                new=AsyncMock(return_value={("B138", "تعویض ابزار")}),
            ),
            patch.object(
                worker.llm_knowledge, "mark_build_running", new=AsyncMock()
            ),
            patch.object(
                worker.llm_knowledge,
                "save_stage_b_guide",
                new=AsyncMock(return_value={"id": "g:x"}),
            ) as mock_save,
            patch.object(
                worker.llm_knowledge,
                "mark_build_finished",
                new=AsyncMock(),
            ),
            patch.object(
                worker.reports,
                "read_report_file",
                new=AsyncMock(return_value=_workbook_bytes()),
            ),
            patch.object(
                worker.reports,
                "_get_report_internal",
                new=AsyncMock(return_value=internal_report),
            ),
        ):
            result = await worker.generate_llm_knowledge_command(
                worker.GenerateLLMKnowledgeInput(build_id="llm_knowledge_build:1")
            )
    finally:
        worker.set_generate_fn(worker._default_batch_generate_fn)

    assert len(calls) == 2
    assert mock_save.await_count == 2
    assert result.records == 3  # 1 resumed + 2 fresh


@pytest.mark.asyncio
async def test_worker_completed_build_is_idempotent():
    from commands import llm_knowledge_commands as worker

    internal_build = _build(status="completed")
    internal_build["record_count"] = 5
    internal_build["failed_record_count"] = 1
    with patch.object(
        worker.llm_knowledge,
        "_get_build_internal",
        new=AsyncMock(return_value=internal_build),
    ):
        result = await worker.generate_llm_knowledge_command(
            worker.GenerateLLMKnowledgeInput(build_id="llm_knowledge_build:1")
        )
    assert result.success is True
    assert result.records == 5
    assert result.failed_records == 1


def test_llm_task_family_listed_without_touching_mining():
    """generate_llm_knowledge commands surface on /tasks as llm_knowledge."""
    from fastapi.testclient import TestClient as TC

    from api.main import app as _app

    async def _repo(query, params=None):
        if "generate_llm_knowledge" in query:
            return [
                {
                    "id": "command:llm1",
                    "status": "running",
                    "args": {"build_id": "llm_knowledge_build:1"},
                    "result": None,
                    "error_message": None,
                    "created": "2026-09-28T10:00:00",
                    "updated": None,
                    "progress_processed": None,
                    "progress_total": None,
                    "started_at": None,
                    "updated_at": "2026-09-28T10:05:00",
                }
            ]
        if "analyze_repair_reports" in query:
            return []
        if "FROM llm_knowledge_build" in query:
            return [
                {"id": "llm_knowledge_build:1", "source_report_ids": ["repair_report:a"]}
            ]
        if "FROM repair_report" in query:
            return [{"id": "repair_report:a", "filename": "Sample.xlsx"}]
        if "FROM command" in query:
            return []
        if "FROM source" in query:
            return []
        raise AssertionError(f"unexpected query: {query}")

    with patch(
        "open_notebook.database.repository.repo_query", new=AsyncMock(side_effect=_repo)
    ):
        resp = TC(_app).get("/api/tasks")
    assert resp.status_code == 200
    (task,) = resp.json()
    assert task["item_type"] == "llm_knowledge"
    assert task["command_name"] == "generate_llm_knowledge"
    assert task["title"] == "Sample.xlsx"
