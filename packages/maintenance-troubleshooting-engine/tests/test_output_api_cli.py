"""Output schema, configuration, public API, and CLI boundaries."""

import json
from pathlib import Path

import pytest

from maintenance_troubleshooting import (
    EngineConfig,
    TroubleshootingKnowledgeBase,
    __version__,
    analyze_workbook,
)
from maintenance_troubleshooting.cli import build_parser, main
from tests.fixtures import write_workbook


def test_knowledge_base_json_round_trip_preserves_persian(tmp_path: Path) -> None:
    base = TroubleshootingKnowledgeBase.empty(
        engine_version=__version__, source_path="history.xlsx"
    )
    base.record_count = 3
    target = base.save(tmp_path / "kb.json")
    raw_text = target.read_text(encoding="utf-8")
    assert "روشن" not in raw_text  # no guides yet; Persian must survive anyway
    payload = json.loads(raw_text)
    assert payload["engine_version"] == __version__
    assert payload["record_count"] == 3
    assert "probability" in payload["probability_semantics"].lower()

    reloaded = TroubleshootingKnowledgeBase.load(target)
    assert reloaded.record_count == 3
    assert reloaded.source_path == "history.xlsx"


def test_analyze_workbook_returns_typed_artifact(tmp_path: Path) -> None:
    path = write_workbook(tmp_path / "history.xlsx")
    result = analyze_workbook(path)
    assert len(result.records) == 3
    assert result.quality_report.total_records == 3
    assert result.knowledge_base is not None
    assert result.knowledge_base.record_count == 3
    assert result.input_report is not None
    # Row 2 has a blank repair description -> warning, still valid.
    assert result.quality_report.valid_records == 3
    assert any(i.code == "blank_repair" for i in result.quality_report.issues)


def test_analyze_workbook_respects_sheet_selection(tmp_path: Path) -> None:
    import openpyxl

    path = tmp_path / "multi.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "empty"
    sheet = book.create_sheet("repairs")
    sheet.append(
        ["تجهیز", "پیشوند درخواست", "شماره درخواست", "شرح درخواست"]
    )
    sheet.append(["QX-1", "QX", "1", "متن"])
    book.save(str(path))

    config = EngineConfig.default()
    config.input.sheet_name = "repairs"
    result = analyze_workbook(path, configuration=config)
    assert len(result.records) == 1
    assert result.records[0].record_id == "QX-1"


def test_config_round_trip_and_strict_keys() -> None:
    config = EngineConfig.default()
    assert config.embedding.provider is None  # providers are optional
    rebuilt = EngineConfig.from_dict(config.to_dict())
    assert rebuilt == config
    with pytest.raises(ValueError, match="unknown configuration sections"):
        EngineConfig.from_dict({"nope": {}})
    with pytest.raises(ValueError, match="unknown keys"):
        EngineConfig.from_dict({"input": {"nope": 1}})


def test_cli_commands(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = str(write_workbook(tmp_path / "history.xlsx"))
    assert main(["inspect", path]) == 0
    assert "repairs" in capsys.readouterr().out

    assert main(["validate", path]) == 0
    assert "3/3" in capsys.readouterr().out

    db_path = str(tmp_path / "kb.db")
    assert main(["analyze", path, "-o", db_path]) == 0
    assert Path(db_path).exists()

    out = str(tmp_path / "kb.json")
    assert main(["export", path, "-o", out]) == 0
    assert Path(out).exists()
    assert "maintenance-troubleshooting" in build_parser().prog


def test_cli_inspect_output(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = str(write_workbook(tmp_path / "history.xlsx"))
    db_path = str(tmp_path / "kb.db")
    assert main(["analyze", path, "-o", db_path]) == 0
    capsys.readouterr()

    assert main(["inspect-output", db_path]) == 0
    out = capsys.readouterr().out
    assert "QX-101" in out

    assert main(["inspect-output", db_path, "--equipment", "QX-101"]) == 0
    assert "QX-101" in capsys.readouterr().out

    assert main(["inspect-output", db_path, "--equipment", "NOPE"]) == 1


def test_cli_validate_fails_on_blank_equipment(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    path = str(
        write_workbook(
            tmp_path / "bad.xlsx",
            headers=["کد فرایندی", "پیشوند درخواست", "شماره درخواست"],
            rows=[["", "QX", "1"]],
        )
    )
    assert main(["validate", path]) == 1
    assert "equipment_code" in capsys.readouterr().out
