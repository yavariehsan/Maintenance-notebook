"""Validation tooling: deterministic splits, leakage, reports, evaluation."""

import json
from pathlib import Path

from maintenance_troubleshooting import EngineConfig, analyze_workbook
from maintenance_troubleshooting.validation import (
    build_report,
    check_leakage,
    evaluate_test_records,
    split_equipment,
    write_split_workbooks,
)
from tests.fixtures import write_workbook


def _coded_workbook(path: Path, codes: list[str]) -> None:
    headers = ["کد فرایندی", "پیشوند درخواست", "شماره درخواست", "شرح درخواست"]
    rows = [[code, code, str(i), "متن"] for i, code in enumerate(codes)]
    write_workbook(path, headers=headers, rows=rows)


def test_split_is_deterministic_and_leak_free() -> None:
    codes = [f"E{i}" for i in range(1, 14)]
    first = split_equipment(codes, test_fraction=0.2, seed=42)
    second = split_equipment(codes, test_fraction=0.2, seed=42)
    assert first == second
    assert check_leakage(first) == []
    assert len(first.test_codes) == 3
    assert len(first.train_codes) == 10
    assert sorted(first.train_codes + first.test_codes) == sorted(codes)


def test_split_round_trips_json() -> None:
    from maintenance_troubleshooting.validation.split import EquipmentSplit

    split = split_equipment(["A", "B", "C"], test_fraction=0.34, seed=7)
    assert EquipmentSplit.from_dict(split.to_dict()) == split


def test_write_split_workbooks_partitions_rows(tmp_path: Path) -> None:
    source = tmp_path / "all.xlsx"
    _coded_workbook(source, ["E1", "E1", "E2", "E3", "E3", "E3"])
    split = split_equipment(["E1", "E2", "E3"], test_fraction=0.34, seed=1)
    counts = write_split_workbooks(
        source, split, tmp_path / "train.xlsx", tmp_path / "test.xlsx"
    )
    assert counts["train_rows"] + counts["test_rows"] == 6
    from maintenance_troubleshooting.inputs import ExcelMaintenanceReader

    train = ExcelMaintenanceReader().read(tmp_path / "train.xlsx").records
    test = ExcelMaintenanceReader().read(tmp_path / "test.xlsx").records
    assert {r.equipment_code for r in train} == set(split.train_codes)
    assert {r.equipment_code for r in test} == set(split.test_codes)


def test_build_report_self_audit_and_suspicious(tmp_path: Path) -> None:
    headers = ["کد فرایندی", "پیشوند درخواست", "شماره درخواست", "شرح درخواست",
               "شرح تعمیر", "حالت خرابی", "دلیل بروز عیب"]
    rows = [
        ["E1", "E1", "1", "متن یک", "تعمیر شد", "روشن نشدن", "12- ایرادی وجود نداشت"],
        ["E1", "E1", "2", "متن دو", "تعویض شد", "روشن نشدن", "8- استهلاک قطعه یدکی"],
    ]
    source = tmp_path / "mini.xlsx"
    write_workbook(source, headers=headers, rows=rows)
    db_path = tmp_path / "mini.db"
    result = analyze_workbook(
        source, configuration=EngineConfig.default(), output_path=db_path
    )
    report = build_report(result, db_path)
    assert report.support_audit["mismatches"] == 0
    assert report.support_audit["causes_checked"] >= 1
    assert "12- ایرادی وجود نداشت" in report.suspicious["generic_causes"]
    saved = report.save(tmp_path / "report")
    assert saved["json"].exists() and saved["markdown"].exists()
    payload = json.loads(saved["json"].read_text(encoding="utf-8"))
    assert payload["dataset"]["total_records"] == 2


def test_evaluate_test_records_labels_proxy_hits(tmp_path: Path) -> None:
    headers = ["کد فرایندی", "پیشوند درخواست", "شماره درخواست", "شرح درخواست",
               "شرح تعمیر", "حالت خرابی", "دلیل بروز عیب",
               "t1", "t2", "t3", "t4", "t5"]
    tree = ["MACHINE TOOLS", "فرز", "فرز عمودی", "OMV", "HSC-800"]
    train_rows = [
        ["E1", "E1", "1", "دستگاه روشن نمی‌شود", "تعویض شد", "روشن نشدن", "خرابی پمپ"] + tree,
        ["E1", "E1", "2", "دستگاه روشن نمی‌شود", "تعمیر شد", "روشن نشدن", "خرابی پمپ"] + tree,
    ]
    test_rows = [
        ["E2", "E2", "1", "دستگاه روشن نمی‌شود", "تعویض شد", "روشن نشدن", "خرابی پمپ"] + tree,
    ]
    train_path = tmp_path / "train.xlsx"
    test_path = tmp_path / "test.xlsx"
    write_workbook(train_path, headers=headers, rows=train_rows)
    write_workbook(test_path, headers=headers, rows=test_rows)
    from maintenance_troubleshooting.inputs import ExcelMaintenanceReader
    from maintenance_troubleshooting.stages.base import PipelineContext
    from maintenance_troubleshooting.stages.causes import CauseMiner
    from maintenance_troubleshooting.stages.equipment import EquipmentAnalyzer
    from maintenance_troubleshooting.stages.evidence import EvidenceMiner
    from maintenance_troubleshooting.stages.failure_modes import FailureModeAnalyzer
    from maintenance_troubleshooting.stages.normalization import Normalizer
    from maintenance_troubleshooting.stages.parsing import RecordParser
    from maintenance_troubleshooting.stages.quality import DataQualityAnalyzer
    from maintenance_troubleshooting.stages.similarity import SimilarityAnalyzer
    from maintenance_troubleshooting.stages.synthesis import KnowledgeSynthesizer

    train_result = analyze_workbook(train_path, configuration=EngineConfig.default())
    context = PipelineContext(config=EngineConfig.default(), input_path=str(train_path))
    for stage in (
        RecordParser(), Normalizer(), DataQualityAnalyzer(), EquipmentAnalyzer(),
        FailureModeAnalyzer(), SimilarityAnalyzer(), EvidenceMiner(), CauseMiner(),
    ):
        context = stage.run(context)
    _ = KnowledgeSynthesizer  # synthesis not needed for association paths
    test_records = ExcelMaintenanceReader().read(test_path).records
    evaluation = evaluate_test_records(test_records, context, train_result)
    assert evaluation.total == 1
    assert evaluation.equipment_matched == 1
    assert evaluation.mode_matched == 1
    assert evaluation.cause_hits == 1
