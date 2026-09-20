"""Tests for the Maintenance Agent Asset Registry foundation.

Covers Asset domain validation and API contract (404/400 arms) with mocked
persistence. Live persistence is validated separately against disposable
SurrealDB during milestone validation runs.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from open_notebook.domain.asset import Asset
from open_notebook.exceptions import InvalidInputError, NotFoundError


@pytest.fixture()
def client():
    from api.main import app

    return TestClient(app)


def _nf(*_args, **_kwargs):
    raise NotFoundError("not found")


class TestAssetValidation:
    def test_defaults(self):
        asset = Asset(name="Pump P-101")
        assert asset.table_name == "asset"
        assert asset.status == "active"
        assert asset.description == ""
        assert asset.asset_type is None

    def test_empty_name_rejected(self):
        with pytest.raises(InvalidInputError):
            Asset(name="   ")

    def test_blank_status_rejected(self):
        with pytest.raises(InvalidInputError):
            Asset(name="Pump", status=" ")

    def test_optional_fields(self):
        asset = Asset(
            name="Turbine T-2",
            asset_type="turbine",
            location="Hall B",
            manufacturer="Acme",
            model="T-2000",
            serial_number="SN-42",
        )
        assert asset.location == "Hall B"
        assert asset.serial_number == "SN-42"


class TestAssetApiContract:
    pytestmark = pytest.mark.asyncio
    @patch("api.routers.assets.Asset.get", new_callable=AsyncMock)
    async def test_get_missing_returns_404(self, mock_get, client):
        mock_get.side_effect = _nf
        assert client.get("/api/assets/asset:gone").status_code == 404

    @patch("api.routers.assets.Asset.get", new_callable=AsyncMock)
    async def test_update_missing_returns_404(self, mock_get, client):
        mock_get.side_effect = _nf
        assert client.put("/api/assets/asset:gone", json={"name": "x"}).status_code == 404

    @patch("api.routers.assets.Asset.get", new_callable=AsyncMock)
    async def test_delete_missing_returns_404(self, mock_get, client):
        mock_get.side_effect = _nf
        assert client.delete("/api/assets/asset:gone").status_code == 404

    async def test_create_blank_name_returns_400(self, client):
        response = client.post("/api/assets", json={"name": "   "})
        assert response.status_code == 400

    async def test_list_invalid_order_by_returns_400(self, client):
        assert client.get("/api/assets", params={"order_by": "bogus"}).status_code == 400
