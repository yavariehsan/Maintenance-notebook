"""Heartbeat keep-alive for source-chat SSE streaming.

Regression test: `stream_source_chat_response` used to go completely silent
for the whole (blocking, minutes-long on CPU-only inference) graph
invocation after the initial `user_message` event. Idle-sensitive proxies
between the browser and the API severed the quiet stream (~30s on the
Next.js dev rewrite proxy) and the UI reported a network error.

The generator must now emit `: ping` SSE comment lines while the invoke
runs. SSE clients ignore `:` comments, so the message protocol is
unchanged; the existing frontend parser only handles `data: ` lines.
"""

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from api.routers import source_chat as sc


class _AiMsg:
    """Minimal langchain-like AI message supporting model_copy()."""

    def __init__(self, content):
        self.type = "ai"
        self.content = content

    def model_copy(self, update):
        return _AiMsg(update.get("content", self.content))


def _slow_graph(delay=0.35):
    """Graph mock whose invoke blocks like a slow LLM call."""
    graph = MagicMock()
    state = MagicMock()
    state.values = {"messages": []}
    graph.get_state.return_value = state

    def _invoke(*, input, config):
        time.sleep(delay)
        return {
            "messages": [_AiMsg("the answer")],
            "context_indicators": {"sources": ["source:1"], "insights": [], "notes": []},
        }

    graph.invoke.side_effect = _invoke
    return graph


def _parse_events(chunks):
    """Split raw SSE chunks into (kind, payload) with comments preserved."""
    events = []
    for chunk in chunks:
        for line in chunk.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith(":"):
                events.append(("comment", line))
            elif line.startswith("data: "):
                events.append(("data", json.loads(line[len("data: "):])))
    return events


@pytest.mark.asyncio
async def test_stream_emits_heartbeats_during_slow_invoke():
    with (
        patch.object(sc, "source_chat_graph", _slow_graph()),
        patch.object(sc, "SOURCE_CHAT_SSE_HEARTBEAT_SECONDS", 0.05),
    ):
        chunks = [
            event
            async for event in sc.stream_source_chat_response(
                session_id="chat_session:abc",
                source_id="source:1",
                message="hello?",
            )
        ]

    events = _parse_events(chunks)
    kinds = [kind for kind, _ in events]

    # user_message first, then heartbeats, then the real protocol untouched.
    assert events[0] == ("data", {"type": "user_message", "content": "hello?", "timestamp": None})
    assert "comment" in kinds
    data_types = [payload["type"] for kind, payload in events if kind == "data"]
    assert data_types[0] == "user_message"
    assert "ai_message" in data_types
    assert "context_indicators" in data_types
    assert data_types[-1] == "complete"

    ai = next(p for k, p in events if k == "data" and p["type"] == "ai_message")
    assert ai["content"] == "the answer"


@pytest.mark.asyncio
async def test_stream_close_mid_invoke_does_not_hang():
    """Client disconnect during inference: generator must finish promptly."""
    with (
        patch.object(sc, "source_chat_graph", _slow_graph(delay=5.0)),
        patch.object(sc, "SOURCE_CHAT_SSE_HEARTBEAT_SECONDS", 0.05),
    ):
        gen = sc.stream_source_chat_response(
            session_id="chat_session:abc",
            source_id="source:1",
            message="hello?",
        )
        first = await gen.__anext__()
        assert "user_message" in first
        await asyncio.wait_for(gen.aclose(), timeout=5.0)
