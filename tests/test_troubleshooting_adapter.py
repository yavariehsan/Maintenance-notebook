"""Host integration tests for the read-only troubleshooting runtime.

Builds a small sanitized SQLite fixture through the real package
pipeline (guaranteeing schema-contract fidelity), then verifies the
thin host adapter + API boundary: configuration, health states,
read paths, precomputed-value pass-through, and read-only behavior.

The Sample-1 database is never committed; only this synthetic fixture
(excluded from git via tmp_path) is used.
"""

import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.troubleshooting_service as troubleshooting_service
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def knowledge_db(tmp_path, monkeypatch):
    """Tiny two-equipment knowledge database via the real package pipeline."""
    import openpyxl
    from maintenance_troubleshooting import EngineConfig, analyze_workbook

    headers = [
        "کد فرایندی",
        "تجهیز",
        "پیشوند درخواست",
        "شماره درخواست",
        "شرح درخواست",
        "شرح تعمیر",
        "حالت خرابی",
        "مکانیزم خرابی",
        "دلیل بروز عیب",
        "t1",
        "t2",
        "t3",
        "t4",
        "t5",
        "خطرات بالقوه/ملاحظات ایمنی/",
    ]
    tree_a = ["ماشین‌ابزار", "فرز", "فرز عمودی", "STARRAG", "SX-1"]
    tree_b = ["ماشین‌ابزار", "فرز", "فرز عمودی", "STARRAG", "SX-2"]
    rows = [
        ["B104", "mill", "B", "1", "دستگاه روشن نمی‌شود",
         "منبع تغذیه بررسی شد. منبع تغذیه تعویض شد. دستگاه تست شد.",
         "روشن نشدن", "عدم بوت PLC", "خرابی منبع تغذیه",
         *tree_a, "قبل از کار برق را قطع کنید"],
        ["B104", "mill", "B", "2", "دستگاه روشن نمی‌شود",
         "سیم‌کشی بررسی شد. کانکتور تعمیر شد.",
         "روشن نشدن", "قطعی سیم", "شل بودن سیم‌کشی",
         *tree_a, ""],
        ["B104", "mill", "B", "3", "نشتی هوا",
         "", "نشتی هوا", "خرابی اتصال", "فرسودگی",
         *tree_a, ""],
        ["M210", "mill2", "M", "1", "دستگاه روشن نمی‌شود",
         "منبع تغذیه تعویض شد.",
         "روشن نشدن", "عدم بوت PLC", "خرابی منبع تغذیه",
         *tree_b, ""],
    ]
    workbook = tmp_path / "mini.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    book.save(str(workbook))

    db_path = tmp_path / "knowledge.db"
    analyze_workbook(
        workbook, configuration=EngineConfig.default(), output_path=db_path
    )
    monkeypatch.setenv("TROUBLESHOOTING_DB_PATH", str(db_path))
    return db_path


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- configuration -----------------------------------------------------------


def test_explicit_env_path_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("TROUBLESHOOTING_DB_PATH", str(tmp_path / "custom.db"))
    assert (
        troubleshooting_service.resolve_database_path() == tmp_path / "custom.db"
    )


def test_default_path_derives_from_data_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("TROUBLESHOOTING_DB_PATH", raising=False)
    monkeypatch.setattr(troubleshooting_service, "DATA_FOLDER", str(tmp_path))
    resolved = troubleshooting_service.resolve_database_path()
    assert resolved == (
        tmp_path / "troubleshooting" / "maintenance_troubleshooting.db"
    )


# --- health states -----------------------------------------------------------


def test_status_missing_when_unconfigured(monkeypatch, tmp_path, client):
    monkeypatch.setenv("TROUBLESHOOTING_DB_PATH", str(tmp_path / "absent.db"))
    body = client.get("/api/troubleshooting/status").json()
    assert body["state"] == "missing"
    assert body["equipment_count"] is None
    # No filesystem paths leak to API consumers.
    assert "\\" not in body["message"]
    assert "absent.db" not in body["message"]


def test_status_unreadable_for_garbage_file(monkeypatch, tmp_path, client):
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"not a sqlite database")
    monkeypatch.setenv("TROUBLESHOOTING_DB_PATH", str(garbage))
    assert client.get("/api/troubleshooting/status").json()["state"] == "unreadable"


def test_status_incompatible_on_schema_mismatch(knowledge_db, monkeypatch, client):
    connection = sqlite3.connect(str(knowledge_db))
    try:
        connection.execute(
            "UPDATE metadata SET value='999' WHERE key='schema_version'"
        )
        connection.commit()
    finally:
        connection.close()
    body = client.get("/api/troubleshooting/status").json()
    assert body["state"] == "incompatible"
    assert body["schema_version"] == "999"


