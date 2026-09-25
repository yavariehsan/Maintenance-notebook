"""Equipment-level train/test splitting (no equipment leakage).

Rows are never split individually: one equipment's whole history goes to
either train or test, so the model cannot see the same equipment on both
sides. Splitting is deterministic for a fixed seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maintenance_troubleshooting.inputs import preserve_identifier


@dataclass(frozen=True)
class EquipmentSplit:
    """One deterministic equipment-level split."""

    train_codes: tuple[str, ...]
    test_codes: tuple[str, ...]
    test_fraction: float
    seed: int
    strategy: str = "seeded-shuffle"

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable view of the split."""
        return {
            "train_codes": list(self.train_codes),
            "test_codes": list(self.test_codes),
            "test_fraction": self.test_fraction,
            "seed": self.seed,
            "strategy": self.strategy,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EquipmentSplit:
        """Rebuild from :meth:`to_dict` output."""
        return cls(
            train_codes=tuple(payload["train_codes"]),
            test_codes=tuple(payload["test_codes"]),
            test_fraction=float(payload["test_fraction"]),
            seed=int(payload["seed"]),
            strategy=str(payload.get("strategy", "seeded-shuffle")),
        )


def split_equipment(
    codes: list[str], test_fraction: float = 0.2, seed: int = 42
) -> EquipmentSplit:
    """Split distinct equipment codes deterministically (no leakage).

    Sorted codes are shuffled with ``random.Random(seed)``; the first
    ``ceil(n * test_fraction)`` (at least one, at most n-1) become test.
    """
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be within (0, 1)")
    unique = sorted(set(codes))
    if len(unique) < 2:
        raise ValueError("need at least 2 equipment for a split")
    order = list(unique)
    random.Random(seed).shuffle(order)
    test_size = min(max(1, round(len(order) * test_fraction)), len(order) - 1)
    test = tuple(sorted(order[:test_size]))
    train = tuple(sorted(order[test_size:]))
    return EquipmentSplit(
        train_codes=train, test_codes=test, test_fraction=test_fraction, seed=seed
    )


def check_leakage(split: EquipmentSplit) -> list[str]:
    """Equipment codes present on both sides (must be empty)."""
    return sorted(set(split.train_codes) & set(split.test_codes))


def write_split_workbooks(
    input_path: str | Path,
    split: EquipmentSplit,
    train_path: str | Path,
    test_path: str | Path,
    equipment_header: str = "کد فرایندی",
) -> dict[str, int]:
    """Write train/test workbooks filtered by equipment code.

    Headers, column order, and cell values are preserved verbatim; only
    row membership changes. Returns ``{"train_rows": n, "test_rows": m}``.
    """
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("splitting workbooks requires 'openpyxl'.") from exc

    source = openpyxl.load_workbook(filename=str(input_path), read_only=True, data_only=True)
    try:
        sheet = source.active
        if sheet is None:
            raise ValueError(f"workbook '{input_path}' has no active sheet")
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        source.close()
    if not rows:
        raise ValueError("workbook has no rows")
    headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    try:
        code_index = headers.index(equipment_header)
    except ValueError as exc:
        raise ValueError(
            f"equipment column '{equipment_header}' not found in workbook"
        ) from exc

    train_set, test_set = set(split.train_codes), set(split.test_codes)

    def _code_of(row: tuple[Any, ...]) -> str | None:
        return preserve_identifier(row[code_index])

    train_rows = [row for row in rows[1:] if _code_of(row) in train_set]
    test_rows = [row for row in rows[1:] if _code_of(row) in test_set]

    def _write(path: str | Path, data_rows: list[tuple[Any, ...]]) -> None:
        book = openpyxl.Workbook()
        target = book.active
        if target is None:
            raise ValueError("cannot create workbook sheet")
        target.title = "repairs"
        target.append(headers)
        for row in data_rows:
            target.append(list(row))
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        book.save(str(target_path))

    _write(train_path, train_rows)
    _write(test_path, test_rows)
    return {"train_rows": len(train_rows), "test_rows": len(test_rows)}


@dataclass
class SplitArtifacts:
    """Split description plus row counts (for reports)."""

    split: EquipmentSplit
    train_rows: int = 0
    test_rows: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
