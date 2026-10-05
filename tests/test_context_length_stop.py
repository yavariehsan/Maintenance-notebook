"""Context-length failures stop custom workers immediately (P1.2).

A context-length failure is deterministic (same oversized payload on every
attempt), so retrying it is a ~25-minute no-op. The two customized workers
must treat ContextLengthExceededError as terminal with honest states, exactly
like ValueError/ConfigurationError, while genuinely transient errors keep
propagating for retry. The framework-level `stop_on` lists are extended in
the same change (verified by config; behavior below is the proof).
"""

from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.exceptions import (
    ConfigurationError,
    ContextLengthExceededError,
)


class TestRepairLLMPhaseContextLength:
    pytestmark = pytest.mark.asyncio

    async def _run_phase(self, llm_command_side_effect):
        from commands import repair_report_commands as rrc

        with (
            patch(
                "api.llm_knowledge_service.find_latest_finished_build_for_reports",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "api.llm_knowledge_service.start_build",
                new=AsyncMock(return_value={"id": "llm_knowledge_build:t"}),
            ),
            patch.object(
                rrc, "_run_llm_command", new=AsyncMock(
                    side_effect=llm_command_side_effect
                ),
            ),
        ):
            return await rrc._run_llm_phase(["repair_report:t"])

    async def test_context_length_is_terminal_with_failed_status(self):
        outcome = await self._run_phase(
            ContextLengthExceededError("context length exceeded")
        )
        assert outcome is not None
        assert outcome["status"] == "failed"
        assert outcome["records"] == 0

    async def test_value_error_stays_terminal(self):
        outcome = await self._run_phase(ValueError("permanent"))
        assert outcome is not None
        assert outcome["status"] == "failed"

    async def test_transient_error_still_propagates_for_retry(self):
        with pytest.raises(RuntimeError):
            await self._run_phase(RuntimeError("db conflict"))


class TestContextLengthExceptionClassification:
    def test_not_covered_by_existing_stop_on_types(self):
        """Documents why explicit listing is required: neither existing
        stop_on member catches it (no subclass shortcut available)."""
        assert not issubclass(ContextLengthExceededError, ValueError)
        assert not issubclass(ContextLengthExceededError, ConfigurationError)

    def test_stop_on_lists_include_context_length(self):
        """Pin the framework-level contract for both customized workers:
        every `stop_on` list in each file must name the exception."""
        import ast
        from pathlib import Path

        for filename in (
            "commands/llm_knowledge_commands.py",
            "commands/repair_report_commands.py",
        ):
            tree = ast.parse(
                (Path(__file__).parent.parent / filename).read_text(
                    encoding="utf-8"
                )
            )
            stop_on_values = [
                ast.unparse(value)
                for node in ast.walk(tree)
                if isinstance(node, ast.Dict)
                for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and key.value == "stop_on"
            ]
            assert stop_on_values, filename
            assert all(
                "ContextLengthExceededError" in value
                for value in stop_on_values
            ), filename
