"""Insight worker path: the REAL graph must send Persian policy + task prompt.

Regression guard for the M20 incident (English Insights in production):
``run_transformation_command`` must route through the real
``run_transformation`` prompt assembly so the provider request contains
BOTH the shared Persian output policy (from the DB default row) AND the
transformation-specific instructions verbatim. Only the provider call and
insight persistence are stubbed; prompt construction is fully real.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_notebook.domain.notebook import Source


@pytest.mark.asyncio
async def test_worker_command_sends_persian_policy_and_full_task_prompt():
    from commands.source_commands import (
        RunTransformationInput,
        run_transformation_command,
    )

    task_prompt = (
        "# SYSTEM ROLE\nYou summarize dense content.\n\n"
        "# TASK\n- Capture core concepts\n- Keep numbers exact"
    )
    transformation = MagicMock(
        title="Simple Summary", prompt=task_prompt, model_id=None
    )
    source = Source(id="source:test123", title="Test Source", asset=None)
    source.full_text = "P-101 delivers 120 L/min at 4.2 bar."

    seen_payload = {}

    fake_response = MagicMock()
    fake_response.content = "خروجی آزمایشی"  # stubbed provider text
    fake_chain = AsyncMock()
    fake_chain.ainvoke = AsyncMock(return_value=fake_response)

    async def _fake_provision(payload_str, model_id, purpose, max_tokens=None):
        seen_payload["system"] = str(payload_str)
        return fake_chain

    with (
        patch(
            "commands.source_commands.Source.get",
            new=AsyncMock(return_value=source),
        ),
        patch(
            "commands.source_commands.Transformation.get",
            new=AsyncMock(return_value=transformation),
        ),
        patch(
            "open_notebook.graphs.transformation.DefaultPrompts",
        ) as mock_defaults_cls,
        patch(
            "open_notebook.graphs.transformation.provision_langchain_model",
            new=_fake_provision,
        ),
        patch.object(
            Source, "add_insight", new=AsyncMock(return_value="command:ok")
        ),
    ):
        mock_defaults_cls.get_instance = AsyncMock(
            return_value=MagicMock(
                transformation_instructions=(
                    "# OUTPUT LANGUAGE AND STYLE\n"
                    "- Write the final output in natural Persian (Farsi)."
                )
            )
        )
        result = await run_transformation_command(
            RunTransformationInput(
                source_id="source:test123",
                transformation_id="transformation:456",
            )
        )

    assert result.success is True
    # The true provider request is the message list passed to ainvoke
    # (provision only receives its str() form for budgeting).
    sent = fake_chain.ainvoke.await_args.args[0]
    assert len(sent) == 2
    system = sent[0].content
    human = sent[1].content
    assert human == "P-101 delivers 120 L/min at 4.2 bar."
    # Test 1: Persian policy present in the actual provider request.
    assert "Persian (Farsi)" in system
    # Test 2: transformation-specific instructions fully preserved.
    assert task_prompt in system
    assert "- Capture core concepts" in system
    assert "- Keep numbers exact" in system
    # Test 3: composition order — policy first, task second.
    assert system.index("Persian (Farsi)") < system.index("# SYSTEM ROLE")