def test_status_available_with_counts(knowledge_db, client):
    body = client.get("/api/troubleshooting/status").json()
    assert body["state"] == "available"
    assert body["equipment_count"] == 2
    assert body["schema_version"] == body["expected_schema_version"]


def test_status_unavailable_without_engine_package(
    knowledge_db, monkeypatch, client
):
    monkeypatch.setattr(troubleshooting_service, "PACKAGE_AVAILABLE", False)
    body = client.get("/api/troubleshooting/status").json()
    assert body["state"] == "unavailable"


def test_endpoints_reject_unavailable_database(monkeypatch, tmp_path, client):
    monkeypatch.setenv("TROUBLESHOOTING_DB_PATH", str(tmp_path / "absent.db"))
    for url in (
        "/api/troubleshooting/equipment",
        "/api/troubleshooting/equipment/B104",
        "/api/troubleshooting/equipment/B104/failure-modes",
    ):
        response = client.get(url)
        assert response.status_code == 422
        assert "unavailable" in response.json()["detail"].lower()


# --- read paths --------------------------------------------------------------


def test_equipment_endpoints(knowledge_db, client):
    items = client.get("/api/troubleshooting/equipment").json()
    assert sorted(item["code"] for item in items) == ["B104", "M210"]
    item = client.get("/api/troubleshooting/equipment/B104").json()
    assert item["manufacturer"] == "STARRAG"
    assert item["record_count"] == 3
    missing = client.get("/api/troubleshooting/equipment/NOPE")
    assert missing.status_code == 404


def test_failure_mode_and_guide_endpoints(knowledge_db, client):
    modes = client.get("/api/troubleshooting/equipment/B104/failure-modes").json()
    assert len(modes) == 2
    start = next(mode for mode in modes if mode["record_count"] == 2)
    guide = client.get(
        f"/api/troubleshooting/equipment/B104/failure-modes/{start['id']}"
    ).json()
    assert guide["failure_mode_id"] == start["id"]
    assert len(guide["causes"]) >= 2
    top = guide["causes"][0]
    # Precomputed values pass through untouched, with provenance attached.
    assert top["support_percent"] is not None
    assert top["denominator"] > 0
    assert top["calculation_method"]
    assert top["evidence"], "expected source traceability"
    assert top["evidence"][0]["record_id"]
    assert guide["safety_notes"], "expected the recorded safety note"
    assert any(
        "برق را قطع کنید" in note["note_text"] for note in guide["safety_notes"]
    )
    unknown = client.get("/api/troubleshooting/equipment/B104/failure-modes/FM-9999")
    assert unknown.status_code == 404
    unknown_equipment = client.get("/api/troubleshooting/equipment/NOPE/failure-modes")
    assert unknown_equipment.status_code == 404


def test_causes_and_evidence_endpoints(knowledge_db, client):
    modes = client.get("/api/troubleshooting/equipment/B104/failure-modes").json()
    start = next(mode for mode in modes if mode["record_count"] == 2)
    causes = client.get(
        f"/api/troubleshooting/equipment/B104/failure-modes/{start['id']}/causes"
    ).json()
    assert len(causes) >= 2
    assert causes[0]["actions"], "expected mined repair actions"
    assert causes[0]["probability"] is not None
    evidence = client.get(
        f"/api/troubleshooting/equipment/B104/failure-modes/{start['id']}/evidence"
    ).json()
    assert evidence
    assert all(row["record_id"] for row in evidence)
    assert all("same_failure_mode" in row["relevance_detail"] for row in evidence)


def test_sparse_mode_flags_insufficient_evidence(knowledge_db, client):
    modes = client.get("/api/troubleshooting/equipment/B104/failure-modes").json()
    sparse = next(mode for mode in modes if mode["record_count"] == 1)
    guide = client.get(
        f"/api/troubleshooting/equipment/B104/failure-modes/{sparse['id']}"
    ).json()
    assert "insufficient_historical_repair_evidence" in guide["warnings"]


# --- read-only behavior ------------------------------------------------------


def test_runtime_reads_leave_database_untouched(knowledge_db, client):
    before = _sha256(knowledge_db)
    modes = client.get("/api/troubleshooting/equipment/B104/failure-modes").json()
    for mode in modes:
        client.get(
            f"/api/troubleshooting/equipment/B104/failure-modes/{mode['id']}"
        )
        client.get(
            f"/api/troubleshooting/equipment/B104/failure-modes/{mode['id']}/causes"
        )
        client.get(
            f"/api/troubleshooting/equipment/B104/failure-modes/{mode['id']}/evidence"
        )
    client.get("/api/troubleshooting/equipment")
    client.get("/api/troubleshooting/status")
    assert _sha256(knowledge_db) == before
    connection = sqlite3.connect(str(knowledge_db))
    try:
        tables_before = connection.execute(
            "SELECT name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    finally:
        connection.close()
    assert _sha256(knowledge_db) == before
    assert tables_before, "expected schema to remain queryable"
