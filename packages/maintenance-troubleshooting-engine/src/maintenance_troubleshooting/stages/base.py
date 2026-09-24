"""Explicit batch-pipeline stages and the shared context.

Each stage reads upstream artifacts from ``PipelineContext`` and writes
its own. Stages are deterministic: stable ordering everywhere, no random
clustering, no wall-clock values inside mined artifacts (timestamps live
only in run metadata).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from maintenance_troubleshooting.config import EngineConfig
from maintenance_troubleshooting.domain.causes import TroubleshootingCause
from maintenance_troubleshooting.domain.equipment import Equipment
from maintenance_troubleshooting.domain.evidence import RepairEvidence
from maintenance_troubleshooting.domain.failure import CanonicalFailureMode
from maintenance_troubleshooting.domain.guides import TroubleshootingGuide
from maintenance_troubleshooting.domain.normalized import NormalizedRecord
from maintenance_troubleshooting.domain.records import MaintenanceRecord
from maintenance_troubleshooting.domain.repairs import RepairAction
from maintenance_troubleshooting.domain.run import AnalysisRun
from maintenance_troubleshooting.inputs import ColumnMapping, InputReport
from maintenance_troubleshooting.quality import DataQualityReport


@dataclass
class PipelineContext:
    """All artifacts exchanged between stages (single run)."""

    config: EngineConfig = field(default_factory=EngineConfig.default)
    column_mapping: ColumnMapping = field(default_factory=ColumnMapping.default)
    input_path: str = ""
    input_hash: str = ""
    records: list[MaintenanceRecord] = field(default_factory=list)
    input_report: InputReport | None = None
    normalized: dict[str, NormalizedRecord] = field(default_factory=dict)
    quality_report: DataQualityReport = field(default_factory=DataQualityReport)
    valid_records: list[MaintenanceRecord] = field(default_factory=list)
    equipment: dict[str, Equipment] = field(default_factory=dict)
    failure_modes: dict[str, CanonicalFailureMode] = field(default_factory=dict)
    record_failure_mode: dict[str, str] = field(default_factory=dict)
    similarity_weights: dict[tuple[str, str], float] = field(default_factory=dict)
    similarity_reasons: dict[tuple[str, str], str] = field(default_factory=dict)
    evidence: list[RepairEvidence] = field(default_factory=list)
    causes: list[TroubleshootingCause] = field(default_factory=list)
    repair_actions: list[RepairAction] = field(default_factory=list)
    cause_repair_links: list[tuple[str, str]] = field(default_factory=list)
    guides: list[TroubleshootingGuide] = field(default_factory=list)
    safety_notes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    run: AnalysisRun | None = None
    enrichment_provider: str = "none"
    enrichment_model: str | None = None


class Stage(Protocol):
    """One named batch-pipeline stage."""

    @property
    def name(self) -> str: ...

    def run(self, context: PipelineContext) -> PipelineContext: ...
