"""Stage 7 — EvidenceMiner: scope evidence per (equipment, failure mode).

Evidence comes only from records sharing the scope's canonical failure
mode, weighted by the precomputed technical similarity between the
record's equipment and the guide equipment. Unrelated equipment (weight
0) contributes nothing — it cannot make machines similar.
"""

from __future__ import annotations

from maintenance_troubleshooting.domain.evidence import RelevanceBasis, RepairEvidence
from maintenance_troubleshooting.similarity import TechnicalSimilarityCategory
from maintenance_troubleshooting.stages.base import PipelineContext

_BASIS_BY_CATEGORY = {
    TechnicalSimilarityCategory.EXACT_EQUIPMENT: RelevanceBasis.EXACT_EQUIPMENT,
    TechnicalSimilarityCategory.SAME_MODEL: RelevanceBasis.SAME_TECHNICAL_MODEL,
    TechnicalSimilarityCategory.SAME_MANUFACTURER_AND_TYPE: (
        RelevanceBasis.SAME_MANUFACTURER_AND_TYPE
    ),
    TechnicalSimilarityCategory.SAME_EQUIPMENT_TYPE: RelevanceBasis.SAME_EQUIPMENT_TYPE,
    TechnicalSimilarityCategory.SAME_SUBCLASS: RelevanceBasis.SAME_TECHNICAL_CLASS,
    TechnicalSimilarityCategory.SAME_MAIN_CLASS: RelevanceBasis.SAME_TECHNICAL_CLASS,
}


class EvidenceMiner:
    """Collect weighted evidence for every (equipment, mode) scope."""

    name = "evidence"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Mine evidence; scopes come from each equipment's own modes."""
        from maintenance_troubleshooting.similarity import classify_technical_similarity

        by_id = {record.record_id: record for record in context.valid_records}
        # Modes attested by each equipment's own records.
        scopes: dict[str, set[str]] = {}
        for record in context.valid_records:
            mode = context.record_failure_mode.get(record.record_id)
            if mode:
                scopes.setdefault(record.equipment_code, set()).add(mode)

        evidence: list[RepairEvidence] = []
        for equipment_code in sorted(scopes):
            for mode_id in sorted(scopes[equipment_code]):
                for record_id in sorted(by_id):
                    if context.record_failure_mode.get(record_id) != mode_id:
                        continue
                    record = by_id[record_id]
                    weight = context.similarity_weights.get(
                        (record.equipment_code, equipment_code), 0.0
                    )
                    if weight <= 0.0:
                        continue
                    category = classify_technical_similarity(
                        context.equipment[record.equipment_code].technical_tree,
                        context.equipment[equipment_code].technical_tree,
                        same_equipment_code=(record.equipment_code == equipment_code),
                    )
                    basis = _BASIS_BY_CATEGORY.get(category)
                    if basis is None:  # unrelated / indeterminate: no evidence
                        continue
                    reason = context.similarity_reasons.get(
                        (record.equipment_code, equipment_code), category.value
                    )
                    evidence.append(
                        RepairEvidence(
                            evidence_id=f"ev-{equipment_code}-{mode_id}-{record_id}",
                            record_id=record_id,
                            equipment_code=record.equipment_code,
                            relevance_basis=basis,
                            repair_action=(record.repair_description or "").strip() or None,
                            cause=(record.cause_recorded or "").strip() or None,
                            mechanism=(record.failure_mechanism_recorded or "").strip() or None,
                            technical_snapshot=record.technical_tree,
                            scope_equipment=equipment_code,
                            scope_failure_mode=mode_id,
                            relevance_detail=f"{reason}+same_failure_mode",
                            weight=weight,
                        )
                    )
        evidence.sort(key=lambda item: (-item.weight, item.evidence_id))
        context.evidence = evidence
        return context
