"""Runtime proof that the Persian default prompt reaches the LLM request.

Migration 31 put the Persian policy in ``open_notebook:default_prompts``,
but ``run_transformation`` never reads that row (it builds
``DefaultPrompts(transformation_instructions=None)``), so the policy never
appears in the final LLM request. These tests pin the runtime contract:

* the default instructions are loaded from the DB singleton;
* they are prepended BEFORE the transformation-specific prompt;
* the transformation-specific prompt survives verbatim (no semantic loss);
* a missing/failed default degrades to task-only instead of crashing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_notebook.domain.notebook import Source


def _make_source():
    source = Source(id="source:test123", title="Test Source", asset=None)
    source.full_text = "full text of the source"
    return source


async def _invoke(default_text=None, task_prompt="Summarize this INPUT", get_instance=None):
    """Run run_transformation; return (result, captured render data)."""
    from open_notebook.graphs.transformation import run_transformation

    source = _make_source()
    transformation = MagicMock(title="Summary", prompt=task_prompt)
    fake_response = MagicMock()
    fake_response.content = "the transformation output"
    fake_chain = AsyncMock()
    fake_chain.ainvoke = AsyncMock(return_value=fake_response)

    captured = {}
    fake_prompter = MagicMock()
    fake_prompter.render.side_effect = (
        lambda data: captured.update(data) or "rendered prompt"
    )

    if get_instance is None:
        get_instance = AsyncMock(
            return_value=MagicMock(transformation_instructions=default_text)
        )

    with (
        patch(
            "open_notebook.graphs.transformation.DefaultPrompts",
        ) as mock_defaults_cls,
        patch(
            "open_notebook.graphs.transformation.Prompter",
            return_value=fake_prompter,
        ),
        patch(
            "open_notebook.graphs.transformation.provision_langchain_model",
            new=AsyncMock(return_value=fake_chain),
        ),
        patch.object(
            Source, "add_insight", new=AsyncMock(return_value="command:ok")
        ),
    ):
        mock_defaults_cls.get_instance = get_instance
        result = await run_transformation(
            {
                "source": source,
                "input_text": None,
                "transformation": transformation,
            },
            config={"configurable": {}},
        )
    return result, captured, mock_defaults_cls


@pytest.mark.asyncio
async def test_default_instructions_prepended_before_task_prompt():
    default = "# OUTPUT LANGUAGE AND STYLE\n- Write in Persian (Farsi)."
    _result, captured, _cls = await _invoke(default_text=default)
    assert captured["instructions"] == f"{default}\n\nSummarize this INPUT"


@pytest.mark.asyncio
async def test_transformation_task_prompt_survives_verbatim():
    task = (
        "# IDENTITY\nYou summarize.\n\n# OUTPUT INSTRUCTIONS\n"
        "- one bullet\n- two bullets"
    )
    _result, captured, _cls = await _invoke(
        default_text="PERSIAN POLICY", task_prompt=task
    )
    assert task in captured["instructions"]
    assert "# OUTPUT INSTRUCTIONS" in captured["instructions"]


@pytest.mark.asyncio
async def test_missing_default_uses_task_prompt_only():
    _result, captured, _cls = await _invoke(default_text=None)
    assert captured["instructions"] == "Summarize this INPUT"


@pytest.mark.asyncio
async def test_db_error_falls_back_to_task_prompt():
    result, captured, _cls = await _invoke(
        get_instance=AsyncMock(side_effect=RuntimeError("db down"))
    )
    assert result == {"output": "the transformation output"}
    assert captured["instructions"] == "Summarize this INPUT"


@pytest.mark.asyncio
async def test_default_loaded_via_get_instance_not_constructor():
    """The graph must read the DB row, never construct with a None override."""
    _result, _captured, mock_defaults_cls = await _invoke(default_text="PERSIAN")
    mock_defaults_cls.get_instance.assert_awaited()
    for call in mock_defaults_cls.call_args_list:
        kwargs = call.kwargs
        assert "transformation_instructions" not in kwargs
