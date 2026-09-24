"""Technical-tree similarity as a first-class, structural concept.

Classification (which structural relationship holds) is separated from
scoring (how much support that relationship contributes). The categories
below document the intended strength order, but mapping them to numbers is
a separate, testable decision owned by a future ranker — not this module.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from maintenance_troubleshooting.domain.equipment import TechnicalTree


class TechnicalSimilarityCategory(str, Enum):
    """Structural relationship between two technical trees."""

    EXACT_EQUIPMENT = "exact_equipment"
    SAME_MODEL = "same_model"
    SAME_MANUFACTURER_AND_TYPE = "same_manufacturer_and_type"
    SAME_EQUIPMENT_TYPE = "same_equipment_type"
    SAME_SUBCLASS = "same_subclass"
    SAME_MAIN_CLASS = "same_main_class"
    UNRELATED = "unrelated"
    INDETERMINATE = "indeterminate"  # no comparable level populated


def _present(value: str | None) -> bool:
    return bool(value and value.strip())


def classify_technical_similarity(
    first: TechnicalTree,
    second: TechnicalTree,
    same_equipment_code: bool = False,
) -> TechnicalSimilarityCategory:
    """Classify the structural relationship between two technical trees.

    Only populated levels on *both* sides are compared. A relationship is
    claimed at the finest level where both sides agree; missing levels can
    only yield a coarser category or ``INDETERMINATE`` — never an upgrade.
    """
    if same_equipment_code:
        return TechnicalSimilarityCategory.EXACT_EQUIPMENT

    a = [level.strip() if level else None for level in first.levels()]
    b = [level.strip() if level else None for level in second.levels()]

    def agree(index: int) -> bool:
        return (
            _present(a[index]) and _present(b[index]) and a[index] == b[index]
        )

    if agree(4):
        return TechnicalSimilarityCategory.SAME_MODEL
    if agree(3) and agree(2):
        return TechnicalSimilarityCategory.SAME_MANUFACTURER_AND_TYPE
    if agree(2):
        return TechnicalSimilarityCategory.SAME_EQUIPMENT_TYPE
    if agree(1):
        return TechnicalSimilarityCategory.SAME_SUBCLASS
    if agree(0):
        return TechnicalSimilarityCategory.SAME_MAIN_CLASS
    if first.is_empty() or second.is_empty():
        return TechnicalSimilarityCategory.INDETERMINATE
    return TechnicalSimilarityCategory.UNRELATED


class TechnicalSimilarityScorer(Protocol):
    """Future numeric support derived from technical-tree overlap.

    Implementations return a support weight in [0, 1] and must document
    their method. The weight is evidence support, not a probability.
    """

    @property
    def name(self) -> str: ...

    def score(
        self,
        first: TechnicalTree,
        second: TechnicalTree,
        same_equipment_code: bool = False,
    ) -> float: ...

    def describe(self) -> str: ...
