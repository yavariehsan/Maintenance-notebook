"""LLM analysis integration (M16): analysis auto-triggers LLM knowledge.

Task 1: the LLM worker command must be registered on the worker entry
package (``surreal-commands-worker --import-modules commands``).
Task 2: normal analysis must trigger LLM generation inline (sequential),
without letting LLM failures fail the mining output.
"""

from unittest.mock import AsyncMock, patch

import pytest


def test_llm_command_registered_on_worker_package():
    import commands

    assert callable(commands.generate_llm_knowledge_command)


@pytest.mark.asyncio
async def test_create_build_rejects_empty_manifest():
    """An empty report set must 400, never create a build row (M17 Task 2)."""
    from api import llm_knowledge_service as llm_service
    from open_notebook.exceptions import InvalidInputError

    queries = []

    async def _repo(query, params=None):
        queries.append(query)
        raise AssertionError("no database write may happen")

    with patch.object(llm_service, "repo_query", new=AsyncMock(side_effect=_repo)):
        with pytest.raises(InvalidInputError):
            await llm_service.create_build([], [], "model:x")
        with pytest.raises(InvalidInputError):
            await llm_service.create_build(["repair_report:a"], [], "model:x")
    assert not any(q.startswith("CREATE") for q in queries)


@pytest.mark.asyncio
async def test_create_build_raises_when_database_drops_manifest():
    """A silent array drop must fail loudly, before any command is submitted.

    Regression for the campact root cause: on a schemafull table SurrealDB
    2.6.5 stores ``source_report_ids``/``manifest`` as empty despite
    non-empty input, which used to produce builds that could never
    execute. ``create_build`` must refuse the dropped row instead of
    returning it.
    """
    from api import llm_knowledge_service as llm_service

    dropped_row = {
        "id": "llm_knowledge_build:dropped1",
        "source_report_ids": [],
        "manifest": [],
        "status": "queued",
        "command_id": None,
        "model": "model:x",
        "prompt_version": "m12-v1",
        "error": None,
        "warnings": [],
        "record_count": None,
        "failed_record_count": None,
        "created": "2026-09-30T00:00:00",
        "started_at": None,
        "finished_at": None,
    }
    queries = []

    async def _repo(query, params=None):
        queries.append(query)
        return [dropped_row]

    manifest = [
        {
            "report_id": "repair_report:a",
            "filename": "Tiny.xlsx",
            "analysis_key": "a3f9c2e1",
        }
    ]
    with patch.object(llm_service, "repo_query", new=AsyncMock(side_effect=_repo)):
        with pytest.raises(RuntimeError, match="not persisted with its report set"):
            await llm_service.create_build(["repair_report:a"], manifest, "model:x")
    assert sum(q.startswith("CREATE") for q in queries) == 1


@pytest.mark.asyncio
async def test_create_build_marks_dropped_row_failed_before_raising():
    """A dropped row must not linger as a queued orphan (review fix).

    The failed mark keeps build-list/Tasks truthful and keeps the row
    out of the active-build guard's way; the RuntimeError still
    prevents any command submission.
    """
    from api import llm_knowledge_service as llm_service

    dropped_row = {
        "id": "llm_knowledge_build:dropped2",
        "source_report_ids": [],
        "manifest": [],
        "status": "queued",
        "command_id": None,
        "model": "model:x",
        "prompt_version": "m12-v1",
        "error": None,
        "warnings": [],
        "record_count": None,
        "failed_record_count": None,
        "created": "2026-09-30T00:00:00",
        "started_at": None,
        "finished_at": None,
    }
    queries = []

    async def _repo(query, params=None):
        queries.append((query, params))
        return [dropped_row]

    manifest = [{"report_id": "repair_report:a", "filename": "T.xlsx",
                 "analysis_key": "k"}]
    with patch.object(llm_service, "repo_query", new=AsyncMock(side_effect=_repo)):
        with pytest.raises(RuntimeError, match="not persisted with its report set"):
            await llm_service.create_build(["repair_report:a"], manifest, "model:x")
    updates = [params for query, params in queries if query.startswith("UPDATE")]
    assert updates, "dropped row must be marked failed before raising"
    assert any(
        (params or {}).get("status") == "failed" for params in updates
    )


