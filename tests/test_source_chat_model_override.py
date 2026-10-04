"""Model-override resolution for the source-chat send/update endpoints.

Regression coverage for the model failure/recovery lifecycle (A -> provider
failure -> B): a failed request must not lock the conversation to the failed
model. The model supplied by the newest request (falling back to the
persisted session override) must reach the streaming execution, and the
session update endpoint must persist — and explicitly clear — overrides.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _session(**overrides):
    defaults = dict(
        id="chat_session:abc",
        title="Session",
        created="2026-01-01T00:00:00",
        updated="2026-01-02T00:00:00",
        model_override="model-a",
        save=AsyncMock(),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _source():
    return SimpleNamespace(id="source:xyz", title="My Source")


async def _empty_stream():
    yield 'data: {"type": "complete"}\n\n'


def _stream_factory(captured):
    def _fake(*args, **kwargs):
        captured.update(kwargs)
        return _empty_stream()

    return _fake


def _patch_common(mock_verify, mock_count, session):
    mock_verify.return_value = (
        "source:xyz",
        _source(),
        "chat_session:abc",
        session,
    )
    mock_count.return_value = 0


@pytest.mark.asyncio
@patch("api.routers.source_chat.stream_source_chat_response")
@patch(
    "api.routers.source_chat.get_verified_source_session", new_callable=AsyncMock
)
async def test_request_override_reaches_execution(mock_verify, mock_stream, client):
    """The model on the newest request beats the persisted session model."""
    session = _session(model_override="model-a")
    mock_verify.return_value = (
        "source:xyz",
        _source(),
        "chat_session:abc",
        session,
    )
    captured = {}
    mock_stream.side_effect = _stream_factory(captured)

    resp = client.post(
        "/api/sources/xyz/chat/sessions/abc/messages",
        json={"message": "hi", "model_override": "model-b"},
    )

    assert resp.status_code == 200
    assert captured.get("model_override") == "model-b"


@pytest.mark.asyncio
@patch("api.routers.source_chat.stream_source_chat_response")
@patch(
    "api.routers.source_chat.get_verified_source_session", new_callable=AsyncMock
)
async def test_session_override_used_when_request_has_none(
    mock_verify, mock_stream, client
):
    session = _session(model_override="model-a")
    mock_verify.return_value = (
        "source:xyz",
        _source(),
        "chat_session:abc",
        session,
    )
    captured = {}
    mock_stream.side_effect = _stream_factory(captured)

    resp = client.post(
        "/api/sources/xyz/chat/sessions/abc/messages",
        json={"message": "hi"},
    )

    assert resp.status_code == 200
    assert captured.get("model_override") == "model-a"


@pytest.mark.asyncio
@patch("api.routers.source_chat.get_session_message_count", new_callable=AsyncMock)
@patch(
    "api.routers.source_chat.get_verified_source_session", new_callable=AsyncMock
)
async def test_update_persists_new_override(mock_verify, mock_count, client):
    session = _session(model_override="model-a")
    _patch_common(mock_verify, mock_count, session)

    resp = client.put(
        "/api/sources/xyz/chat/sessions/abc",
        json={"model_override": "model-b"},
    )

    assert resp.status_code == 200
    assert session.model_override == "model-b"
    assert resp.json()["model_override"] == "model-b"


@pytest.mark.asyncio
@patch("api.routers.source_chat.get_session_message_count", new_callable=AsyncMock)
@patch(
    "api.routers.source_chat.get_verified_source_session", new_callable=AsyncMock
)
async def test_update_explicit_null_clears_override(mock_verify, mock_count, client):
    """Reset-to-default must clear a previously persisted override."""
    session = _session(model_override="model-a")
    _patch_common(mock_verify, mock_count, session)

    resp = client.put(
        "/api/sources/xyz/chat/sessions/abc",
        json={"model_override": None},
    )

    assert resp.status_code == 200
    assert session.model_override is None
    assert resp.json()["model_override"] is None


@pytest.mark.asyncio
@patch("api.routers.source_chat.get_session_message_count", new_callable=AsyncMock)
@patch(
    "api.routers.source_chat.get_verified_source_session", new_callable=AsyncMock
)
async def test_update_without_override_key_leaves_model(mock_verify, mock_count, client):
    session = _session(model_override="model-a")
    _patch_common(mock_verify, mock_count, session)

    resp = client.put(
        "/api/sources/xyz/chat/sessions/abc",
        json={"title": "Renamed"},
    )

    assert resp.status_code == 200
    assert session.title == "Renamed"
    assert session.model_override == "model-a"
