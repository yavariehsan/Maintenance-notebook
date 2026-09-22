"""Per-batch progress callback for generate_embeddings.

The Tasks page progress must come from real worker state, so
`generate_embeddings` accepts an async on_progress(processed, total)
callback invoked after each successful batch. Failures inside the
callback must never break embedding.
"""

from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.utils import embedding as embedding_module
from open_notebook.utils.embedding import generate_embeddings


class _FakeEmbeddingModel:
    async def aembed(self, batch):
        return [[float(len(text))] * 4 for text in batch]


@pytest.mark.asyncio
async def test_generate_embeddings_reports_per_batch_progress(monkeypatch):
    monkeypatch.setattr(embedding_module, "EMBEDDING_BATCH_SIZE", 2)
    fake_manager = AsyncMock()
    fake_manager.get_embedding_model.return_value = _FakeEmbeddingModel()
    calls = []

    async def on_progress(processed, total):
        calls.append((processed, total))

    with patch(
        "open_notebook.ai.models.model_manager", fake_manager
    ):
        result = await generate_embeddings(
            ["a", "bb", "ccc", "dddd", "eeeee"], on_progress=on_progress
        )

    assert len(result) == 5
    # Batches of 2, 2, 1 over 5 texts.
    assert calls == [(2, 5), (4, 5), (5, 5)]


@pytest.mark.asyncio
async def test_generate_embeddings_survives_progress_callback_failure():
    fake_manager = AsyncMock()
    fake_manager.get_embedding_model.return_value = _FakeEmbeddingModel()

    async def bad_callback(processed, total):
        raise RuntimeError("progress store down")

    with patch(
        "open_notebook.ai.models.model_manager", fake_manager
    ):
        result = await generate_embeddings(["a", "bb"], on_progress=bad_callback)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_generate_embeddings_without_callback_unchanged():
    fake_manager = AsyncMock()
    fake_manager.get_embedding_model.return_value = _FakeEmbeddingModel()

    with patch(
        "open_notebook.ai.models.model_manager", fake_manager
    ):
        result = await generate_embeddings(["a", "bb"])

    assert len(result) == 2
