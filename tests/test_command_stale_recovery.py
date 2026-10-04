"""Stale `running` command recovery (startup + Tasks read path).

A command stuck in `running` with no alive worker must eventually flip to
`failed` — never stay `running` forever, and a genuinely active command
(fresh heartbeat) must never be touched. `new` jobs are always left alone
(restarted workers resume `new`).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cmd(cmd_id, status, **fields):
    row = {"id": cmd_id, "status": status}
    row.update(fields)
    return row


def _repo_for(rows):
    """repo_query side effect: SELECT returns rows; UPDATE records calls."""
    calls = []

    async def _fake(query, params=None):
        calls.append((query, params))
        if query.lstrip().upper().startswith("SELECT"):
            return list(rows)
        return []

    _fake.calls = calls
    return _fake


@pytest.mark.asyncio
async def test_stale_running_command_is_failed():
    from api.command_service import CommandService

    stale = _now() - timedelta(seconds=7200)
    rows = [_cmd("command:1", "running", updated_at=_iso(stale))]
    fake = _repo_for(rows)
    with patch(
        "open_notebook.database.repository.repo_query", new=fake
    ):
        result = await CommandService.reconcile_stale_commands()
    assert result["checked"] == 1
    assert result["reconciled"] == 1
    assert "command:1" in result["reconciled_ids"]
    updates = [c for c in fake.calls if c[0].lstrip().upper().startswith("UPDATE")]
    assert len(updates) == 1
    assert "failed" in str(updates[0][1])


@pytest.mark.asyncio
async def test_fresh_running_command_is_untouched():
    from api.command_service import CommandService

    rows = [_cmd("command:1", "running", updated_at=_iso(_now()))]
    fake = _repo_for(rows)
    with patch(
        "open_notebook.database.repository.repo_query", new=fake
    ):
        result = await CommandService.reconcile_stale_commands()
    assert result["checked"] == 1
    assert result["reconciled"] == 0
    assert not [
        c for c in fake.calls if c[0].lstrip().upper().startswith("UPDATE")
    ]


@pytest.mark.asyncio
async def test_running_without_any_timestamp_is_untouched():
    """Conservative: no liveness evidence either way → leave it running."""
    from api.command_service import CommandService

    rows = [_cmd("command:1", "running")]
    fake = _repo_for(rows)
    with patch(
        "open_notebook.database.repository.repo_query", new=fake
    ):
        result = await CommandService.reconcile_stale_commands()
    assert result["reconciled"] == 0


@pytest.mark.asyncio
async def test_new_commands_are_never_reconciled():
    from api.command_service import CommandService

    old = _now() - timedelta(days=2)
    rows = [_cmd("command:1", "new", created=_iso(old))]
    fake = _repo_for(rows)
    with patch(
        "open_notebook.database.repository.repo_query", new=fake
    ):
        result = await CommandService.reconcile_stale_commands()
    # `new` rows are not even selected for reconciliation.
    selects = [c for c in fake.calls if c[0].lstrip().upper().startswith("SELECT")]
    assert selects
    assert "new" not in selects[0][0]
    assert result["reconciled"] == 0


@pytest.mark.asyncio
async def test_mixed_batch_only_stale_running_flips():
    from api.command_service import CommandService

    stale = _now() - timedelta(seconds=7200)
    rows = [
        _cmd("command:1", "running", updated_at=_iso(stale)),
        _cmd("command:2", "running", updated_at=_iso(_now())),
        _cmd("command:3", "completed", updated_at=_iso(stale)),
    ]
    fake = _repo_for(rows)
    with patch(
        "open_notebook.database.repository.repo_query", new=fake
    ):
        result = await CommandService.reconcile_stale_commands()
    assert result["checked"] == 3
    assert result["reconciled"] == 1
    assert result["reconciled_ids"] == ["command:1"]


@pytest.mark.asyncio
async def test_analysis_heartbeat_counts_as_liveness():
    """Repair workers heartbeat via analysis_heartbeat; respect it."""
    from api.command_service import CommandService

    rows = [
        _cmd(
            "command:1",
            "running",
            updated_at=_iso(_now() - timedelta(seconds=7200)),
            analysis_heartbeat=_iso(_now()),
        )
    ]
    fake = _repo_for(rows)
    with patch(
        "open_notebook.database.repository.repo_query", new=fake
    ):
        result = await CommandService.reconcile_stale_commands()
    assert result["reconciled"] == 0


@pytest.mark.asyncio
async def test_db_errors_never_raise():
    """Startup safety: reconciliation must not take down API boot."""
    from api.command_service import CommandService

    async def _boom(query, params=None):
        raise RuntimeError("db unavailable")

    with patch("open_notebook.database.repository.repo_query", new=_boom):
        result = await CommandService.reconcile_stale_commands()
    assert result["checked"] == 0
    assert result["reconciled"] == 0
    assert result["errors"]


@pytest.mark.asyncio
async def test_tasks_read_path_reconciles_before_listing():
    """GET /tasks heals lease-expired orphans so the UI shows true state."""
    from api.routers import tasks as tasks_router

    async def _empty_repo(query, params=None):
        return []

    with (
        patch(
            "api.command_service.CommandService.reconcile_stale_commands",
            new=AsyncMock(
                return_value={"checked": 0, "reconciled": 0,
                              "reconciled_ids": [], "errors": []}
            ),
        ) as mock_reconcile,
        patch(
            "open_notebook.database.repository.repo_query", new=_empty_repo
        ),
    ):
        result = await tasks_router.list_tasks(limit=10)
    mock_reconcile.assert_awaited_once()
    assert result == []


@pytest.mark.asyncio
async def test_startup_quiescence_flips_timestamp_less_orphans():
    """Restart with dead workers: bare `running` rows are orphans (failed)."""
    from api.command_service import CommandService

    rows = [
        _cmd("command:1", "running"),
        _cmd("command:2", "running", name="process_source"),
    ]
    fake = _repo_for(rows)
    with patch(
        "open_notebook.database.repository.repo_query", new=fake
    ):
        result = await CommandService.reconcile_stale_commands(allow_bare=True)
    assert result["checked"] == 2
    assert result["reconciled"] == 2
    assert sorted(result["reconciled_ids"]) == ["command:1", "command:2"]


@pytest.mark.asyncio
async def test_startup_fresh_activity_vetoes_bare_flip():
    """A live worker (fresh heartbeat anywhere) protects bare rows."""
    from api.command_service import CommandService

    rows = [
        _cmd("command:1", "running"),
        _cmd("command:2", "running", updated_at=_iso(_now())),
    ]
    fake = _repo_for(rows)
    with patch(
        "open_notebook.database.repository.repo_query", new=fake
    ):
        result = await CommandService.reconcile_stale_commands(allow_bare=True)
    assert result["reconciled"] == 0
    assert not [
        c for c in fake.calls if c[0].lstrip().upper().startswith("UPDATE")
    ]


@pytest.mark.asyncio
async def test_read_path_leaves_timestamp_less_rows_alone():
    """Mid-session a live worker may own a bare row — never touch on read."""
    from api.command_service import CommandService

    rows = [_cmd("command:1", "running")]
    fake = _repo_for(rows)
    with patch(
        "open_notebook.database.repository.repo_query", new=fake
    ):
        result = await CommandService.reconcile_stale_commands(
            allow_bare=False
        )
    assert result["checked"] == 1
    assert result["reconciled"] == 0


@pytest.mark.asyncio
async def test_lifespan_startup_invokes_reconciliation():
    """Wiring: API boot runs migrations then startup-mode reconciliation."""
    from api import main as api_main

    with (
        patch(
            "api.main._run_database_migrations", new=AsyncMock()
        ),
        patch(
            "api.command_service.CommandService.reconcile_stale_commands",
            new=AsyncMock(
                return_value={"checked": 0, "reconciled": 0,
                              "reconciled_ids": [], "errors": []}
            ),
        ) as mock_reconcile,
    ):
        async with api_main.lifespan(api_main.app):
            pass
    mock_reconcile.assert_awaited_once()
    kwargs = mock_reconcile.await_args.kwargs
    assert kwargs.get("allow_bare") is True