@pytest.mark.asyncio
async def test_create_build_returns_intact_stored_row():
    """A correctly persisted build passes through untouched (pin)."""
    from api import llm_knowledge_service as llm_service

    manifest = [
        {
            "report_id": "repair_report:a",
            "filename": "Tiny.xlsx",
            "analysis_key": "a3f9c2e1",
        }
    ]
    stored_row = {
        "id": "llm_knowledge_build:kept1",
        "source_report_ids": ["repair_report:a"],
        "manifest": manifest,
        "status": "queued",
        "command_id": None,
        "model": "model:x",
        "prompt_version": "m12-v1",
        "error": None,
        "warnings": [],
        "record_count": None,
        "failed_record_count": None,
        "created": "2026-09-30T00:00:00",
        "started_at": None,
        "finished_at": None,
    }

    async def _repo(query, params=None):
        return [stored_row]

    with patch.object(llm_service, "repo_query", new=AsyncMock(side_effect=_repo)):
        build = await llm_service.create_build(
            ["repair_report:a"], manifest, "model:x"
        )
    assert build["source_report_ids"] == ["repair_report:a"]
    assert build["manifest"] == manifest


def _live_run(**overrides):
    row = {
        "id": "repair_analysis_run:run1",
        "report_ids": ["repair_report:abc123"],
        "manifest": [],
        "status": "processing",
        "command_id": None,
        "error": None,
        "record_count": None,
        "equipment_count": None,
        "failure_mode_count": None,
        "guide_count": None,
        "created": "2026-09-26T00:00:00",
        "started_at": None,
        "finished_at": None,
    }
    row.update(overrides)
    return row


def _report_row(**overrides):
    row = {
        "id": "repair_report:abc123",
        "filename": "cmms.xlsx",
        "analysis_key": "a3f9c2e1",
        "analysis_state": "processing",
    }
    row.update(overrides)
    return row


def _run_worker(**mocks):
    """Drive the real analysis worker with mining stubbed.

    Returns (worker_commands, patches, seams) where seams holds the
    AsyncMocks for start_build, llm_command, mark_run_completed and
    mark_run_failed. LLM seams default to success; override via
    ``llm_build`` (start_build return/side_effect) and ``llm_outcome``
    (generate command return/side_effect).
    """
    from types import SimpleNamespace

    from commands import repair_report_commands as worker_commands

    llm_build = mocks.get(
        "llm_build",
        {"id": "llm_knowledge_build:b1", "status": "queued"},
    )
    llm_build_effect = mocks.get("llm_build_effect")
    llm_outcome = mocks.get(
        "llm_outcome",
        SimpleNamespace(
            success=True, build_id="llm_knowledge_build:b1", records=2,
            failed_records=0,
        ),
    )
    llm_outcome_effect = mocks.get("llm_outcome_effect")

    start_build = (
        AsyncMock(side_effect=llm_build_effect)
        if llm_build_effect is not None
        else AsyncMock(return_value=llm_build)
    )
    generate = (
        AsyncMock(side_effect=llm_outcome_effect)
        if llm_outcome_effect is not None
        else AsyncMock(return_value=llm_outcome)
    )
    mark_completed = AsyncMock()
    mark_failed = AsyncMock()
    find_finished = AsyncMock(return_value=mocks.get("find_finished"))

    fake_result = SimpleNamespace(
        records=[], equipment=[], failure_modes=[], guides=[]
    )
    fake_db = SimpleNamespace(
        parent=SimpleNamespace(mkdir=lambda **kwargs: None)
    )

    patches = (
        patch.object(
            worker_commands.reports, "_get_run_internal",
            new=AsyncMock(return_value=_live_run()),
        ),
        patch.object(
            worker_commands.reports, "get_active_run",
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            worker_commands.reports, "_get_report_internal",
            new=AsyncMock(return_value=_report_row()),
        ),
        patch.object(
            worker_commands.reports, "stored_path",
            return_value=SimpleNamespace(exists=lambda: True),
        ),
        patch.object(
            worker_commands.reports, "_set_report_state", new=AsyncMock()
        ),
        patch.object(
            worker_commands.reports, "mark_run_processing", new=AsyncMock()
        ),
        patch.object(
            worker_commands.reports, "mark_run_completed", new=mark_completed
        ),
        patch.object(
            worker_commands.reports, "mark_run_failed", new=mark_failed
        ),
        patch.object(
            worker_commands, "_build_aggregate", new=AsyncMock(return_value=[])
        ),
        patch.object(
            worker_commands, "_load_engine",
            return_value={
                "analyze_workbook": lambda *a, **k: fake_result,
                "EngineConfig": SimpleNamespace(default=lambda: None),
            },
        ),
        patch.object(
            worker_commands, "_resolve_database_path", return_value=fake_db
        ),
        patch(
            "open_notebook.database.repository.repo_query",
            new=AsyncMock(return_value=[]),
        ),
        patch("api.llm_knowledge_service.start_build", new=start_build),
        patch.object(
            worker_commands, "_run_llm_command", new=generate,
        ),
        patch(
            "api.llm_knowledge_service.find_latest_finished_build_for_reports",
            new=find_finished,
        ),
    )
    seams = {
        "start_build": start_build,
        "llm_command": generate,
        "mark_completed": mark_completed,
        "mark_failed": mark_failed,
    }
    return worker_commands, patches, seams


