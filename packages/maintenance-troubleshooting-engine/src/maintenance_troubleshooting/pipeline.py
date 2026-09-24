"""Pipeline orchestration: two phases, explicit stages.

Phase A (batch, offline) runs the full stage chain once and materializes
a SQLite troubleshooting database. Phase B (runtime) reads that database
through :class:`TroubleshootingRepository` — no mining at query time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from maintenance_troubleshooting.config import EngineConfig
from maintenance_troubleshooting.domain.equipment import Equipment
from maintenance_troubleshooting.domain.evidence import RepairEvidence
from maintenance_troubleshooting.domain.failure import CanonicalFailureMode
from maintenance_troubleshooting.domain.guides import TroubleshootingGuide
from maintenance_troubleshooting.domain.records import MaintenanceRecord
from maintenance_troubleshooting.domain.run import AnalysisRun
from maintenance_troubleshooting.enrichment import (
    KnowledgeEnrichmentProvider,
    NoOpEnrichmentProvider,
)
from maintenance_troubleshooting.inputs import (
    ColumnMapping,
    InputReport,
)
from maintenance_troubleshooting.outputs import TroubleshootingKnowledgeBase
from maintenance_troubleshooting.quality import DataQualityReport
from maintenance_troubleshooting.stages.base import PipelineContext, Stage
from maintenance_troubleshooting.stages.causes import CauseMiner
from maintenance_troubleshooting.stages.equipment import EquipmentAnalyzer
from maintenance_troubleshooting.stages.evidence import EvidenceMiner
from maintenance_troubleshooting.stages.failure_modes import FailureModeAnalyzer
from maintenance_troubleshooting.stages.normalization import Normalizer
from maintenance_troubleshooting.stages.parsing import RecordParser
from maintenance_troubleshooting.stages.quality import DataQualityAnalyzer
from maintenance_troubleshooting.stages.repairs import RepairActionMiner
from maintenance_troubleshooting.stages.similarity import SimilarityAnalyzer
from maintenance_troubleshooting.stages.synthesis import KnowledgeSynthesizer
from maintenance_troubleshooting.stages.writer import OutputDatabaseWriter
from maintenance_troubleshooting.version import __version__ as engine_version


@dataclass
class AnalysisResult:
    """Typed result of :func:`analyze_workbook`."""

    records: list[MaintenanceRecord] = field(default_factory=list)
    quality_report: DataQualityReport = field(default_factory=DataQualityReport)
    knowledge_base: TroubleshootingKnowledgeBase | None = None
    input_report: InputReport | None = None
    warnings: list[str] = field(default_factory=list)
    equipment: list[Equipment] = field(default_factory=list)
    failure_modes: list[CanonicalFailureMode] = field(default_factory=list)
    guides: list[TroubleshootingGuide] = field(default_factory=list)
    database_path: str | None = None
    run: AnalysisRun | None = None


@dataclass(frozen=True)
class EvidenceQuery:
    """A troubleshooting question, e.g. equipment + failure mode + symptom."""

    equipment_code: str
    failure_mode: str = ""
    symptom_text: str = ""


class EvidenceSource(Protocol):
    """One rung of the evidence hierarchy (custom pipeline extensions).

    Implementations collect evidence for a query without ranking it;
    ordering across sources belongs to ``CauseRanker``.
    """

    @property
    def name(self) -> str: ...

    def collect(
        self, query: EvidenceQuery, records: list[MaintenanceRecord]
    ) -> list[RepairEvidence]: ...


class CauseRanker(Protocol):
    """Order candidate causes by evidence strength (custom extensions).

    The ordering contract must be explicit and tested; percentages it
    emits must go through ``normalize_probabilities`` with documented
    semantics.
    """

    @property
    def name(self) -> str: ...

    def rank(
        self, query: EvidenceQuery, evidence: list[RepairEvidence]
    ) -> list[TroubleshootingGuide]: ...


def build_stages(
    output_path: str | Path | None,
    started_at: str,
    enrichment: KnowledgeEnrichmentProvider | None,
) -> list[Stage]:
    """Assemble the ordered stage chain (Phase A)."""
    stages: list[Stage] = [
        RecordParser(),
        Normalizer(),
        DataQualityAnalyzer(),
        EquipmentAnalyzer(),
        FailureModeAnalyzer(),
        SimilarityAnalyzer(),
        EvidenceMiner(),
        CauseMiner(),
        RepairActionMiner(),
        KnowledgeSynthesizer(provider=enrichment or NoOpEnrichmentProvider()),
    ]
    if output_path is not None:
        stages.append(OutputDatabaseWriter(output_path, started_at=started_at))
    return stages


def analyze_workbook(
    input_path: str | Path,
    configuration: EngineConfig | None = None,
    column_mapping: ColumnMapping | None = None,
    output_path: str | Path | None = None,
    enrichment: KnowledgeEnrichmentProvider | None = None,
) -> AnalysisResult:
    """Run the batch pipeline; optionally materialize the SQLite database.

    Deterministic for identical input + configuration + engine version
    (the ``none`` enrichment default). Pass ``output_path`` to atomically
    write the troubleshooting database; guides are always built in memory.
    """
    config = configuration or EngineConfig.default()
    started_at = datetime.now(timezone.utc).isoformat()
    context = PipelineContext(
        config=config,
        column_mapping=column_mapping or ColumnMapping.default(),
        input_path=str(input_path),
    )
    for stage in build_stages(output_path, started_at, enrichment):
        context = stage.run(context)

    knowledge_base = TroubleshootingKnowledgeBase.empty(
        engine_version=engine_version, source_path=str(input_path)
    )
    knowledge_base.record_count = len(context.records)

    # Legacy JSON-knowledge-base compatibility: expose mined guides through
    # the M1 artifact shape (guides are the new content; counts stay honest).
    knowledge_base.guides = list(context.guides)

    return AnalysisResult(
        records=context.records,
        quality_report=context.quality_report,
        knowledge_base=knowledge_base,
        input_report=context.input_report,
        warnings=list(context.warnings),
        equipment=sorted(context.equipment.values(), key=lambda e: e.equipment_code),
        failure_modes=sorted(context.failure_modes.values(), key=lambda m: m.key),
        guides=list(context.guides),
        database_path=str(output_path) if output_path is not None else None,
        run=context.run,
    )


# --- Public orchestration helpers --------------------------------------------

__all__ = [
    "AnalysisResult",
    "CauseRanker",
    "EvidenceQuery",
    "EvidenceSource",
    "analyze_workbook",
    "build_stages",
]
