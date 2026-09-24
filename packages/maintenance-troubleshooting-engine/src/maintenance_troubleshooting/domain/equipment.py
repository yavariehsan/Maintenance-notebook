"""Equipment identity and technical-tree representation.

The technical tree (t1..t5) is the primary basis for equipment similarity.
Physical location and production-process location are deliberately absent:
they are context, never similarity evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Core technical hierarchy levels (stable identity).
TECHNICAL_LEVEL_NAMES: tuple[str, ...] = ("t1", "t2", "t3", "t4", "t5")

#: Additional workbook levels, retained but not similarity dimensions.
EXTRA_LEVEL_NAMES: tuple[str, ...] = tuple(f"t{i}" for i in range(6, 12))


@dataclass
class TechnicalTree:
    """Stable technical identity of an equipment.

    Conceptual hierarchy (workbook values preserved verbatim)::

        t1  main equipment class
          → t2  sub class
              → t3  equipment type
                  → t4  manufacturer
                      → t5  model

    Missing levels are ``None``. Structural comparison lives in
    :mod:`maintenance_troubleshooting.similarity`; this model only carries
    the values.
    """

    t1: str | None = None
    t2: str | None = None
    t3: str | None = None
    t4: str | None = None
    t5: str | None = None
    extra_levels: dict[str, str] = field(default_factory=dict)

    def levels(self) -> tuple[str | None, str | None, str | None, str | None, str | None]:
        """Return the (t1..t5) values in hierarchy order."""
        return (self.t1, self.t2, self.t3, self.t4, self.t5)

    def depth(self) -> int:
        """Number of populated core levels."""
        return sum(1 for level in self.levels() if level)

    def is_empty(self) -> bool:
        """Whether no core level is populated."""
        return self.depth() == 0

    @classmethod
    def from_mapping(cls, values: dict[str, str | None]) -> TechnicalTree:
        """Build a tree from a ``{level_name: value}`` mapping.

        Blank values become ``None``; ``t6``..``t11`` land in
        ``extra_levels``; unknown keys are ignored (callers keep them in
        the record ``raw`` payload).
        """
        normalized = {k.strip().lower(): v for k, v in values.items()}
        core = {}
        for name in TECHNICAL_LEVEL_NAMES:
            raw = normalized.get(name)
            text = str(raw).strip() if raw is not None else ""
            core[name] = text or None
        extra = {}
        for name in EXTRA_LEVEL_NAMES:
            raw = normalized.get(name)
            text = str(raw).strip() if raw is not None else ""
            if text:
                extra[name] = text
        return cls(extra_levels=extra, **core)


@dataclass
class Equipment:
    """Stable equipment identity plus technical identity.

    ``equipment_code`` is the stable identifier (e.g. ``"B104"``). There
    are intentionally no location/process fields: two machines in the same
    workshop are not similar unless their technical trees agree.
    """

    equipment_code: str
    main_class: str | None = None
    sub_class: str | None = None
    equipment_type: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    technical_tree: TechnicalTree = field(default_factory=TechnicalTree)

    def identity_key(self) -> str:
        """Stable identity key: the exact equipment code."""
        return self.equipment_code