def _enter(patches):
    from contextlib import ExitStack

    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


@pytest.mark.asyncio
async def test_analysis_triggers_llm_build_for_same_reports():
    worker_commands, patches, seams = _run_worker()
    with _enter(patches):
        result = await worker_commands.analyze_repair_reports_command(
            worker_commands.AnalyzeRepairReportsInput(
                run_id="repair_analysis_run:run1"
            )
        )
    assert result.success is True
    seams["start_build"].assert_awaited_once_with(
        ["repair_report:abc123"], submit_command=False
    )
    seams["llm_command"].assert_awaited_once_with("llm_knowledge_build:b1")
    seams["mark_completed"].assert_awaited_once()


@pytest.mark.asyncio
async def test_start_build_can_skip_command_submission():
    """The analysis worker executes builds inline: no queue job may race it.

    ``submit_command=False`` creates the build row without submitting a
    worker command, so exactly one executor (the analysis worker) runs
    the generation — no duplicate LLM calls, no unique-index collisions.
    """
    from api import llm_knowledge_service as llm_service

    assert "submit_command" in (
        llm_service.start_build.__code__.co_varnames
    )


@pytest.mark.asyncio
async def test_analysis_reuses_active_llm_build_without_duplicate():
    from api.llm_knowledge_service import BuildInProgressError

    worker_commands, patches, seams = _run_worker(
        llm_build_effect=BuildInProgressError(
            "llm_knowledge_build:live", "already in progress"
        )
    )
    with _enter(patches):
        result = await worker_commands.analyze_repair_reports_command(
            worker_commands.AnalyzeRepairReportsInput(
                run_id="repair_analysis_run:run1"
            )
        )
    assert result.success is True
    seams["llm_command"].assert_awaited_once_with("llm_knowledge_build:live")
    seams["mark_completed"].assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_preflight_failure_does_not_fail_mining():
    from open_notebook.exceptions import ConfigurationError

    worker_commands, patches, seams = _run_worker(
        llm_build_effect=ConfigurationError("no language model configured")
    )
    with _enter(patches):
        result = await worker_commands.analyze_repair_reports_command(
            worker_commands.AnalyzeRepairReportsInput(
                run_id="repair_analysis_run:run1"
            )
        )
    assert result.success is True
    seams["llm_command"].assert_not_awaited()
    seams["mark_completed"].assert_awaited_once()
    seams["mark_failed"].assert_not_called()


@pytest.mark.asyncio
async def test_llm_transient_submit_failure_retries_analysis():
    """A transient submit error (DB conflict in create_build) propagates.

    Same contract as transient execution errors: the analysis job
    retries instead of completing with a silent LLM gap.
    """
    worker_commands, patches, seams = _run_worker(
        llm_build_effect=RuntimeError("connection reset by peer")
    )
    with _enter(patches):
        with pytest.raises(RuntimeError, match="connection reset"):
            await worker_commands.analyze_repair_reports_command(
                worker_commands.AnalyzeRepairReportsInput(
                    run_id="repair_analysis_run:run1"
                )
            )
    seams["mark_completed"].assert_not_called()
    seams["mark_failed"].assert_not_called()


