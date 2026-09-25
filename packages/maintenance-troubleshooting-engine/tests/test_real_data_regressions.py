"""Real-data regression fixtures (sanitized edge cases from Sample-1).

Phrases below are generic maintenance terms observed in the real sample;
no operational record content is reproduced.
"""

from pathlib import Path
from typing import Any

from maintenance_troubleshooting.inputs import ExcelMaintenanceReader
from maintenance_troubleshooting.stages.base import PipelineContext
from maintenance_troubleshooting.stages.causes import CauseMiner
from maintenance_troubleshooting.stages.equipment import EquipmentAnalyzer
from maintenance_troubleshooting.stages.evidence import EvidenceMiner
from maintenance_troubleshooting.stages.failure_modes import FailureModeAnalyzer
from maintenance_troubleshooting.stages.normalization import Normalizer
from maintenance_troubleshooting.stages.quality import DataQualityAnalyzer
from maintenance_troubleshooting.stages.similarity import SimilarityAnalyzer
from tests.fixtures import write_workbook

HEADERS = [
    "کد فرایندی",
    "تجهیز",
    "پیشوند درخواست",
    "شماره درخواست",
    "شرح درخواست",
    "شرح تعمیر",
    "حالت خرابی",
    "مکانیزم خرابی",
    "دلیل بروز عیب",
    "t1",
    "t2",
    "t3",
    "t4",
    "t5",
    "توع درخواست",
]


def _row(code: str, num: str, **overrides: Any) -> list[Any]:
    base: dict[str, Any] = {
        "کد فرایندی": code,
        "تجهیز": f"machine {code}",
        "پیشوند درخواست": code,
        "شماره درخواست": num,
        "شرح درخواست": "دستگاه روشن نمی‌شود",
        "شرح تعمیر": "منبع تغذیه تعویض شد",
        "حالت خرابی": "روشن نشدن ماشین (پاور ماشین)",
        "مکانیزم خرابی": "",
        "دلیل بروز عیب": "8- استهلاک قطعه یدکی",
        "t1": "MACHINE TOOLS",
        "t2": "فرز",
        "t3": "فرز عمودی",
        "t4": "OMV",
        "t5": "HSC-800",
        "توع درخواست": "تعمیر",
    }
    base.update(overrides)
    return [base[h] for h in HEADERS]


def test_placeholder_dash_is_missing_everywhere(tmp_path: Path) -> None:
    """'-' placeholders must not form clusters, mechanisms, or trees."""
    rows = [
        _row("M1", "1", **{"حالت خرابی": "-", "مکانیزم خرابی": "-", "t1": "-"}),
        _row("M1", "2", **{"حالت خرابی": "-", "مکانیزم خرابی": "-"}),
    ]
    path = write_workbook(tmp_path / "dash.xlsx", headers=HEADERS, rows=rows)
    result = ExcelMaintenanceReader().read(path)
    assert len(result.records) == 2
    assert result.records[0].failure_mode_recorded is None
    assert result.records[0].failure_mechanism_recorded is None
    assert result.records[0].technical_tree.t1 is None
    # Raw originals retained for traceability.
    assert result.records[0].raw["حالت خرابی"] == "-"


def test_real_typo_header_resolves_request_type(tmp_path: Path) -> None:
    """The sample's 'توع درخواست' header maps to request_type."""
    path = write_workbook(tmp_path / "typo.xlsx", headers=HEADERS, rows=[_row("M1", "1")])
    record = ExcelMaintenanceReader().read(path).records[0]
    assert record.request_type == "تعمیر"


def _mined_context(records: list) -> PipelineContext:
    context = PipelineContext()
    context.records = records
    context = Normalizer().run(context)
    context = DataQualityAnalyzer().run(context)
    context.valid_records = list(context.records)
    context = EquipmentAnalyzer().run(context)
    context = FailureModeAnalyzer().run(context)
    context = SimilarityAnalyzer().run(context)
    context = EvidenceMiner().run(context)
    return context


def test_case_variant_causes_merge(tmp_path: Path) -> None:
    """'Axis Control System' vs 'Axis control system' → one candidate."""
    rows = [
        _row("M1", "1", **{"دلیل بروز عیب": "Axis Control System"}),
        _row("M1", "2", **{"دلیل بروز عیب": "Axis control system"}),
        _row("M1", "3", **{"دلیل بروز عیب": "A11 axis control system"}),
    ]
    path = write_workbook(tmp_path / "case.xlsx", headers=HEADERS, rows=rows)
    records = ExcelMaintenanceReader().read(path).records
    context = _mined_context(records)
    context = CauseMiner().run(context)
    labels = sorted(c.cause for c in context.causes)
    assert labels == ["A11 axis control system", "Axis Control System"]
    merged = next(c for c in context.causes if c.cause == "Axis Control System")
    assert merged.evidence_count == 2


def test_distinct_numbered_causes_stay_separate(tmp_path: Path) -> None:
    """'10- منشا ایراد مشخص نشد' vs '10- موردی مشاهده نشد' must not merge."""
    rows = [
        _row("M1", "1", **{"دلیل بروز عیب": "10- منشا ایراد مشخص نشد"}),
        _row("M1", "2", **{"دلیل بروز عیب": "10- موردی مشاهده نشد"}),
    ]
    path = write_workbook(tmp_path / "num.xlsx", headers=HEADERS, rows=rows)
    records = ExcelMaintenanceReader().read(path).records
    context = _mined_context(records)
    context = CauseMiner().run(context)
    assert len(context.causes) == 2
