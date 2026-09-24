"""End-to-end: synthetic Excel → SQLite → independent reads.

Proves the whole Milestone 2 chain without the host application:

    Synthetic Excel → analyze → SQLite → open independently →
    equipment → failure modes → guide → causes → support % →
    repair actions → source evidence
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from maintenance_troubleshooting import EngineConfig, analyze_workbook
from maintenance_troubleshooting.runtime import TroubleshootingRepository
from tests.fixtures_m2 import (
    EXPECTED_START_SUPPORT_RECORDS,
    SPARSE_RECORD_ID,
    write_b104_workbook,
)


def _start_mode_id(repository: TroubleshootingRepository) -> str:
    modes = repository.list_failure_modes("B104")
    for mode in modes:
        guide = repository.get_troubleshooting_guide("B104", mode.id)
        assert guide is not None
        generated = {
            row["record_id"]
            for cause in guide.causes
            for row in cause.evidence
        }
        if "B-101" in generated:
            return mode.id
    raise AssertionError("B104 start-failure mode not found")


def _analyze_to_db(tmp_path: Path) -> Path:
    workbook = write_b104_workbook(tmp_path / "history.xlsx")
    db_path = tmp_path / "knowledge.db"
    result = analyze_workbook(
        workbook, configuration=EngineConfig.default(), output_path=db_path
    )
    assert result.database_path == str(db_path)
    assert db_path.exists()
    return db_path


def test_end_to_end_knowledge_pipeline(tmp_path: Path) -> None:
    db_path = _analyze_to_db(tmp_path)

    # The database opens independently with stdlib sqlite3 only.
    connection = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "metadata", "analysis_runs", "equipment", "maintenance_records",
            "failure_modes", "equipment_failure_modes", "candidate_causes",
            "repair_actions", "cause_repair_actions", "evidence",
            "cause_evidence", "guide_sections", "safety_notes",
        } <= tables
        version = connection.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        assert version[0] == "1"
        indexes = {
            row[1]
            for row in connection.execute("SELECT type, name FROM sqlite_master")
        }
        assert "idx_causes_scope" in indexes
        assert "idx_evidence_scope" in indexes
    finally:
        connection.close()

    with TroubleshootingRepository(db_path) as repository:
        # Equipment → failure modes.
        codes = [item.code for item in repository.list_equipment()]
        assert codes == ["B104", "B105", "H13", "M210"]
        equipment = repository.get_equipment("B104")
        assert equipment is not None
        assert equipment.manufacturer == "STARRAGHECKERT"
        assert equipment.model == "SX-051"

        mode_id = _start_mode_id(repository)
        guide = repository.get_troubleshooting_guide("B104", mode_id)
        assert guide is not None

        # Same symptom → several candidate causes, ordered by support.
        labels = [cause.label for cause in guide.causes]
        assert "خرابی منبع تغذیه" in labels
        assert "شل بودن سیم‌کشی" in labels
        assert "control-system fault" in labels
        assert "PLC startup failure" in labels
        supports = [c.support_percent for c in guide.causes if c.support_percent]
        assert supports == sorted(supports, reverse=True)

        # Misleading / unrelated knowledge must not leak into this guide.
        assert "hydraulic pump failure" not in labels
        assert not any("نشت" in label or "oil" in label.lower() for label in labels)

        # Support accounting reproduces exactly from stored evidence.
        for cause in guide.causes:
            assert cause.denominator and cause.denominator > 0
            expected = 100.0 * cause.weighted_evidence / cause.denominator
            assert cause.support_percent == expected
            assert cause.calculation_method == "similarity-weighted-share-v1"
            assert cause.evidence
            for row in cause.evidence:
                assert "same_failure_mode" in row["relevance_detail"]
        probabilities = [c.probability for c in guide.causes if c.probability]
        assert probabilities and sum(probabilities) == 1.0

        # Repair actions exist, trace to records, never cite the sparse row.
        actions = [a for cause in guide.causes for a in cause.actions]
        assert actions, "expected mined repair actions"
        cited = {
            rid
            for action in actions
            for rid in json.loads(action["source_record_ids_json"])
        }
        assert SPARSE_RECORD_ID not in cited
        assert cited <= set(EXPECTED_START_SUPPORT_RECORDS)

        # Every evidence record resolves to a stored maintenance record.
        for row in repository.list_evidence("B104", mode_id):
            assert row["symptom_text"]
            assert row["record_id"]

        # Recorded safety note is retained and linked.
        safety = repository.list_safety_notes("B104", mode_id)
        assert any("برق را قطع کنید" in note["note_text"] for note in safety)

        # Guide sections render the manufacturer-manual shape.
        kinds = [section["section"] for section in guide.sections]
        assert "symptom" in kinds and "cause" in kinds and "method" in kinds
        assert any("Historical evidence indicates" in s["body"] for s in guide.sections)
