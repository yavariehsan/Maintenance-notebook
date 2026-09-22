"""Tests for the equipment Excel import and code-uniqueness policy.

Covers workbook parsing/validation (pure, no database), duplicate handling
(in-file and against existing records), row persistence, the import endpoint
contract, and equipment-code lookup. Live persistence is validated separately
against disposable SurrealDB during milestone validation runs.
"""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from api.asset_service import (
    equipment_code_key,
    fetch_existing_code_keys,
    get_asset_by_code,
    import_equipment_rows,
    normalize_equipment_code,
    parse_equipment_workbook,
    reject_existing_codes,
)
from open_notebook.domain.asset import Asset
from open_notebook.exceptions import InvalidInputError, NotFoundError

HEADERS = [
    "Code",
    "Main Description",
    "Factory",
    "Main Function Location",
    "ZONE-Description",
    "SITE-Description",
    "plant-description",
    "Main Class",
    "Sub Class",
    "Type-Description",
    "Manufacture",
    "Model",
]

BR1 = [
    "BR1",
    "Horizontal Lathe Machine",
    "Shop2",
    "Burner&fixter shop-2",
    "Production",
    "Machining",
    "Blade",
    "Machine Tools",
    "CNC",
    "Horizontal Turning",
    "Machine Sazi Tabriz (MST)",
    "TC 20-HS",
]

N51 = [
    "N51",
    "Sawing Machine",
    "Shop1",
    "Burner&fixter shop-2",
    "Production",
    "Engineering",
    "Tool Making",
    "Machine Tools",
    "Manual",
    "Sawing",
    "EDCO(MST)",
    None,  # empty model cell
]


def _workbook_bytes(header=HEADERS, rows=()):
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    wb.close()
    return buffer.getvalue()


@pytest.fixture()
def client():
    from api.main import app

    return TestClient(app)


class TestCodeNormalization:
    def test_key_is_case_insensitive_and_trimmed(self):
        assert equipment_code_key(" br1 ") == equipment_code_key("BR1")
        assert normalize_equipment_code("  T53  ") == "T53"

    def test_blank_code_validator(self):
        with pytest.raises(InvalidInputError):
            Asset(name="Lathe", code="   ")
        # Legacy records without a code stay valid
        assert Asset(name="Lathe").code is None


