"""Stage 8 — CauseMiner: group scope evidence into candidate causes.

Cause texts come from separate evidence sources that are never merged at
the field level:

- ``دلیل بروز عیب`` (+ detail) → ``explicitly_recorded``;
- ``مکانیزم خرابی`` → ``technical_mechanism``.

Grouping key is the normalized text; the label is the most frequent raw
variant (ties → smallest). A candidate records every kind it was seen as.
"""

from __future__ import annotations

from collections import Counter

from maintenance_troubleshooting.domain.causes import TroubleshootingCause
from maintenance_troubleshooting.domain.metrics import OccurrenceRate
from maintenance_troubleshooting.stages.base import PipelineContext

EXPLICITLY_RECORDED = "explicitly_recorded"
HISTORICALLY_INFERRED = "historically_inferred"
TECHNICAL_MECHANISM = "technical_mechanism"


class CauseMiner:
    """Extract candidate causes per (equipment, failure mode) scope."""

    name = "causes"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Group evidence into candidates with frequencies and support."""
        include_mechanisms = context.config.cause_mining.include_mechanism_causes
        by_id = {record.record_id: record for record in context.valid_records}
        # (scope_equipment, scope_mode, normalized_text) -> evidence indices.
        # Grouping keys are case-folded: "Axis Control System" and
        # "Axis control system" are the same recorded cause (real-data
        # finding); labels keep the most frequent raw variant.
        groups: dict[tuple[str, str, str], list[int]] = {}
        kinds: dict[tuple[str, str, str], set[str]] = {}
        for index, item in enumerate(context.evidence):
            record = by_id[item.record_id]
            normalized = context.normalized[item.record_id]
            candidates: list[tuple[str, str, str]] = []
            if normalized.normalized_cause:
                candidates.append(
                    (normalized.normalized_cause.casefold(), EXPLICITLY_RECORDED, "cause")
                )
            if (
                include_mechanisms
                and normalized.normalized_mechanism
                and normalized.normalized_mechanism.casefold()
                != normalized.normalized_cause.casefold()
            ):
                candidates.append(
                    (
                        normalized.normalized_mechanism.casefold(),
                        TECHNICAL_MECHANISM,
                        "mechanism",
                    )
                )
            _ = record
            for text, kind, _source in candidates:
                key = (item.scope_equipment, item.scope_failure_mode, text)
                groups.setdefault(key, []).append(index)
                kinds.setdefault(key, set()).add(kind)

        # Usable evidence per scope (denominator population).
        scope_evidence: dict[tuple[str, str], list[int]] = {}
        for index, item in enumerate(context.evidence):
            scope_evidence.setdefault(
                (item.scope_equipment, item.scope_failure_mode), []
            ).append(index)

        causes: list[TroubleshootingCause] = []
        for (equipment_code, mode_id, text) in sorted(groups):
            indices = groups[(equipment_code, mode_id, text)]
            supporting = [context.evidence[i] for i in indices]
            raws: list[str] = []
            for item in supporting:
                record = by_id[item.record_id]
                for kind in kinds[(equipment_code, mode_id, text)]:
                    if kind == EXPLICITLY_RECORDED and record.cause_recorded:
                        raws.append(record.cause_recorded.strip())
                    elif kind == TECHNICAL_MECHANISM and record.failure_mechanism_recorded:
                        raws.append(record.failure_mechanism_recorded.strip())
            counts = Counter(raws)
            top = max(counts.values())
            label = sorted(t for t, n in counts.items() if n == top)[0]
            population = scope_evidence[(equipment_code, mode_id)]
            weights = [context.evidence[i].weight for i in indices]
            causes.append(
                TroubleshootingCause(
                    cause=label,
                    supporting_evidence=supporting,
                    historical_frequency=OccurrenceRate(
                        count=len(indices),
                        total=len(population),
                        population=f"{equipment_code}/{mode_id}",
                    ),
                    similarity_score=max(weights) if weights else 0.0,
                    equipment_code=equipment_code,
                    failure_mode_id=mode_id,
                    kinds=sorted(kinds[(equipment_code, mode_id, text)]),
                )
            )
        causes.sort(key=lambda cause: (cause.equipment_code, cause.failure_mode_id, cause.cause))
        context.causes = causes
        return context
