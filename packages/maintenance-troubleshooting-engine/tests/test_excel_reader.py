"""Excel reader: mapping, identifiers, raw retention, error reporting."""

from pathlib import Path
from typing import Any

import pytest

from maintenance_troubleshooting.inputs import (
    ColumnMapping,
    ExcelMaintenanceReader,
    preserve_identifier,
)
from tests.fixtures import SYNTHETIC_HEADERS, write_workbook


def test_reads_synthetic_workbook_with_defaults(tmp_path: Path) -> None:
    path = write_workbook(tmp_path / "history.xlsx")
    result = ExcelMaintenanceReader().read(path)
    assert len(result.records) == 3
    first = result.records[0]
    assert first.record_id == "QX-1001"
    assert first.equipment_code == "QX-101"
    assert first.request_description == "دستگاه روشن نمی‌شود"
    assert first.repair_description == "تعویض بلبرینگ اسپیندل انجام شد"
    assert first.failure_mode_recorded == "روشن نشدن دستگاه"
    assert first.technical_tree.t1 == "ماشین‌ابزار"
    assert first.technical_tree.t5 == "مدل X1"
    assert first.location_tree == "سالن ۱"  # context, not similarity
    assert result.report.records_built == 3
    assert result.report.skipped_rows == []
    # Raw cells retained verbatim.
    assert first.raw["تجهیز"] == "QX-101"


def test_equipment_codes_survive_numeric_cells(tmp_path: Path) -> None:
    headers = ["تجهیز", "پیشوند درخواست", "شماره درخواست"]
    rows: list[list[Any]] = [["QX-1", "QX", 7], ["B104", "B", 104.0], [210, "M", "5"]]
    path = write_workbook(tmp_path / "codes.xlsx", headers=headers, rows=rows)
    records = ExcelMaintenanceReader().read(path).records
    assert [r.equipment_code for r in records] == ["QX-1", "B104", "210"]
    assert [r.record_id for r in records] == ["QX-7", "B-104", "M-5"]


def test_preserve_identifier_unit_cases() -> None:
    assert preserve_identifier("B104") == "B104"
    assert preserve_identifier("  H13  ") == "H13"
    assert preserve_identifier(210) == "210"
    assert preserve_identifier(211.0) == "211"
    assert preserve_identifier(None) is None
    assert preserve_identifier("") is None
    assert preserve_identifier("   ") is None


def test_empty_and_unbuildable_rows_are_reported(tmp_path: Path) -> None:
    headers = ["تجهیز", "پیشوند درخواست", "شماره درخواست"]
    rows: list[list[Any]] = [
        ["QX-1", "QX", "1"],
        [None, None, None],  # empty -> counted, skipped
        ["", "", ""],  # empty -> counted, skipped
        ["QX-2", "", ""],  # unbuildable -> skipped with reason
        ["QX-2", "QX", "2", "extra-cell"],  # unmapped content lands in extra
    ]
    path = write_workbook(tmp_path / "messy.xlsx", headers=headers, rows=rows)
    result = ExcelMaintenanceReader().read(path)
    assert len(result.records) == 2
    assert result.report.empty_rows == 2
    assert len(result.report.skipped_rows) == 1
    assert "prefix" in result.report.skipped_rows[0].reason


def test_missing_required_columns_raise(tmp_path: Path) -> None:
    path = write_workbook(
        tmp_path / "bad.xlsx",
        headers=["تجهیز", "شرح درخواست"],
        rows=[["QX-1", "متن"]],
    )
    with pytest.raises(ValueError, match="missing required columns"):
        ExcelMaintenanceReader().read(path)


def test_configurable_aliases_and_unmapped_headers(tmp_path: Path) -> None:
    headers = ["MY_EQUIP", "MY_PREFIX", "MY_NUMBER", "یادداشت آزاد"]
    rows: list[list[Any]] = [["QX-9", "QX", "9", "چیزی"]]
    mapping = (
        ColumnMapping.default()
        .with_alias("equipment_code", "MY_EQUIP")
        .with_alias("request_prefix", "MY_PREFIX")
        .with_alias("request_number", "MY_NUMBER")
    )
    resolved = mapping.resolve(headers)
    assert resolved.missing_required == []
    path = write_workbook(tmp_path / "aliased.xlsx", headers=headers, rows=rows)
    result = ExcelMaintenanceReader().read(path, mapping)
    assert result.records[0].equipment_code == "QX-9"
    assert result.records[0].record_id == "QX-9"
    assert result.records[0].extra == {"یادداشت آزاد": "چیزی"}
    assert "یادداشت آزاد" in result.report.schema.unmapped_headers


def test_default_mapping_covers_documented_contract() -> None:
    from maintenance_troubleshooting.inputs import DEFAULT_COLUMN_ALIASES

    assert set(DEFAULT_COLUMN_ALIASES) >= {
        "equipment_code",
        "request_prefix",
        "request_number",
        "repair_description",
        "failure_mode",
        "failure_mechanism",
        "t1",
        "t5",
        "t11",
    }
    # Every synthetic fixture header must resolve through the defaults.
    known = {alias for options in DEFAULT_COLUMN_ALIASES.values() for alias in options}
    assert all(header in known for header in SYNTHETIC_HEADERS)
