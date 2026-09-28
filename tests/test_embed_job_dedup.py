"""Regression tests: no duplicate embed jobs while one is genuinely active.

Live incident (2026-09-28): ``Machine Bed.pdf``
(``source:5vhtl3b81nqv240ykqwg``) collected three ``embed_source``
commands (started 18:07:40 / 18:08:22 / 18:09:14 UTC, all stuck at
progress 0/17 with ``updated_at == started_at``) because every
``POST /embed`` unconditionally submitted a new job: the first job made
no visible progress (worker gone, no heartbeat mechanism for embed
jobs), the source stayed un-embedded, and each re-click submitted
again. Retries inside the worker reuse the same command ID, so the
distinct IDs prove repeated submission, not worker retry.

``Source.vectorize()`` now deduplicates: a fresh active job's command
ID is returned instead of submitting; an abandoned job (no worker
write within ``EMBED_STALE_SECONDS``) is marked failed with an explicit
reason before exactly one replacement is submitted. Completed jobs
never block resubmission.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from open_notebook.domain import notebook as notebook_module
from open_notebook.domain.notebook import Source


def _cmd(cmd_id, status, updated_at=None, started_at=None):
    return {
        "id": cmd_id,
        "status": status,
        "args": {"source_id": "source:mb1"},
        "result": None,
        "error_message": None,
        "created": None,
        "updated": None,
        "progress_processed": 0 if status == "running" else None,
        "progress_total": 17 if status == "running" else None,
        "started_at": started_at,
        "updated_at": updated_at,
    }


def _iso_now_minus(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _source():
    source = Source(title="Machine Bed.pdf", full_text="Bed is the guiding part. " * 500)
    object.__setattr__(source, "id", "source:mb1")
    return source


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app, raise_server_exceptions=False)


class TestVectorizeDedup:
    @pytest.mark.asyncio
    async def test_active_fresh_job_returns_existing_id(self):
        """A second submission while the first is live returns its ID."""
        live = _cmd("command:live", "running", updated_at=_iso_now_minus(2))
        with (
            patch.object(
                notebook_module, "repo_query", new=AsyncMock(return_value=[live])
            ),
            patch.object(notebook_module, "submit_command") as mock_submit,
        ):
            command_id = await _source().vectorize()
        assert command_id == "command:live"
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_job_is_always_live(self):
        """`new` jobs resume on worker restart: never supersede them."""
        pending = _cmd("command:pending", "new")
        with (
            patch.object(
                notebook_module, "repo_query", new=AsyncMock(return_value=[pending])
            ),
            patch.object(notebook_module, "submit_command") as mock_submit,
        ):
            command_id = await _source().vectorize()
        assert command_id == "command:pending"
        mock_submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_job_heals_then_submits_once(self):
        """An abandoned job is failed explicitly; exactly one replaces it."""
        stale = _cmd(
            "command:stale",
            "running",
            started_at=_iso_now_minus(90),
            updated_at=_iso_now_minus(90),
        )
        updates = []

        async def _repo(query, params=None):
            if "FROM command" in query:
                return [stale]
            if query.startswith("UPDATE"):
                updates.append((query, params))
                return []
            raise AssertionError(f"unexpected query: {query}")

        with (
            patch.object(notebook_module, "repo_query", new=AsyncMock(side_effect=_repo)),
            patch.object(
                notebook_module, "submit_command", return_value="command:fresh"
            ) as mock_submit,
        ):
            command_id = await _source().vectorize()
        assert command_id == "command:fresh"
        mock_submit.assert_called_once()
        failed = [
            params
            for query, params in updates
            if params.get("status") == "failed"
        ]
        assert len(failed) == 1
        assert "Stale embed job" in failed[0].get("error", "")

    @pytest.mark.asyncio
    async def test_completed_job_does_not_block_resubmission(self):
        with (
            patch.object(notebook_module, "repo_query", new=AsyncMock(return_value=[])),
            patch.object(
                notebook_module, "submit_command", return_value="command:new1"
            ) as mock_submit,
        ):
            command_id = await _source().vectorize()
        assert command_id == "command:new1"
        mock_submit.assert_called_once()


class TestEmbedEndpointDedup:
    """POST /api/embed surfaces the deduplicated command ID (200)."""

    def test_second_submit_returns_live_command(self, client):
        live = _cmd("command:live", "running", updated_at=_iso_now_minus(1))
        with (
            patch("api.routers.embedding.Source.get", new=AsyncMock(return_value=_source())),
            patch.object(
                notebook_module, "repo_query", new=AsyncMock(return_value=[live])
            ),
            patch.object(notebook_module, "submit_command") as mock_submit,
            patch(
                "open_notebook.ai.models.model_manager.get_embedding_model",
                new=AsyncMock(return_value=object()),
            ),
        ):
            response = client.post(
                "/api/embed",
                json={"item_id": "source:mb1", "item_type": "source", "async_processing": False},
            )
        assert response.status_code == 200
        assert response.json()["command_id"] == "command:live"
        mock_submit.assert_not_called()
