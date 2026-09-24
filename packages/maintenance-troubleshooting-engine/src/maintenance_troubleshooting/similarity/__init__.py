"""Technical similarity classification and scorer interfaces."""

from maintenance_troubleshooting.similarity.technical_tree import (
    TechnicalSimilarityCategory,
    TechnicalSimilarityScorer,
    classify_technical_similarity,
)

__all__ = [
    "TechnicalSimilarityCategory",
    "TechnicalSimilarityScorer",
    "classify_technical_similarity",
]
