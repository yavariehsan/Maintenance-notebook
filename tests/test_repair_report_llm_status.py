"""Tests for the repair-report LLM analysis status column.

The repair table's `وضعیت تحلیل متن کاوری` column must show the real
per-report language-model build state (never fabricated): the latest
LLM build covering the report, or `not_started` when no build exists.
"""

from unittest.mock import AsyncMock, patch

import pytest


def _build(status, report_ids):
    return {
        "id": "llm_knowledge_build:test",
        "source_report_ids": list(report_ids),
        "status": status,
    }


class TestLLMStatusAnnotation:
    pytestmark = pytest.mark.asyncio

    async def test_no_build_means_not_started(self):
        from api import repair_report_service as reports

        with (
            patch(
                "api.repair_report_service.repo_query",
                new=AsyncMock(return_value=[
                    {"id": "repair_report:one", "filename": "a.xlsx"},
                ]),
            ),
            patch(
                "api.llm_knowledge_service.find_latest_build_covering_report",
                new=AsyncMock(return_value=None),
            ),
        ):
            rows = await reports.list_reports()
        assert len(rows) == 1
        assert rows[0]["llm_status"] == "not_started"

    async def test_covering_build_status_passes_through(self):
        from api import repair_report_service as reports

        builds = {
            "repair_report:one": _build("running", ["repair_report:one"]),
            "repair_report:two": _build("completed", ["repair_report:two"]),
        }

        async def _fake_cover(report_id):
            return builds.get(str(report_id))

        with (
            patch(
                "api.repair_report_service.repo_query",
                new=AsyncMock(return_value=[
                    {"id": "repair_report:one", "filename": "a.xlsx"},
                    {"id": "repair_report:two", "filename": "b.xlsx"},
                ]),
            ),
            patch(
                "api.llm_knowledge_service.find_latest_build_covering_report",
                new=_fake_cover,
            ),
        ):
            rows = await reports.list_reports()
        by_id = {row["id"]: row for row in rows}
        assert by_id["repair_report:one"]["llm_status"] == "running"
        assert by_id["repair_report:two"]["llm_status"] == "completed"

    async def test_report_row_defaults_llm_status(self):
        from api.repair_report_service import _report_row

        row = _report_row({"id": "repair_report:x"})
        assert row["llm_status"] == "not_started"
