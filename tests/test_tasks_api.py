"""Tests for GET /api/tasks (embedding job visibility).

The endpoint exposes the persisted surreal-commands `command` records for
embed_source jobs plus the real per-batch progress the worker writes back.
Progress must be derived from worker state only: percentage is
processed/total*100 when a total is known, otherwise null (indeterminate).

DELETE /api/tasks/{job_id} removes only the command row (never files,
reports, runs, or the knowledge database) and only for terminal jobs.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _cmd(**overrides):
    record = {
        "id": "command:abc",
        "status": "running",
        "args": {"source_id": "source:1"},
        "result": None,
        "error_message": None,
        "created": None,
        "updated": None,
        "progress_processed": None,
        "progress_total": None,
        "started_at": None,
        "updated_at": None,
    }
    record.update(overrides)
    return record


def _repo_factory(commands):
    async def _repo(query, params=None):
        if "analyze_repair_reports" in query:
            return []
        if "FROM repair_analysis_run" in query:
            return []
        if "FROM repair_report" in query:
            return []
        if "FROM command" in query:
            return commands
        if "FROM source" in query:
            return [{"id": "source:1", "title": "CMMS Report"}]
        raise AssertionError(f"unexpected query: {query}")

    return _repo


@pytest.mark.asyncio
@patch("open_notebook.database.repository.repo_query", new_callable=AsyncMock)
async def test_tasks_report_real_progress(mock_repo, client):
    mock_repo.side_effect = _repo_factory(
        [
            _cmd(
                id="command:run",
                status="running",
                progress_processed=12,
                progress_total=351,
                started_at="2026-09-22T10:00:00",
            )
        ]
    )

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    (task,) = resp.json()
    assert task["job_id"] == "command:run"
    assert task["source_id"] == "source:1"
    assert task["source_title"] == "CMMS Report"
    assert task["status"] == "running"
    assert task["processed_chunks"] == 12
    assert task["total_chunks"] == 351
    assert task["percentage"] == pytest.approx(3.4, abs=0.05)
    assert task["started_at"] == "2026-09-22T10:00:00"


@pytest.mark.asyncio
@patch("open_notebook.database.repository.repo_query", new_callable=AsyncMock)
async def test_tasks_indeterminate_before_total_known(mock_repo, client):
    mock_repo.side_effect = _repo_factory([_cmd(id="command:new", status="new")])

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    (task,) = resp.json()
    assert task["status"] == "new"
    assert task["processed_chunks"] is None
    assert task["total_chunks"] is None
    assert task["percentage"] is None


@pytest.mark.asyncio
@patch("open_notebook.database.repository.repo_query", new_callable=AsyncMock)
async def test_tasks_completed_and_failed(mock_repo, client):
    mock_repo.side_effect = _repo_factory(
        [
            _cmd(
                id="command:done",
                status="completed",
                result={"success": True, "source_id": "s", "chunks_created": 7},
                progress_processed=7,
                progress_total=7,
            ),
            _cmd(
                id="command:old",
                status="completed",
                result={"success": True, "source_id": "s", "chunks_created": 3},
            ),
            _cmd(
                id="command:bad",
                status="failed",
                args={"source_id": "source:gone"},
                error_message="boom",
            ),
        ]
    )

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    by_id = {t["job_id"]: t for t in resp.json()}

    assert by_id["command:done"]["percentage"] == 100.0
    assert by_id["command:done"]["chunks_created"] == 7
    # Jobs finished before progress tracking still read as complete.
    assert by_id["command:old"]["percentage"] == 100.0
    # Deleted sources keep their ID with a null title.
    failed = by_id["command:bad"]
    assert failed["status"] == "failed"
    assert failed["source_title"] is None
    assert failed["error_message"] == "boom"


# --- DELETE /api/tasks/{job_id} (M11C-6R Part D) -------------------------------


def _delete_repo_factory(command_row):
    async def _repo(query, params=None):
        if query.startswith("SELECT * FROM command"):
            return [command_row] if command_row is not None else []
        raise AssertionError(f"unexpected query: {query}")

    return _repo


@pytest.mark.asyncio
@patch("open_notebook.database.repository.repo_query", new_callable=AsyncMock)
@patch("open_notebook.database.repository.repo_delete", new_callable=AsyncMock)
async def test_delete_terminal_task_removes_command_only(
    mock_delete, mock_repo, client
):
    """Completed jobs delete the command row; nothing else is touched."""
    mock_repo.side_effect = _delete_repo_factory(_cmd(id="command:done", status="completed"))
    resp = client.delete("/api/tasks/command:done")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"job_id": "command:done", "deleted": True}
    assert mock_delete.await_count == 1


@pytest.mark.asyncio
@patch("open_notebook.database.repository.repo_query", new_callable=AsyncMock)
@patch("open_notebook.database.repository.repo_delete", new_callable=AsyncMock)
async def test_delete_active_task_conflicts(mock_delete, mock_repo, client):
    """Running jobs cannot be deleted (409); the row is preserved."""
    mock_repo.side_effect = _delete_repo_factory(_cmd(id="command:run", status="running"))
    resp = client.delete("/api/tasks/command:run")
    assert resp.status_code == 409
    assert mock_delete.await_count == 0


@pytest.mark.asyncio
@patch("open_notebook.database.repository.repo_query", new_callable=AsyncMock)
@patch("open_notebook.database.repository.repo_delete", new_callable=AsyncMock)
async def test_delete_unknown_task_not_found(mock_delete, mock_repo, client):
    mock_repo.side_effect = _delete_repo_factory(None)
    resp = client.delete("/api/tasks/command:missing")
    assert resp.status_code == 404
    assert mock_delete.await_count == 0


# --- DELETE /api/tasks/history (Clear History) --------------------------------


def _history_repo_factory(commands):
    async def _repo(query, params=None):
        if "FROM command" in query:
            return commands
        raise AssertionError(f"unexpected query: {query}")

    return _repo


@pytest.mark.asyncio
@patch("open_notebook.database.repository.repo_query", new_callable=AsyncMock)
@patch("open_notebook.database.repository.repo_delete", new_callable=AsyncMock)
async def test_clear_history_removes_only_terminal(mock_delete, mock_repo, client):
    mock_repo.side_effect = _history_repo_factory(
        [
            _cmd(id="command:done", status="completed"),
            _cmd(id="command:bad", status="failed"),
            _cmd(id="command:gone", status="canceled"),
            _cmd(id="command:run", status="running"),
            _cmd(id="command:new", status="new"),
        ]
    )
    resp = client.delete("/api/tasks/history")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 3}
    assert mock_delete.await_count == 3


@pytest.mark.asyncio
@patch("open_notebook.database.repository.repo_query", new_callable=AsyncMock)
@patch("open_notebook.database.repository.repo_delete", new_callable=AsyncMock)
async def test_clear_history_empty_is_zero(mock_delete, mock_repo, client):
    """Empty history (and repeated clears) delete nothing, still 200."""
    mock_repo.side_effect = _history_repo_factory([])
    assert client.delete("/api/tasks/history").json() == {"deleted": 0}
    assert client.delete("/api/tasks/history").json() == {"deleted": 0}
    assert mock_delete.await_count == 0


# --- task ordering: most recently updated first ---------------------------------


@pytest.mark.asyncio
@patch("open_notebook.database.repository.repo_query", new_callable=AsyncMock)
async def test_tasks_sorted_by_updated_desc(mock_repo, client):
    """Server-side ordering is updated_at DESC with deterministic ties."""
    old = _cmd(id="command:old", status="completed", updated_at="2026-09-20T10:00:00")
    new = _cmd(id="command:new", status="failed", updated_at="2026-09-28T10:00:00")
    tie_a = _cmd(id="command:aaa", status="completed", updated_at="2026-09-25T10:00:00")
    tie_b = _cmd(id="command:bbb", status="completed", updated_at="2026-09-25T10:00:00")

    async def _repo(query, params=None):
        if "analyze_repair_reports" in query:
            return []
        if "FROM repair_analysis_run" in query:
            return []
        if "FROM repair_report" in query:
            return []
        if "FROM command" in query:
            return [old, tie_a, new, tie_b]
        if "FROM source" in query:
            return []
        raise AssertionError(f"unexpected query: {query}")

    mock_repo.side_effect = _repo
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    ids = [task["job_id"] for task in resp.json()]
    assert ids == ["command:new", "command:bbb", "command:aaa", "command:old"]