class TestParseWorkbook:
    def test_valid_rows_mapped_to_equipment_fields(self):
        result = parse_equipment_workbook(_workbook_bytes(rows=[BR1, N51]))

        assert result.total_rows == 2
        assert len(result.valid_rows) == 2
        assert not result.issues
        br1 = result.valid_rows[0].values
        assert br1["code"] == "BR1"
        assert br1["name"] == "Horizontal Lathe Machine"
        assert br1["location"] == "Burner&fixter shop-2"
        assert br1["zone_description"] == "Production"
        assert br1["site_description"] == "Machining"
        assert br1["plant_description"] == "Blade"
        assert br1["main_class"] == "Machine Tools"
        assert br1["sub_class"] == "CNC"
        assert br1["asset_type"] == "Horizontal Turning"
        assert br1["manufacturer"] == "Machine Sazi Tabriz (MST)"
        assert br1["model"] == "TC 20-HS"
        # Empty model cell stays absent, not an empty string
        assert "model" not in result.valid_rows[1].values

    def test_header_and_value_whitespace_trimmed(self):
        header = ["  Code  ", "  Main Description ", *HEADERS[2:]]
        result = parse_equipment_workbook(
            _workbook_bytes(header=header, rows=[["  br1 ", "  Lathe  "]])
        )

        assert len(result.valid_rows) == 1
        assert result.valid_rows[0].values["code"] == "br1"
        assert result.valid_rows[0].values["name"] == "Lathe"

    def test_blank_rows_skipped(self):
        result = parse_equipment_workbook(
            _workbook_bytes(rows=[BR1, [None] * len(HEADERS), N51])
        )

        assert result.total_rows == 2
        assert len(result.valid_rows) == 2

    def test_missing_code_and_description_become_issues(self):
        bad_code = ["   ", "No code machine", *[None] * 10]
        bad_name = ["X9", "   ", *[None] * 10]
        result = parse_equipment_workbook(_workbook_bytes(rows=[bad_code, bad_name]))

        assert result.total_rows == 2
        assert not result.valid_rows
        assert len(result.issues) == 2
        assert "Code" in result.issues[0].message
        assert "Main Description" in result.issues[1].message

    def test_in_file_duplicates_rejected_after_first(self):
        dupe = [" br1 ", "Second lathe with same code", *[None] * 10]
        result = parse_equipment_workbook(_workbook_bytes(rows=[BR1, dupe]))

        assert result.total_rows == 2
        assert len(result.valid_rows) == 1
        assert len(result.issues) == 1
        assert "Duplicate" in result.issues[0].message

    def test_missing_code_column_fails(self):
        with pytest.raises(InvalidInputError, match="[Cc]ode"):
            parse_equipment_workbook(_workbook_bytes(header=["Name", "Model"], rows=[]))

    def test_non_workbook_bytes_fail(self):
        with pytest.raises(InvalidInputError, match="[Ee]xcel"):
            parse_equipment_workbook(b"not a workbook")

    def test_unknown_columns_ignored_not_guessed(self):
        header = [*HEADERS, "Random Notes"]
        result = parse_equipment_workbook(
            _workbook_bytes(header=header, rows=[[*BR1, "should not map"]])
        )

        assert len(result.valid_rows) == 1
        assert "random notes" not in result.valid_rows[0].values


class TestDuplicatePolicy:
    pytestmark = pytest.mark.asyncio

    def test_existing_codes_rejected_never_overwritten(self):
        result = parse_equipment_workbook(_workbook_bytes(rows=[BR1, N51]))
        reject_existing_codes(result, {"BR1"})

        assert len(result.valid_rows) == 1
        assert result.valid_rows[0].values["code"] == "N51"
        assert len(result.issues) == 1
        assert "already exists" in result.issues[0].message
        assert "overwritten" in result.issues[0].message

    def test_existing_match_is_case_insensitive(self):
        result = parse_equipment_workbook(_workbook_bytes(rows=[BR1]))
        reject_existing_codes(result, {"br1"})

        assert not result.valid_rows
        assert len(result.issues) == 1

    @patch("api.asset_service.repo_query", new_callable=AsyncMock)
    async def test_fetch_existing_keys_normalizes(self, mock_query):
        mock_query.return_value = [{"code": " br1 "}, {"code": None}, {}]

        assert await fetch_existing_code_keys() == {"BR1"}

    @patch("api.asset_service.Asset.save", new_callable=AsyncMock)
    async def test_import_rows_persists_valid(self, mock_save):
        result = parse_equipment_workbook(_workbook_bytes(rows=[BR1, N51]))

        imported, issues = await import_equipment_rows(result.valid_rows)

        assert imported == 2
        assert issues == []
        assert mock_save.call_count == 2


class TestGetAssetByCode:
    pytestmark = pytest.mark.asyncio

    @patch("api.asset_service.repo_query", new_callable=AsyncMock)
    async def test_found_case_insensitive(self, mock_query):
        mock_query.return_value = [
            {"id": "asset:1", "code": "BR1", "name": "Lathe", "status": "active"}
        ]

        asset = await get_asset_by_code(" br1 ")

        assert asset.code == "BR1"
        assert mock_query.call_args[0][1]["code"] == "BR1"

    @patch("api.asset_service.repo_query", new_callable=AsyncMock)
    async def test_missing_raises_not_found(self, mock_query):
        mock_query.return_value = []

        with pytest.raises(NotFoundError):
            await get_asset_by_code("NOPE")

    async def test_blank_code_rejected(self):
        with pytest.raises(InvalidInputError):
            await get_asset_by_code("   ")