@pytest.mark.asyncio
async def test_analysis_reuses_finished_llm_build():
    """A crash between LLM completion and run completion must not duplicate.

    When a terminal (completed/partial) build already covers the exact
    report set, the retry reuses it instead of submitting + executing
    a second full build.
    """
    finished = {
        "id": "llm_knowledge_build:old",
        "status": "partial",
        "record_count": 2,
        "failed_record_count": 1,
    }
    worker_commands, patches, seams = _run_worker(find_finished=finished)
    with _enter(patches):
        result = await worker_commands.analyze_repair_reports_command(
            worker_commands.AnalyzeRepairReportsInput(
                run_id="repair_analysis_run:run1"
            )
        )
    assert result.success is True
    seams["start_build"].assert_not_awaited()
    seams["llm_command"].assert_not_awaited()
    seams["mark_completed"].assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_task_title_falls_back_to_build_id():
    """A report-less build's task row stays recognizable (M17 Task 4)."""
    from api.routers import tasks as tasks_router

    cmd = {
        "id": "command:task1",
        "status": "failed",
        "args": {"build_id": "llm_knowledge_build:0tsuvd"},
        "result": None,
        "error_message": "LLM knowledge build has no report manifest.",
        "created": "2026-09-29T11:59:18",
        "updated": "2026-09-29T11:59:19",
        "started_at": "2026-09-29T11:59:19",
        "updated_at": "2026-09-29T11:59:19",
    }
    build = {
        "id": "llm_knowledge_build:0tsuvd",
        "source_report_ids": [],
    }

    async def _repo(query, params=None):
        if "generate_llm_knowledge" in query:
            return [cmd]
        if "FROM llm_knowledge_build" in query:
            return [build]
        if "FROM repair_report" in query:
            return []
        raise AssertionError(f"unexpected query: {query}")

    with patch(
        "open_notebook.database.repository.repo_query",
        new=AsyncMock(side_effect=_repo),
    ):
        items = await tasks_router._llm_knowledge_tasks(50)
    assert len(items) == 1
    assert items[0].status == "failed"
    assert items[0].error_message == "LLM knowledge build has no report manifest."
    assert items[0].title is not None
    assert "0tsuvd" in items[0].title


