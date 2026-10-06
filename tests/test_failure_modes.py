"""Tests for the equipment failure-mode database (Database B).

Covers FailureMode domain validation, API contract (404/400 arms),
Excel import (dry-run preview + confirm), and the critical separation
guarantee: failure-mode writes never touch the asset table and
equipment imports never touch the failure-mode table.
"""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from open_notebook.domain.failure_mode import FailureMode
from open_notebook.exceptions import InvalidInputError, NotFoundError


@pytest.fixture()
def client():
    from api.main import app

    return TestClient(app)


def _nf(*_args, **_kwargs):
    raise NotFoundError("not found")


def _workbook_bytes(headers, rows) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


class TestFailureModeValidation:
    def test_table_and_defaults(self):
        mode = FailureMode(code="B138", label="تعویض ابزار")
        assert mode.table_name == "failure_mode"
        assert mode.status == "active"
        assert mode.description == ""

    def test_blank_code_rejected(self):
        with pytest.raises(InvalidInputError):
            FailureMode(code="   ", label="x")

    def test_blank_label_rejected(self):
        with pytest.raises(InvalidInputError):
            FailureMode(code="B138", label="  ")

    def test_optional_fields(self):
        mode = FailureMode(code="b138", label="Seal wear", description="d",
                           status="inactive")
        assert mode.description == "d"
        assert mode.status == "inactive"


class TestFailureModeApiContract:
    pytestmark = pytest.mark.asyncio

    @patch("api.routers.failure_modes.FailureMode.get", new_callable=AsyncMock)
    async def test_get_missing_returns_404(self, mock_get, client):
        mock_get.side_effect = _nf
        assert client.get("/api/failure-modes/failure_mode:gone").status_code == 404

    @patch("api.routers.failure_modes.FailureMode.get", new_callable=AsyncMock)
    async def test_delete_missing_returns_404(self, mock_get, client):
        mock_get.side_effect = _nf
        assert client.delete("/api/failure-modes/failure_mode:gone").status_code == 404

    async def test_create_blank_label_returns_400(self, client):
        response = client.post("/api/failure-modes",
                               json={"code": "B138", "label": "   "})
        assert response.status_code == 400

    async def test_create_blank_code_returns_400(self, client):
        response = client.post("/api/failure-modes",
                               json={"code": "  ", "label": "x"})
        assert response.status_code == 400

    async def test_import_wrong_extension_returns_400(self, client):
        response = client.post(
            "/api/failure-modes/import",
            files={"file": ("modes.txt", b"nope", "text/plain")},
        )
        assert response.status_code == 400


class TestFailureModeImport:
    pytestmark = pytest.mark.asyncio

    def test_parse_valid_workbook(self):
        from api.failure_mode_service import parse_failure_mode_workbook

        content = _workbook_bytes(
            ["Code", "Failure Mode", "Description"],
            [["B138", "تعویض ابزار", "tool change"]],
        )
        result = parse_failure_mode_workbook(content)
        assert result.total_rows == 1
        assert len(result.valid_rows) == 1
        assert result.valid_rows[0].values["code"] == "B138"
        assert result.valid_rows[0].values["label"] == "تعویض ابزار"
        assert result.issues == []

    def test_parse_missing_code_column(self):
        from api.failure_mode_service import parse_failure_mode_workbook

        content = _workbook_bytes(["Nope"], [["x"]])
        with pytest.raises(InvalidInputError):
            parse_failure_mode_workbook(content)

    def test_parse_rejects_blank_label(self):
        from api.failure_mode_service import parse_failure_mode_workbook

        content = _workbook_bytes(
            ["Code", "Failure Mode"],
            [["B138", "   "], ["B139", "Seal"]],
        )
        result = parse_failure_mode_workbook(content)
        assert result.total_rows == 2
        assert len(result.valid_rows) == 1
        assert len(result.issues) == 1
        assert result.issues[0].row_number == 2

    async def test_import_confirm_writes_only_failure_mode_table(self, client):
        content = _workbook_bytes(
            ["Code", "Failure Mode"],
            [["B138", "تعویض ابزار"]],
        )
        with (
            patch("api.routers.failure_modes.fetch_existing_mode_keys",
                  new=AsyncMock(return_value=set())),
            patch("open_notebook.domain.failure_mode.FailureMode.save",
                  new=AsyncMock()) as mock_fm_save,
            patch("open_notebook.domain.asset.Asset.save",
                  new=AsyncMock()) as mock_asset_save,
        ):
            response = client.post(
                "/api/failure-modes/import?dry_run=false",
                files={"file": ("modes.xlsx", content,
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["imported_count"] == 1
        assert mock_fm_save.await_count == 1
        mock_asset_save.assert_not_awaited()

    async def test_dry_run_writes_nothing(self, client):
        content = _workbook_bytes(
            ["Code", "Failure Mode"],
            [["B138", "تعویض ابزار"]],
        )
        with (
            patch("api.routers.failure_modes.fetch_existing_mode_keys",
                  new=AsyncMock(return_value=set())),
            patch("open_notebook.domain.failure_mode.FailureMode.save",
                  new=AsyncMock()) as mock_fm_save,
        ):
            response = client.post(
                "/api/failure-modes/import?dry_run=true",
                files={"file": ("modes.xlsx", content,
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert response.status_code == 200
        assert response.json()["imported_count"] == 0
        mock_fm_save.assert_not_awaited()
