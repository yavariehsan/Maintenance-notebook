"""Batch-run provenance metadata (auditable output databases)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnalysisRun:
    """One knowledge-generation run (stored in ``analysis_runs``)."""

    engine_version: str
    schema_version: str
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    input_filename: str = ""
    input_hash: str = ""
    record_count: int = 0
    equipment_count: int = 0
    failure_mode_count: int = 0
    cause_count: int = 0
    repair_action_count: int = 0
    llm_enrichment_enabled: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