class TestAssetApiContracts:
    pytestmark = pytest.mark.asyncio

    @patch("api.routers.assets.repo_query", new_callable=AsyncMock)
    async def test_create_duplicate_code_returns_400(self, mock_query, client):
        mock_query.return_value = [{"id": "asset:old"}]

        response = client.post(
            "/api/assets", json={"name": "Lathe", "code": "BR1"}
        )

        assert response.status_code == 400
        assert "BR1" in response.json()["detail"]

    @patch("api.routers.assets.repo_query", new_callable=AsyncMock)
    async def test_by_code_found(self, mock_query, client):
        mock_query.return_value = [
            {
                "id": "asset:1",
                "name": "Lathe",
                "description": "",
                "status": "active",
                "code": "BR1",
            }
        ]

        response = client.get("/api/assets/by-code/br1")

        assert response.status_code == 200
        assert response.json()["code"] == "BR1"

    @patch("api.routers.assets.repo_query", new_callable=AsyncMock)
    async def test_by_code_missing_returns_404(self, mock_query, client):
        mock_query.return_value = []

        assert client.get("/api/assets/by-code/NOPE").status_code == 404

    def test_import_wrong_extension_returns_400(self, client):
        response = client.post(
            "/api/assets/import",
            files={"file": ("equipment.txt", b"Code\nBR1\n", "text/plain")},
        )

        assert response.status_code == 400

    def test_import_missing_code_column_returns_400(self, client):
        response = client.post(
            "/api/assets/import",
            files={
                "file": (
                    "equipment.xlsx",
                    _workbook_bytes(header=["Name"], rows=[]),
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet",
                )
            },
        )

        assert response.status_code == 400
        assert "Code" in response.json()["detail"]

    @patch("api.routers.assets.fetch_existing_code_keys", new_callable=AsyncMock)
    async def test_import_dry_run_previews_without_persisting(
        self, mock_existing, client
    ):
        mock_existing.return_value = set()

        response = client.post(
            "/api/assets/import",
            files={
                "file": (
                    "equipment.xlsx",
                    _workbook_bytes(rows=[BR1, N51]),
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet",
                )
            },
            params={"dry_run": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total_rows"] == 2
        assert len(body["valid_rows"]) == 2
        assert body["issues"] == []
        assert body["imported_count"] == 0

    @patch("api.routers.assets.import_equipment_rows", new_callable=AsyncMock)
    @patch("api.routers.assets.fetch_existing_code_keys", new_callable=AsyncMock)
    async def test_import_confirm_persists_valid_rows(
        self, mock_existing, mock_import, client
    ):
        from api.asset_service import EquipmentImportRow

        mock_existing.return_value = set()

        async def _fake_import(rows):
            return len(rows), []

        mock_import.side_effect = _fake_import

        response = client.post(
            "/api/assets/import",
            files={
                "file": (
                    "equipment.xlsx",
                    _workbook_bytes(rows=[BR1, N51]),
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet",
                )
            },
            params={"dry_run": False},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["imported_count"] == 2
        persisted = mock_import.call_args[0][0]
        assert [r.values["code"] for r in persisted] == ["BR1", "N51"]
        assert all(isinstance(r, EquipmentImportRow) for r in persisted)

    @patch("api.routers.assets.fetch_existing_code_keys", new_callable=AsyncMock)
    async def test_import_reports_existing_duplicates(
        self, mock_existing, client
    ):
        mock_existing.return_value = {"BR1"}

        response = client.post(
            "/api/assets/import",
            files={
                "file": (
                    "equipment.xlsx",
                    _workbook_bytes(rows=[BR1, N51]),
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet",
                )
            },
            params={"dry_run": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["valid_rows"]) == 1
        assert body["valid_rows"][0]["code"] == "N51"
        assert len(body["issues"]) == 1
        assert body["issues"][0]["code"] == "BR1"
