"""Record identity strategies.

A unique maintenance request identifier is constructed from the request
prefix + request number (e.g. ``BR-1042``). The format is a strategy, not
an assumption: alternative workbooks can plug in their own scheme while
the original prefix/number fields are always preserved on the record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class RecordIdStrategy(Protocol):
    """Build a stable record ID from request identity components."""

    @property
    def name(self) -> str: ...

    def build_id(self, prefix: str | None, number: str | None) -> str:
        """Return the record ID; raise ``ValueError`` when unbuildable."""
        ...


@dataclass(frozen=True)
class PrefixNumberRecordId:
    """Default strategy: ``{prefix}{separator}{number}``."""

    separator: str = "-"

    @property
    def name(self) -> str:
        return "prefix-number"

    def build_id(self, prefix: str | None, number: str | None) -> str:
        """Join cleaned prefix and number; blank components are an error."""
        clean_prefix = (prefix or "").strip()
        clean_number = (number or "").strip()
        if not clean_prefix or not clean_number:
            raise ValueError(
                "record ID needs both a request prefix and a request number"
            )
        return f"{clean_prefix}{self.separator}{clean_number}"
