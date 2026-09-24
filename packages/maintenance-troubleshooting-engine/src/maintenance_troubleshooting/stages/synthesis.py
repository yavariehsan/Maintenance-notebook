"""Stage 10 — KnowledgeSynthesizer: evidence → guides with support math.

Support formula (``similarity-weighted-share-v1``)::

    support_percent(cause) =
        100 * Σ weights of the cause's supporting evidence
            / Σ weights of all usable scope evidence

Usable evidence = same-canonical-mode records with technical weight > 0.
The denominator, numerator, method, and evidence IDs are all stored, so
any percentage reproduces exactly. Percentages are shares of evidence
weight — never calibrated probabilities (see ``metrics``).

Confidence rule (``evidence-count-v1``, thresholds configurable)::

    high         count >= high_min_count and denominator >= high_min_denom
    medium       count >= medium_min_count and denominator >= medium_min_denom
    low          at least one supporting record
    insufficient otherwise
"""

from __future__ import annotations

from typing import Any

from maintenance_troubleshooting.domain.causes import (
    SupportBreakdown,
    TroubleshootingCause,
)
from maintenance_troubleshooting.domain.evidence import RelevanceBasis, RepairEvidence
from maintenance_troubleshooting.domain.failure import FailureMode, FailureProvenance
from maintenance_troubleshooting.domain.guides import (
    RecommendedAction,
    TroubleshootingGuide,
)
from maintenance_troubleshooting.domain.metrics import (
    Confidence,
    ProbabilityMethod,
    normalize_probabilities,
)
from maintenance_troubleshooting.enrichment import (
    EnrichmentInput,
    EnrichmentRecordRef,
    KnowledgeEnrichmentProvider,
    NoOpEnrichmentProvider,
    validate_enrichment,
)
from maintenance_troubleshooting.stages.base import PipelineContext
from maintenance_troubleshooting.stages.causes import (
    EXPLICITLY_RECORDED,
    HISTORICALLY_INFERRED,
    TECHNICAL_MECHANISM,
)

_ACCEPTED_SUGGESTED_KINDS = {
    EXPLICITLY_RECORDED,
    HISTORICALLY_INFERRED,
    TECHNICAL_MECHANISM,
}


