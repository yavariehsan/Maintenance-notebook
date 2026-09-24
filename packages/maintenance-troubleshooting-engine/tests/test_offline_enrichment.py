"""Determinism, offline operation, and enrichment-boundary tests."""

from __future__ import annotations

import os
import socket
import sqlite3
from pathlib import Path

import pytest

from maintenance_troubleshooting import (
    EngineConfig,
    FakeKnowledgeEnrichmentProvider,
    analyze_workbook,
)
from maintenance_troubleshooting.runtime import TroubleshootingRepository
from tests.fixtures_m2 import write_b104_workbook

_COMPARE_TABLES = (
    "equipment",
    "maintenance_records",
    "failure_modes",
    "equipment_failure_modes",
    "candidate_causes",
    "repair_actions",
    "cause_repair_actions",
    "evidence",
    "cause_evidence",
    "guide_sections",
    "safety_notes",
)


def _dump(db_path: Path) -> dict[str, list[tuple]]:
    connection = sqlite3.connect(str(db_path))
    try:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in _COMPARE_TABLES
        }
    finally:
        connection.close()


def test_deterministic_pipeline_produces_stable_databases(tmp_path: Path) -> None:
    """Identical input + config + version → identical mined artifacts."""
    workbook = write_b104_workbook(tmp_path / "history.xlsx")
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    analyze_workbook(workbook, configuration=EngineConfig.default(), output_path=first)
    analyze_workbook(workbook, configuration=EngineConfig.default(), output_path=second)
    assert _dump(first) == _dump(second)


@pytest.fixture
def offline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block network use and LLM credentials for the offline test."""

    def _blocked(*args: object, **kwargs: object) -> object:
        raise RuntimeError("network disabled in offline test")

    monkeypatch.setattr(socket, "socket", _blocked)
    for key in list(os.environ):
        if "KEY" in key.upper() or "TOKEN" in key.upper() or "LLM" in key.upper():
            monkeypatch.delenv(key, raising=False)


def test_offline_default_pipeline_needs_no_network_or_llm(
    tmp_path: Path, offline_environment: None
) -> None:
    """Mandatory: default deterministic analysis works fully offline."""
    workbook = write_b104_workbook(tmp_path / "history.xlsx")
    db_path = tmp_path / "offline.db"
    result = analyze_workbook(
        workbook, configuration=EngineConfig.default(), output_path=db_path
    )
    assert db_path.exists()
    assert len(result.guides) > 0
    assert result.run is not None
    assert result.run.llm_enrichment_enabled is False
    with TroubleshootingRepository(db_path) as repository:
        assert len(repository.list_equipment()) == 4


def test_fake_enrichment_flows_through_validation_to_sqlite(tmp_path: Path) -> None:
    """provider → structured enrichment → validation → synthesis → SQLite."""
    workbook = write_b104_workbook(tmp_path / "history.xlsx")
    db_path = tmp_path / "enriched.db"
    result = analyze_workbook(
        workbook,
        configuration=EngineConfig.default(),
        output_path=db_path,
        enrichment=FakeKnowledgeEnrichmentProvider(),
    )
    assert result.run is not None
    assert result.run.llm_enrichment_enabled is True
    assert result.run.llm_provider == "fake"
    assert any("unknown record IDs" in warning for warning in result.warnings), (
        "ghost suggestion must be rejected with a warning"
    )
    with TroubleshootingRepository(db_path) as repository:
        modes = repository.list_failure_modes("B104")
        assert modes, "enriched run must still produce guides"
        connection = sqlite3.connect(str(db_path))
        try:
            enriched = connection.execute(
                "SELECT COUNT(*) FROM failure_modes WHERE enriched_label IS NOT NULL"
            ).fetchone()[0]
            inferred = connection.execute(
                "SELECT COUNT(*) FROM candidate_causes "
                "WHERE kinds_json LIKE '%historically_inferred%'"
            ).fetchone()[0]
        finally:
            connection.close()
        assert enriched > 0
        assert inferred > 0
