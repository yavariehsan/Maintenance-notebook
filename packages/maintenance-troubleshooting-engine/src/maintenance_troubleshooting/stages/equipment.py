"""Stage 4 — EquipmentAnalyzer: records → equipment entities.

Equipment identity is the stable process code (``کد فرایندی``), always a
string. One equipment owns many records; records are never collapsed.
Technical identity (t1..t5) is a deterministic consensus: most frequent
non-blank value per level, ties broken lexicographically.
"""

from __future__ import annotations

from collections import Counter

from maintenance_troubleshooting.domain.equipment import Equipment, TechnicalTree
from maintenance_troubleshooting.domain.records import MaintenanceRecord
from maintenance_troubleshooting.stages.base import PipelineContext


def _consensus(values: list[str | None]) -> str | None:
    """Most frequent non-blank value; ties → lexicographically smallest."""
    counts = Counter(value for value in values if value and value.strip())
    if not counts:
        return None
    top = max(counts.values())
    return sorted(value for value, count in counts.items() if count == top)[0]


class EquipmentAnalyzer:
    """Group valid records by equipment code into equipment entities."""

    name = "equipment"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Build one ``Equipment`` per distinct equipment code (sorted)."""
        by_code: dict[str, list[MaintenanceRecord]] = {}
        for record in context.valid_records:
            by_code.setdefault(record.equipment_code, []).append(record)
        equipment: dict[str, Equipment] = {}
        for code in sorted(by_code):
            records = by_code[code]
            tree = TechnicalTree(
                t1=_consensus([r.technical_tree.t1 for r in records]),
                t2=_consensus([r.technical_tree.t2 for r in records]),
                t3=_consensus([r.technical_tree.t3 for r in records]),
                t4=_consensus([r.technical_tree.t4 for r in records]),
                t5=_consensus([r.technical_tree.t5 for r in records]),
            )
            equipment[code] = Equipment(
                equipment_code=code,
                main_class=tree.t1,
                sub_class=tree.t2,
                equipment_type=tree.t3,
                manufacturer=tree.t4,
                model=tree.t5,
                technical_tree=tree,
                record_count=len(records),
                name=_consensus(
                    [r.equipment_name for r in records if r.equipment_name]
                ),
            )
        context.equipment = equipment
        return context
