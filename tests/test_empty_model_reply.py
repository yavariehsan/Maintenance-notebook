"""Empty model reply handling (P0.3).

A successful model invocation that yields empty/whitespace-only text must not
be treated as a valid answer: chat and source-chat raise the existing
ExternalServiceError before anything is appended to history; the
transformation graph raises InvalidInputError before any insight is
persisted. Valid responses pass through unchanged.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from open_notebook.exceptions import ExternalServiceError, InvalidInputError


def _chain_with_output(content: str):
    chain = MagicMock()
    chain.invoke = MagicMock(return_value=AIMessage(content=content))
    ainvoke = AsyncMock(return_value=AIMessage(content=content))
    chain.ainvoke = ainvoke
    return chain


class TestChatEmptyReply:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty", ["", "   ", "\n\t \n"])
    async def test_empty_reply_is_error(self, empty: str):
        from open_notebook.graphs import chat as chat_graph

        chain = _chain_with_output(empty)
        with patch.object(
            chat_graph, "provision_langchain_model", new=AsyncMock(return_value=chain)
        ):
            with pytest.raises(ExternalServiceError):
                chat_graph.call_model_with_messages(
                    {"messages": [], "notebook": None, "context": None,
                     "context_config": None, "model_override": None},
                    {"configurable": {}},
                )

    @pytest.mark.asyncio
    async def test_valid_reply_passes_through(self):
        from open_notebook.graphs import chat as chat_graph

        chain = _chain_with_output("hello there")
        with patch.object(
            chat_graph, "provision_langchain_model", new=AsyncMock(return_value=chain)
        ):
            result = chat_graph.call_model_with_messages(
                {"messages": [], "notebook": None, "context": None,
                 "context_config": None, "model_override": None},
                {"configurable": {}},
            )
        assert result["messages"].content == "hello there"


class TestSourceChatEmptyReply:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty", ["", "   "])
    async def test_empty_reply_is_error(self, empty: str):
        from open_notebook.graphs import source_chat as sc

        chain = _chain_with_output(empty)
        with (
            patch.object(
                sc, "build_source_context",
                new=AsyncMock(return_value={"sources": [], "insights": []}),
            ),
            patch.object(
                sc, "provision_langchain_model",
                new=AsyncMock(return_value=chain),
            ),
        ):
            with pytest.raises(ExternalServiceError):
                sc.call_model_with_source_context(
                    {"messages": [], "source_id": "source:x", "source": None,
                     "insights": None, "context": None, "model_override": None,
                     "context_indicators": None},
                    {"configurable": {}},
                )

    @pytest.mark.asyncio
    async def test_valid_reply_passes_through(self):
        from open_notebook.graphs import source_chat as sc

        chain = _chain_with_output("grounded answer")
        with (
            patch.object(
                sc, "build_source_context",
                new=AsyncMock(return_value={"sources": [], "insights": []}),
            ),
            patch.object(
                sc, "provision_langchain_model",
                new=AsyncMock(return_value=chain),
            ),
        ):
            result = sc.call_model_with_source_context(
                {"messages": [], "source_id": "source:x", "source": None,
                 "insights": None, "context": None, "model_override": None,
                 "context_indicators": None},
                {"configurable": {}},
            )
        assert result["messages"].content == "grounded answer"


class TestTransformationEmptyOutput:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty", ["", "   "])
    async def test_empty_model_output_rejected_without_persist(
        self, empty: str
    ):
        from open_notebook.domain.notebook import Source
        from open_notebook.graphs.transformation import run_transformation

        source = Source(id="source:t", title="T", asset=None)
        source.full_text = "real source text with evidence"
        transformation = MagicMock(title="Summary", prompt="Summarize")
        chain = _chain_with_output(empty)

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
                new=AsyncMock(return_value=chain),
            ) as mock_provision,
            patch.object(
                Source, "add_insight", new=AsyncMock(return_value="command:ok")
            ) as mock_add_insight,
        ):
            mock_prompter_cls.return_value.render.return_value = "prompt"
            with pytest.raises(InvalidInputError):
                await run_transformation(
                    {"source": source, "input_text": None,
                     "transformation": transformation},
                    {"configurable": {}},
                )
        mock_provision.assert_awaited_once()
        mock_add_insight.assert_not_awaited()
