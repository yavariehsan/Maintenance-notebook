"""Stage 2 — Normalizer: verbatim source text → normalized copies."""

from __future__ import annotations

from maintenance_troubleshooting.domain.normalized import NormalizedRecord
from maintenance_troubleshooting.stages.base import PipelineContext
from maintenance_troubleshooting.text import TextNormalizer


class Normalizer:
    """Normalize free-text fields for matching; originals untouched."""

    name = "normalizer"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Build one ``NormalizedRecord`` per canonical record."""
        normalizer = TextNormalizer(context.config.normalization.to_options())
        normalized: dict[str, NormalizedRecord] = {}
        for record in context.records:
            mode_text = (
                record.failure_mode_recorded or record.proposed_failure_mode or ""
            )
            normalized[record.record_id] = NormalizedRecord(
                record_id=record.record_id,
                equipment_code=record.equipment_code,
                normalized_symptom=normalizer.normalize(record.symptom_text),
                normalized_failure_mode=normalizer.normalize(mode_text),
                normalized_mechanism=normalizer.normalize(
                    record.failure_mechanism_recorded
                ),
                normalized_cause=normalizer.normalize(record.cause_recorded),
                normalized_repair=normalizer.normalize(record.repair_description),
            )
        context.normalized = normalized
        return context