class KnowledgeSynthesizer:
    """Rank causes, score support, link actions, assemble guides."""

    name = "synthesis"

    def __init__(self, provider: KnowledgeEnrichmentProvider | None = None) -> None:
        self.provider = provider or NoOpEnrichmentProvider()

    def run(self, context: PipelineContext) -> PipelineContext:
        """Synthesize every (equipment, failure mode) scope in order."""
        context.enrichment_provider = self.provider.name
        model = getattr(self.provider, "model", None)
        context.enrichment_model = model if isinstance(model, str) else None
        scopes = sorted(
            {
                (cause.equipment_code, cause.failure_mode_id)
                for cause in context.causes
            }
        )
        for equipment_code, mode_id in scopes:
            self._synthesize_scope(context, equipment_code, mode_id)
        context.guides.sort(key=lambda guide: (guide.equipment_code, guide.failure_mode.key))
        return context

    def _synthesize_scope(
        self, context: PipelineContext, equipment_code: str, mode_id: str
    ) -> None:
        scope_causes = sorted(
            (
                cause
                for cause in context.causes
                if cause.equipment_code == equipment_code
                and cause.failure_mode_id == mode_id
            ),
            key=lambda cause: cause.cause,
        )
        scope_evidence = [
            item
            for item in context.evidence
            if item.scope_equipment == equipment_code
            and item.scope_failure_mode == mode_id
        ]
        denominator = sum(item.weight for item in scope_evidence)
        scoring = context.config.scoring

        for cause in scope_causes:
            weights = [item.weight for item in cause.supporting_evidence]
            cause.weighted_evidence = sum(weights)
            cause.denominator = denominator
            cause.calculation_method = scoring.support_method
            cause.support_percent = (
                100.0 * cause.weighted_evidence / denominator if denominator > 0 else 0.0
            )
            cause.support = self._breakdown(cause)
            cause.confidence = self._confidence(context, cause)
        scope_causes.sort(key=lambda c: (-(c.support_percent or 0.0), c.cause))

        try:
            method = ProbabilityMethod(scoring.probability_method)
        except ValueError:
            context.warnings.append(
                f"unknown probability method '{scoring.probability_method}'; "
                "probabilities omitted"
            )
            method = None
        if method is not None:
            for probability in normalize_probabilities(
                {c.cause: (c.support_percent or 0.0) for c in scope_causes}, method
            ):
                next(c for c in scope_causes if c.cause == probability.cause).probability = probability

        for rank, cause in enumerate(scope_causes, start=1):
            cause.rank = rank
            cause.cause_id = f"cause-{equipment_code}-{mode_id}-{rank:02d}"

        self._apply_enrichment(context, equipment_code, mode_id, scope_causes)
        self._link_actions(context, equipment_code, mode_id, scope_causes)
        self._collect_safety(context, equipment_code, mode_id, scope_causes, scope_evidence)
        context.guides.append(
            self._assemble_guide(context, equipment_code, mode_id, scope_causes, scope_evidence)
        )

    @staticmethod
    def _breakdown(cause: TroubleshootingCause) -> SupportBreakdown:
        """Max weight per relevance dimension (None = no evidence)."""

        def peak(*bases: RelevanceBasis) -> float | None:
            weights = [
                item.weight
                for item in cause.supporting_evidence
                if item.relevance_basis in bases
            ]
            return max(weights) if weights else None

        non_exact = tuple(
            basis
            for basis in RelevanceBasis
            if basis is not RelevanceBasis.EXACT_EQUIPMENT
        )
        return SupportBreakdown(
            technical_tree_support=peak(*non_exact),
            equipment_specific_support=peak(RelevanceBasis.EXACT_EQUIPMENT),
            manufacturer_support=peak(RelevanceBasis.SAME_MANUFACTURER_AND_TYPE),
            model_support=peak(RelevanceBasis.SAME_TECHNICAL_MODEL),
            failure_mode_support=1.0,
        )

    def _confidence(
        self, context: PipelineContext, cause: TroubleshootingCause
    ) -> Confidence:
        """Documented evidence-count rule (see module docstring)."""
        scoring = context.config.scoring
        count = cause.evidence_count
        denominator = cause.denominator
        if (
            count >= scoring.confidence_high_min_count
            and denominator >= scoring.confidence_high_min_denominator
        ):
            return Confidence(value=0.9, basis="evidence-count-v1:high")
        if (
            count >= scoring.confidence_medium_min_count
            and denominator >= scoring.confidence_medium_min_denominator
        ):
            return Confidence(value=0.6, basis="evidence-count-v1:medium")
        if count >= 1:
            return Confidence(value=0.3, basis="evidence-count-v1:low")
        return Confidence(value=0.0, basis="evidence-count-v1:insufficient")

    def _link_actions(
        self,
        context: PipelineContext,
        equipment_code: str,
        mode_id: str,
        scope_causes: list[TroubleshootingCause],
    ) -> None:
        """Link scope actions to causes sharing source records (top-N kept)."""
        limit = context.config.cause_mining.max_actions_per_cause
        scope_actions = sorted(
            (
                action
                for action in context.repair_actions
                if action.equipment_code == equipment_code
                and action.failure_mode_id == mode_id
            ),
            key=lambda action: (-action.frequency, action.action_text),
        )
        for cause in scope_causes:
            supporting_ids = {item.record_id for item in cause.supporting_evidence}
            linked = [
                action
                for action in scope_actions
                if supporting_ids & set(action.source_record_ids)
            ][:limit]
            cause.recommended_actions = [action.action_text for action in linked]
            for action in linked:
                link = (cause.cause_id, action.action_id)
                if link not in context.cause_repair_links:
                    context.cause_repair_links.append(link)

    def _apply_enrichment(
        self,
        context: PipelineContext,
        equipment_code: str,
        mode_id: str,
        scope_causes: list[TroubleshootingCause],
    ) -> None:
        """Run the optional provider on bounded scope input; validate first."""
        if self.provider.name == "none":
            return
        mode = context.failure_modes[mode_id]
        scope_records = sorted(
            {item.record_id for cause in scope_causes for item in cause.supporting_evidence}
        )
        capped = scope_records[: context.config.enrichment.max_records_per_scope]
        by_id = {record.record_id: record for record in context.valid_records}
        equipment = context.equipment[equipment_code]
        refs = tuple(
            EnrichmentRecordRef(
                record_id=rid,
                equipment_code=by_id[rid].equipment_code,
                symptom=(by_id[rid].request_description or "")[:500],
                repair=(by_id[rid].repair_description or "")[:1000],
                cause=(by_id[rid].cause_recorded or "")[:300],
                mechanism=(by_id[rid].failure_mechanism_recorded or "")[:300],
                failure_mode_recorded=(by_id[rid].failure_mode_recorded or "")[:300],
            )
            for rid in capped
        )
        tech = tuple(
            (level, value)
            for level, value in zip(
                ("t1", "t2", "t3", "t4", "t5"), equipment.technical_tree.levels()
            )
            if value
        )
        result, warnings = validate_enrichment(
            self.provider.enrich(
                EnrichmentInput(
                    equipment_code=equipment_code,
                    failure_mode_label=mode.canonical_label,
                    records=refs,
                    technical_context=tech,
                )
            ),
            set(scope_records),
        )
        for warning in warnings:
            context.warnings.append(f"{equipment_code}/{mode_id}: {warning}")
        if result.canonical_label_suggestion:
            mode.enriched_label = result.canonical_label_suggestion
        for suggestion in result.suggested_causes:
            kind = (
                suggestion.kind
                if suggestion.kind in _ACCEPTED_SUGGESTED_KINDS
                else HISTORICALLY_INFERRED
            )
            linked = [
                item
                for cause in scope_causes
                for item in cause.supporting_evidence
                if item.record_id in suggestion.basis_record_ids
            ]
            if not linked:
                context.warnings.append(
                    f"{equipment_code}/{mode_id}: dropped suggestion "
                    f"'{suggestion.cause_label}' (no scope evidence)"
                )
                continue
            scope_causes.append(
                TroubleshootingCause(
                    cause=suggestion.cause_label,
                    supporting_evidence=linked,
                    equipment_code=equipment_code,
                    failure_mode_id=mode_id,
                    kinds=[kind],
                    recommended_actions=[
                        a.action_text
                        for a in result.suggested_actions
                        if set(a.basis_record_ids) & {i.record_id for i in linked}
                    ],
                )
            )
            context.causes.append(scope_causes[-1])
        if result.suggested_causes:
            # Re-rank after enrichment additions (support math identical).
            denominator = sum(
                item.weight
                for cause in scope_causes
                for item in cause.supporting_evidence
            )
            for cause in scope_causes:
                if not cause.calculation_method:
                    cause.weighted_evidence = sum(
                        item.weight for item in cause.supporting_evidence
                    )
                    cause.denominator = denominator
                    cause.calculation_method = context.config.scoring.support_method
                    cause.support_percent = (
                        100.0 * cause.weighted_evidence / denominator if denominator else 0.0
                    )
                    cause.support = self._breakdown(cause)
                    cause.confidence = self._confidence(context, cause)
            scope_causes.sort(key=lambda c: (-(c.support_percent or 0.0), c.cause))
            for rank, cause in enumerate(scope_causes, start=1):
                cause.rank = rank
                cause.cause_id = f"cause-{equipment_code}-{mode_id}-{rank:02d}"

    def _collect_safety(
        self,
        context: PipelineContext,
        equipment_code: str,
        mode_id: str,
        scope_causes: list[TroubleshootingCause],
        scope_evidence: list[RepairEvidence],
    ) -> None:
        """Associate recorded safety notes with causes (never invented)."""
        by_id = {record.record_id: record for record in context.valid_records}
        seen: dict[str, dict[str, Any]] = {}
        for cause in scope_causes:
            cause_id = cause.cause_id
            for item in cause.supporting_evidence:
                note = (by_id[item.record_id].safety_notes or "").strip()
                if not note:
                    continue
                entry = seen.setdefault(
                    note,
                    {
                        "equipment_code": equipment_code,
                        "failure_mode_id": mode_id,
                        "note_text": note,
                        "cause_ids": [],
                        "source_record_ids": [],
                    },
                )
                if cause_id and cause_id not in entry["cause_ids"]:
                    entry["cause_ids"].append(cause_id)
                if item.record_id not in entry["source_record_ids"]:
                    entry["source_record_ids"].append(item.record_id)
        for entry in seen.values():
            entry["cause_ids"].sort()
            entry["source_record_ids"].sort()
            context.safety_notes.append(entry)

    def _assemble_guide(
        self,
        context: PipelineContext,
        equipment_code: str,
        mode_id: str,
        scope_causes: list[TroubleshootingCause],
        scope_evidence: list[RepairEvidence],
    ) -> TroubleshootingGuide:
        """Assemble the structured guide (ranked causes, actions, evidence)."""
        mode = context.failure_modes[mode_id]
        by_id = {record.record_id: record for record in context.valid_records}
        own_symptoms = sorted(
            {
                (by_id[item.record_id].request_description or "").strip()
                for item in scope_evidence
                if item.equipment_code == equipment_code
                and (by_id[item.record_id].request_description or "").strip()
            }
        )
        label = mode.enriched_label or mode.canonical_label
        guide_mode = FailureMode(
            key=mode.key, label=label, provenance=FailureProvenance.INFERRED
        )
        warnings: list[str] = []
        scope_actions = [
            action
            for action in context.repair_actions
            if action.equipment_code == equipment_code
            and action.failure_mode_id == mode_id
        ]
        if not scope_actions:
            warnings.append(
                "insufficient_historical_repair_evidence: no repair actions "
                "could be extracted for this failure mode"
            )
        recommended: list[RecommendedAction] = []
        position = 1
        for cause in scope_causes:
            for text in cause.recommended_actions[:3]:
                recommended.append(
                    RecommendedAction(
                        order=position,
                        action=text,
                        source_record_ids=sorted(
                            {
                                item.record_id
                                for item in cause.supporting_evidence
                            }
                        ),
                    )
                )
                position += 1
        return TroubleshootingGuide(
            equipment_code=equipment_code,
            failure_mode=guide_mode,
            symptom_summary=own_symptoms[0] if own_symptoms else label,
            candidate_causes=list(scope_causes),
            recommended_actions=recommended,
            evidence=sorted(scope_evidence, key=lambda item: item.evidence_id),
            generated_from_record_ids=sorted(
                {item.record_id for item in scope_evidence}
            ),
            warnings=warnings,
        )
