"""Focused empty-transformation-source tests (P0.4).

Invariant: a transformation must NOT call the LLM when the resolved content
(explicit `input_text` or `source.full_text`) is empty or whitespace-only.
Such input is rejected with InvalidInputError before model provisioning, so
no LLM call occurs and no insight is persisted. Valid input (either channel)
keeps working unchanged.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_notebook.domain.notebook import Source
from open_notebook.exceptions import InvalidInputError


def make_source(**overrides):
    defaults = dict(id="source:test123", title="Test Source", asset=None)
    defaults.update(overrides)
    return Source(**defaults)


def make_state(source, input_text=None):
    return {
        "source": source,
        "input_text": input_text,
        "transformation": MagicMock(title="Summary", prompt="Summarize this"),
    }


def _mocks(mock_add_insight=None):
    return (
        patch(
            "open_notebook.graphs.transformation.provision_langchain_model",
            new=AsyncMock(),
        ),
        patch.object(
            Source,
            "add_insight",
            new=AsyncMock(
                return_value="command:ok" if mock_add_insight is None else mock_add_insight
            ),
        ),
    )


class TestEmptyTransformationSourceRejected:
    pytestmark = pytest.mark.asyncio

    @pytest.mark.parametrize("empty_text", ["", "   ", "\n\t  \n", " \r\n "])
    async def test_empty_and_whitespace_source_rejected_before_llm(
        self, empty_text: str
    ):
        from open_notebook.graphs.transformation import run_transformation

        source = make_source()
        source.full_text = empty_text
        provision_mock, insight_mock = _mocks()

        with provision_mock as mock_provision, insight_mock as mock_add_insight:
            with pytest.raises(InvalidInputError):
                await run_transformation(
                    make_state(source), config={"configurable": {}}
                )

        mock_provision.assert_not_awaited()
        mock_add_insight.assert_not_awaited()

    async def test_whitespace_explicit_input_rejected(self):
        from open_notebook.graphs.transformation import run_transformation

        source = make_source()
        source.full_text = "real source text"
        provision_mock, insight_mock = _mocks()

        with provision_mock as mock_provision, insight_mock as mock_add_insight:
            with pytest.raises(InvalidInputError):
                await run_transformation(
                    make_state(source, input_text="   "),
                    config={"configurable": {}},
                )

        mock_provision.assert_not_awaited()
        mock_add_insight.assert_not_awaited()


class TestValidTransformationSourceStillWorks:
    pytestmark = pytest.mark.asyncio

    async def test_valid_source_text_runs_llm_and_persists(self):
        from open_notebook.graphs.transformation import run_transformation

        source = make_source()
        source.full_text = "full text of the source"
        fake_response = MagicMock()
        fake_response.content = "the transformation output"
        fake_chain = AsyncMock()
        fake_chain.ainvoke = AsyncMock(return_value=fake_response)

        with (
            patch(
                "open_notebook.graphs.transformation.DefaultPrompts",
                return_value=MagicMock(transformation_instructions=None),
            ),
            patch(
                "open_notebook.graphs.transformation.Prompter"
            ) as mock_prompter_cls,
            patch(
                "open_notebook.graphs.transformation.provision_langchain_model",
                new=AsyncMock(return_value=fake_chain),
            ) as mock_provision,
            patch.object(
                Source, "add_insight", new=AsyncMock(return_value="command:ok")
            ) as mock_add_insight,
        ):
            mock_prompter_cls.return_value.render.return_value = "rendered prompt"
            result = await run_transformation(
                make_state(source), config={"configurable": {}}
            )

        mock_provision.assert_awaited_once()
        mock_add_insight.assert_awaited_once()
        assert result == {"output": "the transformation output"}

    async def test_valid_explicit_input_overrides_empty_source(self):
        from open_notebook.graphs.transformation import run_transformation

        source = make_source()
        source.full_text = ""
        fake_response = MagicMock()
        fake_response.content = "explicit output"
        fake_chain = AsyncMock()
        fake_chain.ainvoke = AsyncMock(return_value=fake_response)

        with (
            patch(
                "open_notebook.graphs.transformation.DefaultPrompts",
                return_value=MagicMock(transformation_instructions=None),
            ),
            patch(
                "open_notebook.graphs.transformation.Prompter"
            ) as mock_prompter_cls,
            patch(
                "open_notebook.graphs.transformation.provision_langchain_model",
                new=AsyncMock(return_value=fake_chain),
            ) as mock_provision,
            patch.object(
                Source, "add_insight", new=AsyncMock(return_value="command:ok")
            ) as mock_add_insight,
        ):
            mock_prompter_cls.return_value.render.return_value = "rendered prompt"
            result = await run_transformation(
                make_state(source, input_text="explicit valid content"),
                config={"configurable": {}},
            )

        mock_provision.assert_awaited_once()
        mock_add_insight.assert_awaited_once()
        assert result == {"output": "explicit output"}
