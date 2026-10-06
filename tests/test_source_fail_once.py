"""Fail-once semantics for deleted sources/transformations (P1.1).

A genuinely missing record (NotFoundError from the lookup, per the P0.5
distinction) is a permanent failure: the command must finish terminally on
the first attempt, never burn the transient retry budget. Infrastructure
failures keep propagating for retry.
"""

from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.exceptions import DatabaseOperationError, NotFoundError


def _process_input():
    from commands.source_commands import SourceProcessingInput

    return SourceProcessingInput(
        source_id="source:gone",
        content_state={},
        notebook_ids=[],
        transformations=[],
        embed=False,
    )


def _run_input():
    from commands.source_commands import RunTransformationInput

    return RunTransformationInput(
        source_id="source:gone", transformation_id="transformation:gone"
    )


class TestProcessSourceFailOnce:
    pytestmark = pytest.mark.asyncio

    async def test_deleted_source_fails_fast_as_value_error(self):
        from commands import source_commands as sc

        with patch.object(
            sc.Source, "get", new=AsyncMock(side_effect=NotFoundError("gone"))
        ) as mock_get:
            with pytest.raises(ValueError, match="[Dd]eleted|not found|gone"):
                await sc.process_source_command(_process_input())
        mock_get.assert_awaited_once()

    async def test_database_outage_stays_retryable(self):
        from commands import source_commands as sc

        with patch.object(
            sc.Source,
            "get",
            new=AsyncMock(side_effect=DatabaseOperationError("down")),
        ):
            with pytest.raises(DatabaseOperationError):
                await sc.process_source_command(_process_input())


class TestRunTransformationFailOnce:
    pytestmark = pytest.mark.asyncio

    async def test_deleted_source_returns_terminal_failure(self):
        from commands import source_commands as sc

        with (
            patch.object(
                sc.Source, "get", new=AsyncMock(side_effect=NotFoundError("gone"))
            ),
            patch.object(
                sc, "transform_graph",
            ) as mock_graph,
        ):
            mock_graph.ainvoke = AsyncMock()
            result = await sc.run_transformation_command(_run_input())
        assert result.success is False
        assert result.error_message
        mock_graph.ainvoke.assert_not_awaited()

    async def test_deleted_transformation_returns_terminal_failure(self):
        from commands import source_commands as sc
        from open_notebook.domain.notebook import Source

        source = Source(id="source:x", title="X", asset=None)
        with (
            patch.object(
                sc.Source, "get", new=AsyncMock(return_value=source)
            ),
            patch.object(
                sc.Transformation,
                "get",
                new=AsyncMock(side_effect=NotFoundError("gone")),
            ),
            patch.object(
                sc, "transform_graph",
            ) as mock_graph,
        ):
            mock_graph.ainvoke = AsyncMock()
            result = await sc.run_transformation_command(_run_input())
        assert result.success is False
        assert result.error_message
        mock_graph.ainvoke.assert_not_awaited()
