"""Stage 6 — SimilarityAnalyzer: equipment similarity matrix + reasons.

Weights come from ``SimilarityConfig.technical_weights`` keyed by
category name (configurable analytical hierarchy, documented in
``docs/algorithm-principles.md``). Every pair exposes its reason
(``same_equipment_code``, ``same_manufacturer_and_model``, …).
"""

from __future__ import annotations

from maintenance_troubleshooting.similarity import (
    TechnicalSimilarityCategory,
    classify_technical_similarity,
)
from maintenance_troubleshooting.stages.base import PipelineContext

_CATEGORY_REASONS = {
    TechnicalSimilarityCategory.EXACT_EQUIPMENT: "same_equipment_code",
    TechnicalSimilarityCategory.SAME_MODEL: "same_manufacturer_and_model",
    TechnicalSimilarityCategory.SAME_MANUFACTURER_AND_TYPE: "same_manufacturer_and_type",
    TechnicalSimilarityCategory.SAME_EQUIPMENT_TYPE: "same_t1_t2_t3_class",
    TechnicalSimilarityCategory.SAME_SUBCLASS: "same_technical_subclass",
    TechnicalSimilarityCategory.SAME_MAIN_CLASS: "same_technical_main_class",
    TechnicalSimilarityCategory.UNRELATED: "technically_unrelated",
    TechnicalSimilarityCategory.INDETERMINATE: "insufficient_technical_levels",
}


def category_reason(category: TechnicalSimilarityCategory) -> str:
    """Human reason for a similarity category (stored on evidence rows)."""
    return _CATEGORY_REASONS[category]


class SimilarityAnalyzer:
    """Precompute pairwise technical support weights between equipment."""

    name = "similarity"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Fill the symmetric weight/reason matrix (self-pairs = 1.0)."""
        weights_config = context.config.similarity.technical_weights
        codes = sorted(context.equipment)
        weights: dict[tuple[str, str], float] = {}
        reasons: dict[tuple[str, str], str] = {}
        for first in codes:
            for second in codes:
                if first == second:
                    weights[(first, second)] = 1.0
                    reasons[(first, second)] = "same_equipment_code"
                    continue
                category = classify_technical_similarity(
                    context.equipment[first].technical_tree,
                    context.equipment[second].technical_tree,
                )
                weight = float(weights_config.get(category.value, 0.0))
                weights[(first, second)] = weight
                reasons[(first, second)] = _CATEGORY_REASONS[category]
        context.similarity_weights = weights
        context.similarity_reasons = reasons
        return context
