"""Pipeline orchestration and future evidence/ranking interfaces.

This milestone runs the real input → canonical → quality stages and
returns a typed artifact. Guide ranking (the §21 evidence hierarchy) is
exposed as protocols so later milestones implement and test it explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from maintenance_troubleshooting.config import EngineConfig
from maintenance_troubleshooting.domain.evidence import RepairEvidence
from maintenance_troubleshooting.domain.guides import TroubleshootingGuide
from maintenance_troubleshooting.domain.records import MaintenanceRecord
from maintenance_troubleshooting.inputs import (
    ColumnMapping,
    ExcelMaintenanceReader,
    InputReport,
)
from maintenance_troubleshooting.inputs.record_ids import PrefixNumberRecordId
from maintenance_troubleshooting.outputs import TroubleshootingKnowledgeBase
from maintenance_troubleshooting.quality import (
    DataQualityReport,
    DuplicateDetector,
    RecordValidator,
)
from maintenance_troubleshooting.version import __version__ as engine_version


@dataclass
class AnalysisResult:
    """Typed result of :func:`analyze_workbook`."""

    records: list[MaintenanceRecord] = field(default_factory=list)
    quality_report: DataQualityReport = field(default_factory=DataQualityReport)
    knowledge_base: TroubleshootingKnowledgeBase | None = None
    input_report: InputReport | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceQuery:
    """A troubleshooting question, e.g. equipment + failure mode + symptom."""

    equipment_code: str
    failure_mode: str = ""
    symptom_text: str = ""


class EvidenceSource(Protocol):
    """One rung of the future evidence hierarchy (§21 roadmap).

    Implementations collect evidence for a query without ranking it;
    ordering across sources belongs to ``CauseRanker``.
    """

    @property
    def name(self) -> str: ...

    def collect(
        self, query: EvidenceQuery, records: list[MaintenanceRecord]
    ) -> list[RepairEvidence]: ...


class CauseRanker(Protocol):
    """Order candidate causes by evidence strength (future milestone).

    The ordering contract must be explicit and tested; percentages it
    emits must go through ``normalize_probabilities`` with documented
    semantics.
    """

    @property
    def name(self) -> str: ...

    def rank(
        self, query: EvidenceQuery, evidence: list[RepairEvidence]
    ) -> list[TroubleshootingGuide]: ...


def analyze_workbook(
    input_path: str | Path,
    configuration: EngineConfig | None = None,
    column_mapping: ColumnMapping | None = None,
) -> AnalysisResult:
    """Run input → canonical records → data quality; return typed artifact.

    Guide ranking is not implemented in this milestone: the returned
    knowledge base is an (honest, empty) shell carrying source provenance
    and record counts for later stages to populate.
    """
    config = configuration or EngineConfig.default()
    reader = ExcelMaintenanceReader(
        record_id_strategy=PrefixNumberRecordId(),
        sheet_name=config.input.sheet_name,
        header_row=config.input.header_row,
    )
    read_result = reader.read(input_path, column_mapping)

    validator = RecordValidator(min_repair_length=config.text_mining.min_repair_length)
    quality = validator.validate_all(read_result.records)
    quality.duplicates.extend(DuplicateDetector().find_duplicates(read_result.records))

    knowledge_base = TroubleshootingKnowledgeBase.empty(
        engine_version=engine_version, source_path=str(input_path)
    )
    knowledge_base.record_count = len(read_result.records)

    warnings = [
        f"row {row.row_number}: {row.reason}" for row in read_result.report.skipped_rows
    ]
    if quality.duplicates:
        warnings.append(f"{len(quality.duplicates)} duplicate record-ID groups found")

    return AnalysisResult(
        records=read_result.records,
        quality_report=quality,
        knowledge_base=knowledge_base,
        input_report=read_result.report,
        warnings=warnings,
    )
