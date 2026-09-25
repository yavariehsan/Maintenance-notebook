"""Read-only runtime guarantees for the generated knowledge database.

- ``read_only=True`` opens SQLite with ``mode=ro``: writes fail, the file
  is never created, locked for writing, or modified by reads.
- A missing database raises before any connection exists.
- The exported schema-version constant matches generated databases.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from maintenance_troubleshooting import (
    TROUBLESHOOTING_SCHEMA_VERSION,
    EngineConfig,
    analyze_workbook,
)
from maintenance_troubleshooting.runtime import TroubleshootingRepository
from tests.fixtures_m2 import write_b104_workbook


def _analyze_to_db(tmp_path: Path) -> Path:
    workbook = write_b104_workbook(tmp_path / "history.xlsx")
    db_path = tmp_path / "knowledge.db"
    analyze_workbook(
        workbook, configuration=EngineConfig.default(), output_path=db_path
    )
    return db_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_only_mode_serves_reads_but_rejects_writes(tmp_path: Path) -> None:
    db_path = _analyze_to_db(tmp_path)
    before = _sha256(db_path)
    with TroubleshootingRepository(db_path, read_only=True) as repository:
        assert repository.list_equipment(), "expected equipment rows"
        with pytest.raises(sqlite3.OperationalError):
            repository._connection.execute("CREATE TABLE probe (id INTEGER)")
    assert _sha256(db_path) == before


def test_read_only_mode_never_creates_a_missing_database(tmp_path: Path) -> None:
    missing = tmp_path / "absent.db"
    with pytest.raises(FileNotFoundError):
        TroubleshootingRepository(missing, read_only=True)
    assert not missing.exists()


def test_exported_schema_version_matches_generated_databases(
    tmp_path: Path,
) -> None:
    db_path = _analyze_to_db(tmp_path)
    with TroubleshootingRepository(db_path, read_only=True) as repository:
        assert repository.metadata()["schema_version"] == TROUBLESHOOTING_SCHEMA_VERSION
