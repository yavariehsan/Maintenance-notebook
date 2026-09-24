"""Technical-tree similarity classification (structural, not scoring)."""

from maintenance_troubleshooting.domain import TechnicalTree
from maintenance_troubleshooting.similarity import (
    TechnicalSimilarityCategory as Cat,
)
from maintenance_troubleshooting.similarity import (
    classify_technical_similarity as classify,
)


def tree(**levels: str | None) -> TechnicalTree:
    base = {"t1": None, "t2": None, "t3": None, "t4": None, "t5": None}
    base.update(levels)
    return TechnicalTree(**base)  # type: ignore[arg-type]


def test_exact_equipment_wins() -> None:
    assert classify(tree(), tree(), same_equipment_code=True) is Cat.EXACT_EQUIPMENT


def test_same_model() -> None:
    assert (
        classify(tree(t1="a", t5="m1"), tree(t1="other", t5="m1")) is Cat.SAME_MODEL
    )


def test_manufacturer_and_type_needs_both() -> None:
    both = classify(tree(t3="t", t4="m"), tree(t3="t", t4="m"))
    assert both is Cat.SAME_MANUFACTURER_AND_TYPE
    # t4 alone (without t3) must not claim the manufacturer+type category.
    only_maker = classify(tree(t4="m", t5="x"), tree(t4="m", t5="y"))
    assert only_maker is not Cat.SAME_MANUFACTURER_AND_TYPE


def test_coarser_categories() -> None:
    assert classify(tree(t3="t"), tree(t3="t")) is Cat.SAME_EQUIPMENT_TYPE
    assert classify(tree(t2="s"), tree(t2="s")) is Cat.SAME_SUBCLASS
    assert classify(tree(t1="c"), tree(t1="c")) is Cat.SAME_MAIN_CLASS


def test_unrelated_and_indeterminate() -> None:
    assert classify(tree(t1="a"), tree(t1="b")) is Cat.UNRELATED
    assert classify(TechnicalTree(), tree(t1="a")) is Cat.INDETERMINATE
    assert classify(TechnicalTree(), TechnicalTree()) is Cat.INDETERMINATE


def test_missing_levels_never_upgrade() -> None:
    # t5 agrees but only on one side being populated is impossible here;
    # t5 populated on both but different, t4+t3 agree -> manufacturer+type.
    assert (
        classify(tree(t3="t", t4="m", t5="x"), tree(t3="t", t4="m", t5="y"))
        is Cat.SAME_MANUFACTURER_AND_TYPE
    )
