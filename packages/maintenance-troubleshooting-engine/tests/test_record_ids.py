"""Record-ID strategy: prefix + number default, pluggable format."""

import pytest

from maintenance_troubleshooting.inputs import PrefixNumberRecordId


def test_default_strategy_joins_prefix_and_number() -> None:
    strategy = PrefixNumberRecordId()
    assert strategy.name == "prefix-number"
    assert strategy.build_id("BR", "1042") == "BR-1042"
    assert strategy.build_id("  BR ", " 1042 ") == "BR-1042"


def test_blank_components_are_errors_not_silent_ids() -> None:
    strategy = PrefixNumberRecordId()
    with pytest.raises(ValueError):
        strategy.build_id("", "1042")
    with pytest.raises(ValueError):
        strategy.build_id("BR", None)


def test_separator_is_configurable() -> None:
    assert PrefixNumberRecordId(separator="/").build_id("BR", "7") == "BR/7"
