"""Train/test evaluation without ground-truth fabrication.

Knowledge is built from train equipment only. Each held-out test record
is then associated with:

- nearest train equipment (technical similarity; location never used),
- nearest train canonical failure mode (lexical match),
- candidate causes of the matched (equipment, mode) scope.

Association rates use the test record's *recorded* cause as a clearly
labeled proxy — not as ground truth. No precision/recall is claimed;
limitations are reported explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from maintenance_troubleshooting.domain.records import MaintenanceRecord
from maintenance_troubleshooting.pipeline import AnalysisResult
from maintenance_troubleshooting.similarity import classify_technical_similarity
from maintenance_troubleshooting.stages.base import PipelineContext
from maintenance_troubleshooting.stages.similarity import category_reason
from maintenance_troubleshooting.text import (
    SimpleTokenizer,
    TextNormalizer,
    TokenSetSimilarity,
)


@dataclass
class TestRecordOutcome:
    """Association outcome for one held-out record (proxy-based)."""

    record_id: str
    equipment_code: str
    nearest_train_equipment: str | None = None
    similarity_reason: str = ""
    matched_mode_id: str | None = None
    mode_match_score: float = 0.0
    recorded_cause: str = ""
    cause_hit: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class EvaluationReport:
    """Association rates over the held-out set (labeled, not ground truth)."""

    total: int = 0
    equipment_matched: int = 0
    mode_matched: int = 0
    cause_hits: int = 0
    outcomes: list[TestRecordOutcome] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """One-line human summary."""
        if not self.total:
            return "no test records evaluated"
        return (
            f"{self.equipment_matched}/{self.total} equipment matched, "
            f"{self.mode_matched}/{self.total} modes matched, "
            f"{self.cause_hits}/{self.total} recorded-cause hits"
        )


def _nearest_equipment(
    record: MaintenanceRecord, context: PipelineContext
) -> tuple[str | None, str]:
    """Best train equipment by technical category order (deterministic)."""
    order = [
        "same_equipment_code",
        "same_manufacturer_and_model",
        "same_manufacturer_and_type",
        "same_t1_t2_t3_class",
        "same_technical_subclass",
        "same_technical_main_class",
    ]
    best: tuple[str | None, str] = (None, "technically_unrelated")
    for code in sorted(context.equipment):
        reason = category_reason(
            classify_technical_similarity(
                record.technical_tree, context.equipment[code].technical_tree
            )
        )
        if reason in order and (
            best[0] is None or order.index(reason) < order.index(best[1])
        ):
            best = (code, reason)
    return best


def evaluate_test_records(
    test_records: list[MaintenanceRecord],
    train_context: PipelineContext,
    train_result: AnalysisResult,
    mode_match_threshold: float = 0.4,
) -> EvaluationReport:
    """Associate held-out records with train-built knowledge (proxy labels)."""
    normalizer = TextNormalizer()
    similarity = TokenSetSimilarity(SimpleTokenizer())
    train_modes = {
        mode.key: mode
        for mode in train_result.failure_modes
    }
    scope_causes: dict[tuple[str, str], list[str]] = {}
    for cause in train_result.guides:
        for candidate in cause.candidate_causes:
            scope_causes.setdefault(
                (cause.equipment_code, cause.failure_mode.key), []
            ).append(normalizer.normalize(candidate.cause))
    report = EvaluationReport(
        limitations=[
            "Recorded causes are proxies, not ground truth: a miss means the "
            "recorded wording was not among the predicted candidates, not "
            "that the prediction is wrong.",
            "Test equipment is unseen by construction; association relies on "
            "technical similarity, never location.",
        ]
    )
    for record in sorted(test_records, key=lambda r: r.record_id):
        outcome = TestRecordOutcome(
            record_id=record.record_id,
            equipment_code=record.equipment_code,
            recorded_cause=(record.cause_recorded or "").strip(),
        )
        nearest, reason = _nearest_equipment(record, train_context)
        if nearest is None:
            outcome.notes.append("no technically similar train equipment")
            report.outcomes.append(outcome)
            continue
        outcome.nearest_train_equipment = nearest
        outcome.similarity_reason = reason
        report.equipment_matched += 1
        symptom = normalizer.normalize(
            record.failure_mode_recorded or record.request_description or ""
        )
        best_mode, best_score = None, 0.0
        for key, mode in sorted(train_modes.items()):
            score = similarity.similarity(symptom, normalizer.normalize(mode.canonical_label))
            if score > best_score:
                best_mode, best_score = key, score
        if best_mode is None or best_score < mode_match_threshold:
            outcome.notes.append("no train failure mode matched the symptom")
            report.outcomes.append(outcome)
            continue
        outcome.matched_mode_id = best_mode
        outcome.mode_match_score = round(best_score, 4)
        report.mode_matched += 1
        predicted = scope_causes.get((nearest, best_mode), [])
        recorded = normalizer.normalize(outcome.recorded_cause)
        if recorded and recorded in predicted:
            outcome.cause_hit = True
            report.cause_hits += 1
        else:
            outcome.notes.append("recorded cause not among predicted candidates")
        report.outcomes.append(outcome)
    report.total = len(report.outcomes)
    return report
