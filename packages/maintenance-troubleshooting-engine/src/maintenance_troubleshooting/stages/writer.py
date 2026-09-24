"""Stage 11 — OutputDatabaseWriter: atomic SQLite knowledge database.

Generation is atomic: everything lands in a temporary database, integrity
is validated, and only then does the file replace the final output. A
failed run never leaves a partial production database behind.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maintenance_troubleshooting.domain.causes import (
    DEFAULT_PROBABILITY_SEMANTICS,
)
from maintenance_troubleshooting.domain.repairs import RepairAction
from maintenance_troubleshooting.domain.run import AnalysisRun
from maintenance_troubleshooting.stages.base import PipelineContext
from maintenance_troubleshooting.version import __version__ as ENGINE_VERSION

SCHEMA_VERSION = "1"

_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    engine_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    input_filename TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    equipment_count INTEGER NOT NULL,
    failure_mode_count INTEGER NOT NULL,
    cause_count INTEGER NOT NULL,
    repair_action_count INTEGER NOT NULL,
    llm_enrichment_enabled INTEGER NOT NULL,
    llm_provider TEXT,
    llm_model TEXT
);

CREATE TABLE equipment (
    code TEXT PRIMARY KEY,
    name TEXT,
    main_class TEXT,
    sub_class TEXT,
    equipment_type TEXT,
    manufacturer TEXT,
    model TEXT,
    t1 TEXT, t2 TEXT, t3 TEXT, t4 TEXT, t5 TEXT,
    record_count INTEGER NOT NULL
);

CREATE TABLE maintenance_records (
    record_id TEXT PRIMARY KEY,
    equipment_code TEXT NOT NULL,
    equipment_name TEXT,
    request_prefix TEXT,
    request_number TEXT,
    request_type TEXT,
    symptom_text TEXT,
    repair_description TEXT,
    failure_mode_recorded TEXT,
    proposed_failure_mode TEXT,
    failure_mechanism_recorded TEXT,
    cause_recorded TEXT,
    t1 TEXT, t2 TEXT, t3 TEXT, t4 TEXT, t5 TEXT,
    location_tree TEXT,
    process_tree TEXT,
    safety_notes TEXT,
    raw_json TEXT NOT NULL
);

CREATE TABLE failure_modes (
    id TEXT PRIMARY KEY,
    canonical_label TEXT NOT NULL,
    normalized_label TEXT NOT NULL,
    enriched_label TEXT,
    aliases_json TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE equipment_failure_modes (
    equipment_code TEXT NOT NULL REFERENCES equipment(code),
    failure_mode_id TEXT NOT NULL REFERENCES failure_modes(id),
    record_ids_json TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    PRIMARY KEY (equipment_code, failure_mode_id)
);

CREATE TABLE candidate_causes (
    id TEXT PRIMARY KEY,
    equipment_code TEXT NOT NULL REFERENCES equipment(code),
    failure_mode_id TEXT NOT NULL REFERENCES failure_modes(id),
    cause_label TEXT NOT NULL,
    kinds_json TEXT NOT NULL,
    support_percent REAL,
    evidence_count INTEGER NOT NULL,
    weighted_evidence REAL NOT NULL,
    denominator REAL NOT NULL,
    calculation_method TEXT NOT NULL,
    similarity_score REAL,
    similarity_basis TEXT,
    confidence_value REAL,
    confidence_basis TEXT,
    probability REAL,
    rank INTEGER NOT NULL
);

CREATE TABLE repair_actions (
    id TEXT PRIMARY KEY,
    equipment_code TEXT NOT NULL REFERENCES equipment(code),
    failure_mode_id TEXT NOT NULL REFERENCES failure_modes(id),
    category TEXT NOT NULL,
    role TEXT NOT NULL,
    action_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    source_record_ids_json TEXT NOT NULL,
    frequency INTEGER NOT NULL
);

CREATE TABLE cause_repair_actions (
    cause_id TEXT NOT NULL REFERENCES candidate_causes(id),
    repair_action_id TEXT NOT NULL REFERENCES repair_actions(id),
    PRIMARY KEY (cause_id, repair_action_id)
);

CREATE TABLE evidence (
    id TEXT PRIMARY KEY,
    scope_equipment TEXT NOT NULL,
    scope_failure_mode TEXT NOT NULL,
    record_id TEXT NOT NULL REFERENCES maintenance_records(record_id),
    equipment_code TEXT NOT NULL,
    relevance_basis TEXT NOT NULL,
    relevance_detail TEXT NOT NULL,
    weight REAL NOT NULL
);

CREATE TABLE cause_evidence (
    cause_id TEXT NOT NULL REFERENCES candidate_causes(id),
    evidence_id TEXT NOT NULL REFERENCES evidence(id),
    PRIMARY KEY (cause_id, evidence_id)
);

CREATE TABLE guide_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_code TEXT NOT NULL,
    failure_mode_id TEXT NOT NULL,
    section TEXT NOT NULL,
    title TEXT NOT NULL,
    position INTEGER NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE safety_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_code TEXT NOT NULL,
    failure_mode_id TEXT NOT NULL,
    cause_ids_json TEXT NOT NULL,
    note_text TEXT NOT NULL,
    source_record_ids_json TEXT NOT NULL
);

CREATE INDEX idx_records_equipment ON maintenance_records(equipment_code);
CREATE INDEX idx_efm_equipment ON equipment_failure_modes(equipment_code);
CREATE INDEX idx_causes_scope ON candidate_causes(equipment_code, failure_mode_id);
CREATE INDEX idx_actions_scope ON repair_actions(equipment_code, failure_mode_id);
CREATE INDEX idx_evidence_scope ON evidence(scope_equipment, scope_failure_mode);
CREATE INDEX idx_evidence_record ON evidence(record_id);
CREATE INDEX idx_sections_scope ON guide_sections(equipment_code, failure_mode_id);
CREATE INDEX idx_safety_scope ON safety_notes(equipment_code, failure_mode_id);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_seconds(started_at: str, completed_at: str) -> float:
    """Wall-clock duration between two ISO timestamps (never negative)."""
    try:
        delta = datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)
        return max(0.0, delta.total_seconds())
    except ValueError:
        return 0.0


class OutputDatabaseWriter:
    """Write the knowledge database atomically with integrity validation."""

    name = "output-db"

    def __init__(self, output_path: str | Path, started_at: str = "") -> None:
        self.output_path = Path(output_path)
        self.started_at = started_at or _utc_now()

    def run(self, context: PipelineContext) -> PipelineContext:
        """Generate tmp DB → validate → atomic replace → record run."""
        tmp_path = self.output_path.with_name(
            f"{self.output_path.name}.tmp-{os.getpid()}"
        )
        if tmp_path.exists():
            tmp_path.unlink()
        try:
            self._write(tmp_path, context)
            self._validate(tmp_path, context)
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_path, self.output_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        context.run = self._run_record(context)
        return context

    def _run_record(self, context: PipelineContext) -> AnalysisRun:
        completed = _utc_now()
        duration = _duration_seconds(self.started_at, completed)
        return AnalysisRun(
            engine_version=ENGINE_VERSION,
            schema_version=SCHEMA_VERSION,
            started_at=self.started_at,
            completed_at=completed,
            duration_seconds=duration,
            input_filename=Path(context.input_path).name,
            input_hash=context.input_hash,
            record_count=len(context.records),
            equipment_count=len(context.equipment),
            failure_mode_count=len(context.failure_modes),
            cause_count=len(context.causes),
            repair_action_count=len(context.repair_actions),
            llm_enrichment_enabled=context.enrichment_provider != "none",
            llm_provider=context.enrichment_provider,
            llm_model=context.enrichment_model,
        )

    def _write(self, tmp_path: Path, context: PipelineContext) -> None:
        connection = sqlite3.connect(str(tmp_path))
        try:
            connection.executescript(_DDL)
            self._insert_metadata(connection, context)
            self._insert_equipment(connection, context)
            self._insert_records(connection, context)
            self._insert_modes(connection, context)
            self._insert_causes(connection, context)
            self._insert_actions(connection, context)
            self._insert_evidence(connection, context)
            self._insert_sections(connection, context)
            self._insert_safety(connection, context)
            self._insert_run(connection, context)
            connection.commit()
        finally:
            connection.close()

    def _insert_metadata(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        rows = [
            ("schema_version", SCHEMA_VERSION),
            ("engine_version", ENGINE_VERSION),
            ("probability_semantics", DEFAULT_PROBABILITY_SEMANTICS),
            ("support_method", context.config.scoring.support_method),
            ("input_filename", Path(context.input_path).name),
            ("input_hash", context.input_hash),
        ]
        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)", rows
        )

    def _insert_equipment(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        rows = [
            (
                code,
                entity.name,
                entity.main_class,
                entity.sub_class,
                entity.equipment_type,
                entity.manufacturer,
                entity.model,
                entity.technical_tree.t1,
                entity.technical_tree.t2,
                entity.technical_tree.t3,
                entity.technical_tree.t4,
                entity.technical_tree.t5,
                entity.record_count,
            )
            for code, entity in sorted(context.equipment.items())
        ]
        connection.executemany(
            """INSERT INTO equipment (code, name, main_class, sub_class,
               equipment_type, manufacturer, model, t1, t2, t3, t4, t5,
               record_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )

    def _insert_records(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        rows = [
            (
                record.record_id,
                record.equipment_code,
                record.equipment_name,
                record.request_prefix,
                record.request_number,
                record.request_type,
                record.request_description,
                record.repair_description,
                record.failure_mode_recorded,
                record.proposed_failure_mode,
                record.failure_mechanism_recorded,
                record.cause_recorded,
                record.technical_tree.t1,
                record.technical_tree.t2,
                record.technical_tree.t3,
                record.technical_tree.t4,
                record.technical_tree.t5,
                record.location_tree,
                record.process_tree,
                record.safety_notes,
                json.dumps(record.raw, ensure_ascii=False, default=str),
            )
            for record in sorted(context.records, key=lambda r: r.record_id)
        ]
        connection.executemany(
            """INSERT INTO maintenance_records (record_id, equipment_code,
               equipment_name, request_prefix, request_number, request_type,
               symptom_text, repair_description, failure_mode_recorded,
               proposed_failure_mode, failure_mechanism_recorded,
               cause_recorded, t1, t2, t3, t4, t5, location_tree,
               process_tree, safety_notes, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )

    def _insert_modes(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        mode_rows = []
        scope_rows = []
        for key in sorted(context.failure_modes):
            mode = context.failure_modes[key]
            mode_rows.append(
                (
                    key,
                    mode.canonical_label,
                    mode.normalized_label,
                    mode.enriched_label,
                    json.dumps(mode.aliases, ensure_ascii=False),
                    len(mode.record_ids),
                    mode.status,
                )
            )
        connection.executemany(
            """INSERT INTO failure_modes (id, canonical_label,
               normalized_label, enriched_label, aliases_json, record_count,
               status) VALUES (?,?,?,?,?,?,?)""",
            mode_rows,
        )
        by_scope: dict[tuple[str, str], list[str]] = {}
        for record in context.valid_records:
            mode_id = context.record_failure_mode.get(record.record_id)
            if mode_id:
                by_scope.setdefault((record.equipment_code, mode_id), []).append(
                    record.record_id
                )
        for (equipment_code, mode_id), record_ids in sorted(by_scope.items()):
            unique = sorted(set(record_ids))
            scope_rows.append(
                (
                    equipment_code,
                    mode_id,
                    json.dumps(unique, ensure_ascii=False),
                    len(unique),
                )
            )
        connection.executemany(
            """INSERT INTO equipment_failure_modes (equipment_code,
               failure_mode_id, record_ids_json, record_count)
               VALUES (?,?,?,?)""",
            scope_rows,
        )

    def _insert_causes(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        rows = []
        for cause in sorted(context.causes, key=lambda c: c.cause_id):
            peak = max(
                cause.supporting_evidence, key=lambda item: item.weight, default=None
            )
            rows.append(
                (
                    cause.cause_id,
                    cause.equipment_code,
                    cause.failure_mode_id,
                    cause.cause,
                    json.dumps(cause.kinds, ensure_ascii=False),
                    cause.support_percent,
                    cause.evidence_count,
                    cause.weighted_evidence,
                    cause.denominator,
                    cause.calculation_method,
                    cause.similarity_score,
                    peak.relevance_detail if peak else None,
                    cause.confidence.value if cause.confidence else None,
                    cause.confidence.basis if cause.confidence else None,
                    cause.probability.probability if cause.probability else None,
                    cause.rank,
                )
            )
        connection.executemany(
            """INSERT INTO candidate_causes (id, equipment_code,
               failure_mode_id, cause_label, kinds_json, support_percent,
               evidence_count, weighted_evidence, denominator,
               calculation_method, similarity_score, similarity_basis,
               confidence_value, confidence_basis, probability, rank)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )

    def _insert_actions(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        rows = [
            (
                action.action_id,
                action.equipment_code,
                action.failure_mode_id,
                action.category.value,
                action.role.value,
                action.action_text,
                action.normalized_text,
                json.dumps(action.source_record_ids, ensure_ascii=False),
                action.frequency,
            )
            for action in sorted(context.repair_actions, key=lambda a: a.action_id)
        ]
        connection.executemany(
            """INSERT INTO repair_actions (id, equipment_code, failure_mode_id,
               category, role, action_text, normalized_text,
               source_record_ids_json, frequency)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        links = sorted(set(context.cause_repair_links))
        connection.executemany(
            "INSERT INTO cause_repair_actions (cause_id, repair_action_id) VALUES (?, ?)",
            links,
        )

    def _insert_evidence(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        rows = [
            (
                item.evidence_id,
                item.scope_equipment,
                item.scope_failure_mode,
                item.record_id,
                item.equipment_code,
                item.relevance_basis.value,
                item.relevance_detail,
                item.weight,
            )
            for item in sorted(context.evidence, key=lambda item: item.evidence_id)
        ]
        connection.executemany(
            """INSERT INTO evidence (id, scope_equipment, scope_failure_mode,
               record_id, equipment_code, relevance_basis, relevance_detail,
               weight) VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
        links: set[tuple[str, str]] = set()
        for cause in context.causes:
            if not cause.cause_id:
                continue
            for item in cause.supporting_evidence:
                links.add((cause.cause_id, item.evidence_id))
        connection.executemany(
            "INSERT INTO cause_evidence (cause_id, evidence_id) VALUES (?, ?)",
            sorted(links),
        )

    def _insert_sections(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        actions_by_text: dict[tuple[str, str, str], RepairAction] = {}
        for action in context.repair_actions:
            actions_by_text.setdefault(
                (action.equipment_code, action.failure_mode_id, action.action_text),
                action,
            )
        position = 0
        rows: list[tuple[Any, ...]] = []
        for guide in sorted(
            context.guides, key=lambda g: (g.equipment_code, g.failure_mode.key)
        ):
            equipment_code = guide.equipment_code
            mode_id = guide.failure_mode.key
            rows.append(
                (
                    equipment_code, mode_id, "symptom",
                    f"Observed failure: {guide.failure_mode.label}", position,
                    f"Historical evidence indicates the following symptom was "
                    f"observed for equipment {equipment_code}: "
                    f"{guide.symptom_summary}",
                )
            )
            position += 1
            for cause in guide.candidate_causes:
                action_lines = []
                for text in cause.recommended_actions:
                    linked_action: RepairAction | None = actions_by_text.get(
                        (equipment_code, mode_id, text)
                    )
                    tag = linked_action.role.value if linked_action else "suggested"
                    action_lines.append(f"- [{tag}] {text}")
                evidence_ids = sorted(item.evidence_id for item in cause.supporting_evidence)
                body = (
                    f"Historical evidence indicates '{cause.cause}' with "
                    f"{cause.support_percent:.1f}% historical support "
                    f"({cause.evidence_count} records, method "
                    f"{cause.calculation_method}).\n"
                )
                if action_lines:
                    body += "How to investigate / repair:\n" + "\n".join(action_lines) + "\n"
                body += f"Historical evidence: {', '.join(evidence_ids)}"
                rows.append(
                    (
                        equipment_code, mode_id, "cause",
                        f"Candidate cause {cause.rank}: {cause.cause}", position, body,
                    )
                )
                position += 1
            safety = [
                note
                for note in context.safety_notes
                if note["equipment_code"] == equipment_code
                and note["failure_mode_id"] == mode_id
            ]
            if safety:
                lines = [f"- {note['note_text']}" for note in safety]
                rows.append(
                    (
                        equipment_code, mode_id, "safety",
                        "Recorded safety notes", position,
                        "Historical records note the following safety "
                        "considerations (recorded, not invented):\n" + "\n".join(lines),
                    )
                )
                position += 1
            rows.append(
                (
                    equipment_code, mode_id, "method",
                    "How these numbers were produced", position,
                    f"Support percentages are shares of similarity-weighted "
                    f"evidence ({guide.probability_semantics})",
                )
            )
            position += 1
        connection.executemany(
            """INSERT INTO guide_sections (equipment_code, failure_mode_id,
               section, title, position, body) VALUES (?,?,?,?,?,?)""",
            rows,
        )

    def _insert_safety(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        rows = [
            (
                note["equipment_code"],
                note["failure_mode_id"],
                json.dumps(note["cause_ids"], ensure_ascii=False),
                note["note_text"],
                json.dumps(note["source_record_ids"], ensure_ascii=False),
            )
            for note in sorted(
                context.safety_notes,
                key=lambda n: (n["equipment_code"], n["failure_mode_id"], n["note_text"]),
            )
        ]
        connection.executemany(
            """INSERT INTO safety_notes (equipment_code, failure_mode_id,
               cause_ids_json, note_text, source_record_ids_json)
               VALUES (?,?,?,?,?)""",
            rows,
        )

    def _insert_run(self, connection: sqlite3.Connection, context: PipelineContext) -> None:
        run = self._run_record(context)
        connection.execute(
            """INSERT INTO analysis_runs (started_at, completed_at,
               duration_seconds, engine_version, schema_version,
               input_filename, input_hash, record_count, equipment_count,
               failure_mode_count, cause_count, repair_action_count,
               llm_enrichment_enabled, llm_provider, llm_model)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run.started_at,
                run.completed_at,
                run.duration_seconds,
                run.engine_version,
                run.schema_version,
                run.input_filename,
                run.input_hash,
                run.record_count,
                run.equipment_count,
                run.failure_mode_count,
                run.cause_count,
                run.repair_action_count,
                int(run.llm_enrichment_enabled),
                run.llm_provider,
                run.llm_model,
            ),
        )

    def _validate(self, tmp_path: Path, context: PipelineContext) -> None:
        """Integrity validation before atomic finalization."""
        connection = sqlite3.connect(str(tmp_path))
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError(f"SQLite integrity check failed: {integrity}")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            required = {
                "metadata", "analysis_runs", "equipment", "maintenance_records",
                "failure_modes", "equipment_failure_modes", "candidate_causes",
                "repair_actions", "cause_repair_actions", "evidence",
                "cause_evidence", "guide_sections", "safety_notes",
            }
            missing = required - tables
            if missing:
                raise ValueError(f"missing tables: {sorted(missing)}")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise ValueError(f"foreign key violations: {violations}")
            counts = {
                "equipment": len(context.equipment),
                "maintenance_records": len(context.records),
                "failure_modes": len(context.failure_modes),
                "candidate_causes": len(context.causes),
                "repair_actions": len(context.repair_actions),
                "evidence": len(context.evidence),
            }
            for table, expected in counts.items():
                actual = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if actual != expected:
                    raise ValueError(
                        f"table {table}: expected {expected} rows, found {actual}"
                    )
            version = connection.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()
            if not version or version[0] != SCHEMA_VERSION:
                raise ValueError("schema version metadata missing or wrong")
        finally:
            connection.close()
