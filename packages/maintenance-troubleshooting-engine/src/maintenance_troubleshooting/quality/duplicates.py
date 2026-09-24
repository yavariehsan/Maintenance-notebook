"""Duplicate detection over stable record identifiers."""

from __future__ import annotations

from dataclasses import dataclass

from maintenance_troubleshooting.domain.records import MaintenanceRecord
from maintenance_troubleshooting.quality.models import DuplicateGroup


@dataclass
class DuplicateDetector:
    """Group records sharing one record ID.

    Duplicate request rows are common in maintenance exports (re-opened or
    re-logged requests). Detection reports groups; downstream stages decide
    how to treat them — nothing is merged or dropped here.
    """

    case_sensitive: bool = True

    def _key(self, record_id: str) -> str:
        return record_id if self.case_sensitive else record_id.lower()

    def find_duplicates(
        self, records: list[MaintenanceRecord], row_numbers: list[int] | None = None
    ) -> list[DuplicateGroup]:
        """Return one group per record ID seen more than once."""
        positions = row_numbers if row_numbers is not None else list(range(len(records)))
        buckets: dict[str, DuplicateGroup] = {}
        for record, position in zip(records, positions):
            key = self._key(record.record_id)
            group = buckets.setdefault(key, DuplicateGroup(key=key))
            group.record_ids.append(record.record_id)
            group.row_numbers.append(position)
        return [group for group in buckets.values() if len(group.record_ids) > 1]
