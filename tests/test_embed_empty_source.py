"""Regression tests: POST /embed on a source with no extractable text.

Root cause (live investigation, 2026-09-28): ``PM.pdf``
(``source:fbmvpvdkyjt88bgn9v0u``, SHA256
``D5C96116B6CFA523A4B2F85C03B005B432469D0327D59EDC36A5983774EF938D``)
is a valid, unencrypted 15-page image-only (scanned) PDF: pdfplumber
extracts 0 characters on every page (one full-page image per page), so
content-core returns empty content, ``process_source`` fails with "Could
not extract any text content", and the source record keeps
``full_text=""``. ``Table.pdf`` (``source:fudjo0i7or2ot0zpzskt``) has a
real text layer (10655 chars) and embeds normally.

``Source.vectorize()`` documents ``ValueError`` for the empty-text guard
(covered in ``tests/test_domain.py``); the bug was that POST /embed let
that ``ValueError`` fall into the generic handler and returned an opaque
HTTP 500. It must return 400 with the domain message instead, while
sources with text keep returning 200.

The 4 MB/3.6 MB PDFs are not vendored as fixtures; the defect lives at
the submission layer (empty ``full_text``) and is reproduced
deterministically without them.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from open_notebook.domain.notebook import Source


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _source_with_text(text):
    source = Source(title="PM", full_text=text)
    object.__setattr__(source, "id", "source:fbmvpvdkyjt88bgn9v0u")
    return source


class TestEmbedEmptySourceText:
    """api/routers/embedding.py: POST /api/embed with a text-less source."""

    def test_empty_text_returns_400_not_500(self, client):
        with (
            patch(
                "api.routers.embedding.Source.get",
                new=AsyncMock(return_value=_source_with_text("")),
            ),
            patch(
                "open_notebook.ai.models.model_manager.get_embedding_model",
                new=AsyncMock(return_value=object()),
            ),
        ):
            response = client.post(
                "/api/embed",
                json={
                    "item_id": "source:fbmvpvdkyjt88bgn9v0u",
                    "item_type": "source",
                    "async_processing": False,
                },
            )

        assert response.status_code == 400
        assert "has no text to vectorize" in response.json()["detail"]

    def test_whitespace_text_returns_400_not_500(self, client):
        with (
            patch(
                "api.routers.embedding.Source.get",
                new=AsyncMock(return_value=_source_with_text("   \n  ")),
            ),
            patch(
                "open_notebook.ai.models.model_manager.get_embedding_model",
                new=AsyncMock(return_value=object()),
            ),
        ):
            response = client.post(
                "/api/embed",
                json={
                    "item_id": "source:fbmvpvdkyjt88bgn9v0u",
                    "item_type": "source",
                    "async_processing": False,
                },
            )

        assert response.status_code == 400

    def test_source_with_text_still_succeeds(self, client):
        """Table.pdf equivalent: extracted text submits the job (200)."""
        with (
            patch(
                "api.routers.embedding.Source.get",
                new=AsyncMock(
                    return_value=_source_with_text("INNSE BERARDI Machine Tools")
                ),
            ),
            patch.object(
                Source, "vectorize", new=AsyncMock(return_value="command:abc123")
            ),
            patch(
                "open_notebook.ai.models.model_manager.get_embedding_model",
                new=AsyncMock(return_value=object()),
            ),
        ):
            response = client.post(
                "/api/embed",
                json={
                    "item_id": "source:fudjo0i7or2ot0zpzskt",
                    "item_type": "source",
                    "async_processing": False,
                },
            )

        assert response.status_code == 200
        assert response.json()["command_id"] == "command:abc123"
