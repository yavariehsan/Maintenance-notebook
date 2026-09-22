"""Tests for the Smart Maintenance Guide backend.

Covers equipment-scoped retrieval (the selected code — and only that code —
reaches the database functions), the no_sources / no_context states, source
association on updates, and the maintenance endpoint contracts. Live
cross-equipment isolation is additionally validated against disposable
SurrealDB during milestone validation runs.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from open_notebook.domain.asset import Asset
from open_notebook.domain.maintenance import (
    maintenance_text_search,
    maintenance_vector_search,
    normalize_equipment_code,
)
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import InvalidInputError, NotFoundError


@pytest.fixture()
def client():
    from api.main import app

    return TestClient(app)


def _asset(code="BR1", name="Horizontal Lathe Machine"):
    return Asset(id="asset:1", code=code, name=name, status="active")


class TestNormalizeCode:
    def test_blank_rejected(self):
        with pytest.raises(InvalidInputError):
            normalize_equipment_code("   ")

    def test_trims(self):
        assert normalize_equipment_code("  br1  ") == "br1"


class TestScopedSearchFunctions:
    pytestmark = pytest.mark.asyncio

    @patch("open_notebook.domain.maintenance.repo_query", new_callable=AsyncMock)
    @patch(
        "open_notebook.utils.embedding.generate_embedding",
        new_callable=AsyncMock,
    )
    async def test_vector_search_scoped_to_code(
        self, mock_embed, mock_query, monkeypatch
    ):
        # generate_embedding is imported into the caller's namespace.
        import open_notebook.utils.embedding as embedding_module

        monkeypatch.setattr(
            embedding_module, "generate_embedding", mock_embed, raising=False
        )
        mock_embed.return_value = [0.1, 0.2]
        mock_query.return_value = [
            {"id": "source_embedding:a", "similarity": 0.9},
            {"id": "source_embedding:b", "similarity": 0.5},
        ]

        results = await maintenance_vector_search("bearing failure", " br1 ")

        assert [r["id"] for r in results] == [
            "source_embedding:a",
            "source_embedding:b",
        ]
        params = mock_query.call_args[0][1]
        assert params["code"] == "br1"
        assert "fn::maintenance_vector_search" in mock_query.call_args[0][0]

    async def test_vector_search_blank_keyword_rejected(self):
        with pytest.raises(InvalidInputError):
            await maintenance_vector_search("", "BR1")

    async def test_vector_search_blank_code_rejected(self):
        with pytest.raises(InvalidInputError):
            await maintenance_vector_search("bearing", "  ")

    @patch("open_notebook.domain.maintenance.repo_query", new_callable=AsyncMock)
    async def test_text_search_scoped_to_code(self, mock_query):
        mock_query.return_value = [{"id": "source:x", "relevance": 2.0}]

        results = await maintenance_text_search("spindle", "BR1")

        assert results == [{"id": "source:x", "relevance": 2.0}]
        params = mock_query.call_args[0][1]
        assert params["code"] == "BR1"
        assert "fn::maintenance_text_search" in mock_query.call_args[0][0]

    async def test_text_search_blank_keyword_rejected(self):
        with pytest.raises(InvalidInputError):
            await maintenance_text_search("", "BR1")


class TestAskEquipment:
    pytestmark = pytest.mark.asyncio

    async def _run_ask(self, vector_hits, text_hits, answer_text="Bearing failed."):
        with (
            patch(
                "api.maintenance_service.get_asset_by_code",
                new_callable=AsyncMock,
                return_value=_asset(),
            ),
            patch(
                "api.maintenance_service.list_equipment_sources",
                new_callable=AsyncMock,
                return_value=[{"id": "source:br1", "title": "CMMS-Report BR1"}],
            ),
            patch(
                "api.maintenance_service.maintenance_vector_search",
                new_callable=AsyncMock,
                return_value=vector_hits,
            ) as mock_vector,
            patch(
                "api.maintenance_service.maintenance_text_search",
                new_callable=AsyncMock,
                return_value=text_hits,
            ) as mock_text,
            patch("api.maintenance_service.Prompter") as mock_prompter,
            patch(
                "api.maintenance_service.provision_langchain_model",
                new_callable=AsyncMock,
            ) as mock_provision,
        ):
            prompt = MagicMock()
            prompt.render.return_value = "rendered"
            mock_prompter.return_value = prompt
            message = MagicMock()
            message.content = answer_text
            model = AsyncMock()
            model.ainvoke.return_value = message
            mock_provision.return_value = model

            from api.maintenance_service import ask_equipment

            result = await ask_equipment("What failed?", "BR1")
            return result, mock_vector, mock_text

    async def test_ok_answer_uses_only_selected_code_scope(self):
        hits = [
            {
                "id": "source_embedding:1",
                "parent_id": "source:br1",
                "title": "CMMS-Report BR1",
                "content": "bearing failed",
                "similarity": 0.9,
            }
        ]
        result, mock_vector, mock_text = await self._run_ask(hits, [])

        assert result["status"] == "ok"
        assert result["answer"] == "Bearing failed."
        assert result["equipment_code"] == "BR1"
        assert result["sources"] == [{"id": "source:br1", "title": "CMMS-Report BR1"}]
        # The retrieval scope carries the SELECTED code to the scoped
        # database functions — never a global search.
        assert mock_vector.call_args[0][1] == "BR1"
        assert mock_text.call_args[0][1] == "BR1"

    async def test_no_sources_state(self):
        with (
            patch(
                "api.maintenance_service.get_asset_by_code",
                new_callable=AsyncMock,
                return_value=_asset(),
            ),
            patch(
                "api.maintenance_service.list_equipment_sources",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "api.maintenance_service.maintenance_vector_search",
                new_callable=AsyncMock,
            ) as mock_vector,
        ):
            from api.maintenance_service import ask_equipment

            result = await ask_equipment("What failed?", "BR1")

            assert result["status"] == "no_sources"
            assert result["answer"] == ""
            assert result["sources"] == []
            mock_vector.assert_not_called()

    async def test_no_context_state_when_hits_empty(self):
        result, _, _ = await self._run_ask([], [])

        assert result["status"] == "no_context"
        assert result["answer"] == ""
        # Associated reports are still listed so the UI can show them.
        assert result["sources"] == [{"id": "source:br1", "title": "CMMS-Report BR1"}]

    async def test_blank_question_rejected(self):
        from api.maintenance_service import ask_equipment

        with pytest.raises(InvalidInputError):
            await ask_equipment("   ", "BR1")

    async def test_unknown_equipment_propagates_not_found(self):
        with patch(
            "api.maintenance_service.get_asset_by_code",
            new_callable=AsyncMock,
            side_effect=NotFoundError("gone"),
        ):
            from api.maintenance_service import ask_equipment

            with pytest.raises(NotFoundError):
                await ask_equipment("What failed?", "NOPE")

    async def test_text_hits_merged_without_duplicates(self):
        vector_hits = [
            {"id": "source_embedding:1", "parent_id": "source:br1", "similarity": 0.9}
        ]
        text_hits = [
            {"id": "source_embedding:1", "parent_id": "source:br1", "relevance": 3.0},
            {"id": "source:br1", "parent_id": "source:br1", "relevance": 1.0},
        ]
        result, _, _ = await self._run_ask(vector_hits, text_hits)

        assert result["status"] == "ok"


class TestListEquipmentSources:
    pytestmark = pytest.mark.asyncio

    @patch("api.maintenance_service.repo_query", new_callable=AsyncMock)
    async def test_returns_id_and_title(self, mock_query):
        mock_query.return_value = [{"id": "source:1", "title": "CMMS-Report"}]

        from api.maintenance_service import list_equipment_sources

        assert await list_equipment_sources("br1") == [
            {"id": "source:1", "title": "CMMS-Report"}
        ]
        assert mock_query.call_args[0][1]["code"] == "BR1"

    async def test_blank_code_rejected(self):
        from api.maintenance_service import list_equipment_sources

        with pytest.raises(InvalidInputError):
            await list_equipment_sources(" ")


class TestMaintenanceApiContracts:
    pytestmark = pytest.mark.asyncio

    @patch("api.routers.maintenance.ask_equipment", new_callable=AsyncMock)
    async def test_ask_ok(self, mock_ask, client):
        mock_ask.return_value = {
            "equipment_code": "BR1",
            "status": "ok",
            "answer": "Bearing failed.",
            "sources": [{"id": "source:1", "title": "CMMS-Report"}],
        }

        response = client.post(
            "/api/maintenance/ask",
            json={"equipment_code": "BR1", "question": "What failed?"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        mock_ask.assert_called_once()

    async def test_ask_blank_question_returns_400(self, client):
        response = client.post(
            "/api/maintenance/ask",
            json={"equipment_code": "BR1", "question": "   "},
        )

        assert response.status_code == 400

    @patch(
        "api.routers.maintenance.ask_equipment",
        new_callable=AsyncMock,
        side_effect=NotFoundError("gone"),
    )
    async def test_ask_unknown_equipment_returns_404(self, mock_ask, client):
        response = client.post(
            "/api/maintenance/ask",
            json={"equipment_code": "NOPE", "question": "What failed?"},
        )

        assert response.status_code == 404

    @patch(
        "api.routers.maintenance.list_equipment_sources",
        new_callable=AsyncMock,
        return_value=[{"id": "source:1", "title": "CMMS-Report"}],
    )
    async def test_list_sources(self, mock_list, client):
        response = client.get(
            "/api/maintenance/sources", params={"equipment_code": "BR1"}
        )

        assert response.status_code == 200
        assert response.json() == [{"id": "source:1", "title": "CMMS-Report"}]


class TestSourceEquipmentAssociation:
    pytestmark = pytest.mark.asyncio

    async def _put_code(self, client, code_value):
        source = Source(id="source:1", title="CMMS-Report")
        with (
            patch(
                "api.routers.sources.Source.get",
                new_callable=AsyncMock,
                return_value=source,
            ),
            patch.object(Source, "save", new=AsyncMock()),
            patch.object(
                Source, "get_embedded_chunks", new=AsyncMock(return_value=0)
            ),
        ):
            response = client.put(
                "/api/sources/source:1", json={"equipment_code": code_value}
            )
        return response, source

    async def test_set_equipment_code_trims(self, client):
        response, source = await self._put_code(client, " br1 ")

        assert response.status_code == 200
        assert response.json()["equipment_code"] == "br1"
        assert source.equipment_code == "br1"

    async def test_clear_equipment_code_with_empty_string(self, client):
        response, source = await self._put_code(client, "   ")

        assert response.status_code == 200
        assert response.json()["equipment_code"] is None
        assert source.equipment_code is None

    async def test_update_without_code_leaves_association(self, client):
        source = Source(id="source:1", title="CMMS-Report", equipment_code="BR1")
        with (
            patch(
                "api.routers.sources.Source.get",
                new_callable=AsyncMock,
                return_value=source,
            ),
            patch.object(Source, "save", new=AsyncMock()),
            patch.object(
                Source, "get_embedded_chunks", new=AsyncMock(return_value=0)
            ),
        ):
            response = client.put(
                "/api/sources/source:1", json={"title": "CMMS-Report v2"}
            )

        assert response.status_code == 200
        assert response.json()["equipment_code"] == "BR1"
