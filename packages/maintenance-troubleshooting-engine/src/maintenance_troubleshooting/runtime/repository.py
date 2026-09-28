"""Read-only runtime repository over a generated knowledge database.

This is the future UI boundary: indexed SQLite queries only. No mining,
no text processing, no similarity computation, no LLM — the batch phase
already materialized everything this layer returns.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EquipmentSummary:
    """Equipment row with its failure-mode count."""

    code: str
    name: str | None
    manufacturer: str | None
    model: str | None
    record_count: int
    failure_mode_count: int = 0


@dataclass(frozen=True)
class FailureModeSummary:
    """Failure mode of one equipment with guide statistics."""

    id: str
    label: str
    record_count: int
    cause_count: int = 0


@dataclass(frozen=True)
class CauseView:
    """Candidate cause with support accounting and linked actions/evidence."""

    id: str
    label: str
    kinds: list[str]
    support_percent: float | None
    evidence_count: int
    weighted_evidence: float
    denominator: float
    calculation_method: str
    similarity_score: float | None
    similarity_basis: str | None
    confidence: float | None
    probability: float | None
    rank: int
    actions: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class GuideView:
    """Assembled troubleshooting guide (precomputed sections + tables)."""

    equipment_code: str
    failure_mode_id: str
    failure_mode_label: str
    symptom_summary: str
    causes: list[CauseView] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    safety_notes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verifications: list[dict[str, Any]] = field(default_factory=list)
    post_repair_events: list[dict[str, Any]] = field(default_factory=list)


def _synthesize_for_stored_action(
    action_text: str, category: str, secondary_categories_json: Any
) -> str | None:
    """Deterministic guide instruction for a stored action row.

    Read-path fallback for databases that predate the stored
    ``guide_instruction`` column: runs the same pure M11C-6R2 rule over
    the stored verbatim text. Returns ``None`` outside the approved
    shape; never raises (a malformed row simply has no instruction).
    """
    try:
        from maintenance_troubleshooting.stages.guide_instructions import (
            synthesize_guide_instruction,
        )
        from maintenance_troubleshooting.text import SimpleTokenizer

        try:
            secondary = (
                json.loads(secondary_categories_json)
                if isinstance(secondary_categories_json, str)
                else []
            )
        except (ValueError, TypeError):
            secondary = []
        if not isinstance(secondary, list):
            secondary = []
        tokens = SimpleTokenizer().tokenize(action_text.lower())
        return synthesize_guide_instruction(
            action_text,
            tokens,
            primary_is_replace=(category == "replace"),
            has_adjust=("adjust" in secondary),
        )
    except Exception:
        return None


class TroubleshootingRepository:
    """Read-only access to a generated troubleshooting database."""

    def __init__(self, database_path: str | Path, *, read_only: bool = False) -> None:
        self.database_path = Path(database_path)
        if not self.database_path.exists():
            raise FileNotFoundError(f"knowledge database not found: {database_path}")
        if read_only:
            # URI mode=ro: the file is never created, locked for writing, or
            # modified. Host runtimes must use this mode.
            uri = self.database_path.absolute().as_posix()
            self._connection = sqlite3.connect(f"file:{uri}?mode=ro", uri=True)
        else:
            self._connection = sqlite3.connect(str(self.database_path))
        self._connection.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the underlying read connection."""
        self._connection.close()

    def __enter__(self) -> TroubleshootingRepository:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def metadata(self) -> dict[str, str]:
        """Database metadata (schema/engine versions, input hash, ...)."""
        return {
            row["key"]: row["value"]
            for row in self._connection.execute("SELECT key, value FROM metadata")
        }

    def list_equipment(self) -> list[EquipmentSummary]:
        """All equipment with record and failure-mode counts (indexed)."""
        rows = self._connection.execute(
            """SELECT e.code, e.name, e.manufacturer, e.model, e.record_count,
                      COUNT(DISTINCT efm.failure_mode_id) AS modes
               FROM equipment e
               LEFT JOIN equipment_failure_modes efm ON efm.equipment_code = e.code
               GROUP BY e.code ORDER BY e.code"""
        ).fetchall()
        return [
            EquipmentSummary(
                code=row["code"],
                name=row["name"],
                manufacturer=row["manufacturer"],
                model=row["model"],
                record_count=row["record_count"],
                failure_mode_count=row["modes"],
            )
            for row in rows
        ]

    def get_equipment(self, code: str) -> EquipmentSummary | None:
        """One equipment by code, or ``None``."""
        for equipment in self.list_equipment():
            if equipment.code == code:
                return equipment
        return None

    def list_failure_modes(self, equipment_code: str) -> list[FailureModeSummary]:
        """Failure modes of one equipment with cause counts."""
        rows = self._connection.execute(
            """SELECT efm.failure_mode_id AS id, fm.canonical_label AS label,
                      efm.record_count,
                      COUNT(DISTINCT cc.id) AS causes
               FROM equipment_failure_modes efm
               JOIN failure_modes fm ON fm.id = efm.failure_mode_id
               LEFT JOIN candidate_causes cc
                 ON cc.equipment_code = efm.equipment_code
                AND cc.failure_mode_id = efm.failure_mode_id
               WHERE efm.equipment_code = ?
               GROUP BY efm.failure_mode_id ORDER BY efm.failure_mode_id""",
            (equipment_code,),
        ).fetchall()
        return [
            FailureModeSummary(
                id=row["id"],
                label=row["label"],
                record_count=row["record_count"],
                cause_count=row["causes"],
            )
            for row in rows
        ]

    def list_candidate_causes(
        self, equipment_code: str, failure_mode_id: str
    ) -> list[CauseView]:
        """Ranked candidate causes with actions and evidence attached."""
        rows = self._connection.execute(
            """SELECT * FROM candidate_causes
               WHERE equipment_code = ? AND failure_mode_id = ?
               ORDER BY rank""",
            (equipment_code, failure_mode_id),
        ).fetchall()
        return [self._cause_view(dict(row)) for row in rows]

    def _cause_view(self, row: dict[str, Any]) -> CauseView:
        try:
            actions = self._connection.execute(
                """SELECT ra.id, ra.category, ra.role, ra.action_text,
                          ra.secondary_categories_json, ra.source_record_ids_json,
                          ra.frequency, ra.guide_instruction
                   FROM cause_repair_actions cra
                   JOIN repair_actions ra ON ra.id = cra.repair_action_id
                   WHERE cra.cause_id = ?
                   ORDER BY ra.frequency DESC, ra.action_text""",
                (row["id"],),
            ).fetchall()
        except sqlite3.Error:
            # Databases generated before the guide_instruction column
            # (M11C-6R2 Part B) predate it: read without it and derive
            # the instruction deterministically below.
            actions = self._connection.execute(
                """SELECT ra.id, ra.category, ra.role, ra.action_text,
                          ra.secondary_categories_json, ra.source_record_ids_json,
                          ra.frequency
                   FROM cause_repair_actions cra
                   JOIN repair_actions ra ON ra.id = cra.repair_action_id
                   WHERE cra.cause_id = ?
                   ORDER BY ra.frequency DESC, ra.action_text""",
                (row["id"],),
            ).fetchall()
        evidence = self._connection.execute(
            """SELECT e.id, e.record_id, e.equipment_code, e.relevance_basis,
                      e.relevance_detail, e.weight, mr.symptom_text,
                      mr.repair_description
               FROM cause_evidence ce
               JOIN evidence e ON e.id = ce.evidence_id
               JOIN maintenance_records mr ON mr.record_id = e.record_id
               WHERE ce.cause_id = ?
               ORDER BY e.weight DESC, e.id""",
            (row["id"],),
        ).fetchall()
        return CauseView(
            id=row["id"],
            label=row["cause_label"],
            kinds=json.loads(row["kinds_json"]),
            support_percent=row["support_percent"],
            evidence_count=row["evidence_count"],
            weighted_evidence=row["weighted_evidence"],
            denominator=row["denominator"],
            calculation_method=row["calculation_method"],
            similarity_score=row["similarity_score"],
            similarity_basis=row["similarity_basis"],
            confidence=row["confidence_value"],
            probability=row["probability"],
            rank=row["rank"],
            actions=[self._action_view(dict(action)) for action in actions],
            evidence=[dict(item) for item in evidence],
        )

    @staticmethod
    def _action_view(action: dict[str, Any]) -> dict[str, Any]:
        """Action row → view dict with guide instruction resolved.

        Prefers the stored ``guide_instruction`` (M11C-6R2 Part B); when
        the database predates the column or the value is NULL, derives it
        deterministically from the stored action text with the same pure
        rule — never invented, ``None`` outside the approved shape.
        """
        if action.get("guide_instruction") is None:
            action["guide_instruction"] = _synthesize_for_stored_action(
                str(action.get("action_text") or ""),
                str(action.get("category") or ""),
                action.get("secondary_categories_json"),
            )
        return action

    def list_evidence(
        self, equipment_code: str, failure_mode_id: str
    ) -> list[dict[str, Any]]:
        """All scope evidence with source record excerpts."""
        rows = self._connection.execute(
            """SELECT e.*, mr.symptom_text, mr.repair_description
               FROM evidence e
               JOIN maintenance_records mr ON mr.record_id = e.record_id
               WHERE e.scope_equipment = ? AND e.scope_failure_mode = ?
               ORDER BY e.weight DESC, e.id""",
            (equipment_code, failure_mode_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_safety_notes(
        self, equipment_code: str, failure_mode_id: str
    ) -> list[dict[str, Any]]:
        """Recorded safety notes for a scope (never invented)."""
        rows = self._connection.execute(
            """SELECT * FROM safety_notes
               WHERE equipment_code = ? AND failure_mode_id = ?
               ORDER BY id""",
            (equipment_code, failure_mode_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_technical_verifications(
        self, equipment_code: str, failure_mode_id: str
    ) -> list[dict[str, Any]]:
        """Verification steps attested for a scope (M11C D4)."""
        rows = self._connection.execute(
            """SELECT * FROM guide_verifications
               WHERE equipment_code = ? AND failure_mode_id = ?
               ORDER BY id""",
            (equipment_code, failure_mode_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_post_repair_events(
        self, equipment_code: str, failure_mode_id: str
    ) -> list[dict[str, Any]]:
        """Handover/outcome events attested for a scope (M11C D5)."""
        rows = self._connection.execute(
            """SELECT * FROM guide_post_repair_events
               WHERE equipment_code = ? AND failure_mode_id = ?
               ORDER BY id""",
            (equipment_code, failure_mode_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_troubleshooting_guide(
        self, equipment_code: str, failure_mode_id: str
    ) -> GuideView | None:
        """Assemble the full guide from precomputed rows (reads only)."""
        modes = {
            mode.id: mode for mode in self.list_failure_modes(equipment_code)
        }
        mode = modes.get(failure_mode_id)
        if mode is None:
            return None
        sections = self._connection.execute(
            """SELECT section, title, position, body FROM guide_sections
               WHERE equipment_code = ? AND failure_mode_id = ?
               ORDER BY position""",
            (equipment_code, failure_mode_id),
        ).fetchall()
        causes = self.list_candidate_causes(equipment_code, failure_mode_id)
        safety = self.list_safety_notes(equipment_code, failure_mode_id)
        verifications = self.list_technical_verifications(
            equipment_code, failure_mode_id
        )
        events = self.list_post_repair_events(equipment_code, failure_mode_id)
        return GuideView(
            equipment_code=equipment_code,
            failure_mode_id=failure_mode_id,
            failure_mode_label=mode.label,
            symptom_summary=next(
                (
                    section["body"]
                    for section in sections
                    if section["section"] == "symptom"
                ),
                mode.label,
            ),
            causes=causes,
            sections=[dict(section) for section in sections],
            safety_notes=safety,
            warnings=(
                ["insufficient_historical_repair_evidence"]
                if not any(cause.actions for cause in causes)
                else []
            ),
            verifications=verifications,
            post_repair_events=events,
        )