def _finished_build_row(**overrides):
    row = {
        "id": "llm_knowledge_build:9",
        "source_report_ids": ["repair_report:a"],
        "manifest": [],
        "status": "completed",
        "command_id": None,
        "model": "model:chat",
        "prompt_version": "m12-v1",
        "error": None,
        "warnings": [],
        "record_count": 3,
        "failed_record_count": 0,
        "created": "2026-09-28T10:00:00",
        "started_at": "2026-09-28T10:00:01",
        "finished_at": "2026-09-28T10:01:00",
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_find_latest_finished_build_prefers_completed_set():
    from api import llm_knowledge_service as llm_service

    rows = [
        _finished_build_row(status="running", command_id="command:live"),
        _finished_build_row(
            id="llm_knowledge_build:8",
            status="partial",
            record_count=1,
            failed_record_count=2,
        ),
    ]

    async def _repo(query, params=None):
        # Mirror the query contract: only finished builds are returned.
        return [
            row
            for row in rows
            if row["status"] in ("completed", "partial")
        ]

    with patch.object(
        llm_service, "repo_query", new=AsyncMock(side_effect=_repo)
    ):
        found = await llm_service.find_latest_finished_build_for_reports(
            ["repair_report:a"]
        )
    assert found is not None
    assert found["id"] == "llm_knowledge_build:8"
    assert found["status"] == "partial"


@pytest.mark.asyncio
async def test_find_latest_finished_build_ignores_failed_and_other_sets():
    from api import llm_knowledge_service as llm_service

    rows = [
        _finished_build_row(status="failed", record_count=0),
        _finished_build_row(
            id="llm_knowledge_build:7",
            source_report_ids=["repair_report:zzz"],
        ),
    ]

    async def _repo(query, params=None):
        return [
            row
            for row in rows
            if row["status"] in ("completed", "partial")
        ]

    with patch.object(
        llm_service, "repo_query", new=AsyncMock(side_effect=_repo)
    ):
        found = await llm_service.find_latest_finished_build_for_reports(
            ["repair_report:a"]
        )
    assert found is None


@pytest.mark.asyncio
async def test_inline_running_build_stays_live_past_submit_grace():
    """An inline build (no command) running 10 min must NOT go stale."""
    from datetime import datetime, timedelta, timezone

    from api import llm_knowledge_service as llm_service

    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    live = _finished_build_row(
        status="running", command_id=None, created=recent,
        started_at=recent,
    )
    updates = []

    async def _repo(query, params=None):
        if "FROM llm_knowledge_build" in query:
            return [live]
        if query.startswith("UPDATE"):
            updates.append((query, params))
            return []
        raise AssertionError(f"unexpected query: {query}")

    with patch.object(
        llm_service, "repo_query", new=AsyncMock(side_effect=_repo)
    ):
        active = await llm_service.find_active_build_for_reports(
            ["repair_report:a"]
        )
    assert active is not None
    assert active["id"] == "llm_knowledge_build:9"
    assert updates == [], "a live inline build must never be finalized"


@pytest.mark.asyncio
async def test_inline_running_build_finalized_past_lease():
    from datetime import datetime, timedelta, timezone

    from api import llm_knowledge_service as llm_service

    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    dead = _finished_build_row(
        status="running", command_id=None, created=old, started_at=old
    )
    updates = []

    async def _repo(query, params=None):
        if "FROM llm_knowledge_build" in query:
            return [dead]
        if query.startswith("UPDATE"):
            updates.append((query, params))
            return []
        raise AssertionError(f"unexpected query: {query}")

    with patch.object(
        llm_service, "repo_query", new=AsyncMock(side_effect=_repo)
    ):
        active = await llm_service.find_active_build_for_reports(
            ["repair_report:a"]
        )
    assert active is None
    assert any(
        params.get("status") == "failed" for _, params in updates
    ), "a dead inline build must be failed explicitly"


@pytest.mark.asyncio
async def test_inline_start_build_submits_no_command():
    """`submit_command=False` creates the row but submits nothing.

    Exactly one executor (the analysis worker) may run the build —
    this pins the no-queue-race invariant.
    """
    from api import llm_knowledge_service as llm_service

    async def _repo(query, params=None):
        if "FROM llm_knowledge_build" in query:
            return []
        if query.startswith("CREATE llm_knowledge_build"):
            # Healthy persistence: the stored row carries the report set.
            return [_finished_build_row(
                status="queued",
                command_id=None,
                manifest=[
                    {
                        "report_id": "repair_report:a",
                        "filename": "cmms.xlsx",
                        "analysis_key": "k1",
                    }
                ],
            )]
        raise AssertionError(f"unexpected query: {query}")

    with (
        patch.object(
            llm_service, "resolve_llm_model_id",
            new=AsyncMock(return_value="model:chat"),
        ),
        patch(
            "api.llm_generation.preflight_llm_generation", new=AsyncMock()
        ),
        patch.object(llm_service, "repo_query", new=AsyncMock(side_effect=_repo)),
        patch(
            "api.repair_report_service._get_report_internal",
            new=AsyncMock(
                return_value={
                    "id": "repair_report:a",
                    "filename": "cmms.xlsx",
                    "analysis_key": "k1",
                }
            ),
        ),
        patch(
            "api.command_service.CommandService.submit_command_job",
            new=AsyncMock(),
        ) as submit,
    ):
        build = await llm_service.start_build(
            ["repair_report:a"], submit_command=False
        )
    assert build["status"] == "queued"
    assert build["command_id"] is None
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_permanent_failure_completes_mining_explicitly():
    """A permanent LLM error never fails the mining result.

    The generate command has already marked the LLM build failed; the
    analysis run still completes and the failed build stays visible in
    Repair Guide (explicit failure, never silent success).
    """
    worker_commands, patches, seams = _run_worker(
        llm_outcome_effect=ValueError("LLM knowledge build has no manifest.")
    )
    with _enter(patches):
        result = await worker_commands.analyze_repair_reports_command(
            worker_commands.AnalyzeRepairReportsInput(
                run_id="repair_analysis_run:run1"
            )
        )
    assert result.success is True
    seams["mark_completed"].assert_awaited_once()
    seams["mark_failed"].assert_not_called()
