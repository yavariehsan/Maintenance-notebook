"""Tests for the repair-report collection + analysis workflow (Milestone 6).

Covers, with mocked SurrealDB persistence (``repo_query`` seam):
upload validation, listing, detail, 10-row preview, analysis state
transitions, duplicate/concurrent protection, failure bookkeeping, and
no-leakage of storage paths.

Plus engine-level integration (real package pipeline, tmp files only):
multi-file aggregate determinism, record-ID namespacing, and the full
chain aggregate → engine → Troubleshooting DB → runtime adapter reads.

The real ``Sample-1.xlsx`` is never used here; only tiny synthetic
fixtures built in tmp directories.
"""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api import repair_report_service as reports
from api.main import app

HEADERS = [
    "کد فرایندی",
    "تجهیز",
    "پیشوند درخواست",
    "شماره درخواست",
    "شرح درخواست",
    "شرح تعمیر",
    "حالت خرابی",
    "مکانیزم خرابی",
    "دلیل بروز عیب",
]


def _workbook_bytes(rows, headers=None):
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(headers or HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _row(cells):
    full = list(cells) + [""] * (len(HEADERS) - len(cells))
    return full[: len(HEADERS)]


def _sample_rows(prefix="B", start=1, count=3, code="B104"):
    return [
        _row(
            [
                code,
                "mill",
                prefix,
                str(start + i),
                f"عیب شماره {start + i}",
                f"تعمیر انجام شد {start + i}. قطعه تعویض شد.",
                "روشن نشدن",
                "عدم بوت",
                "خرابی منبع تغذیه",
            ]
        )
        for i in range(count)
    ]


@pytest.fixture
def client():
    return TestClient(app)


def _report_row(**overrides):
    row = {
        "id": "repair_report:abc123",
        "filename": "cmms.xlsx",
        "stored_filename": "cmms.xlsx",
        "size_bytes": 1234,
        "sheet": "Sheet1",
        "column_count": 9,
        "data_rows": 3,
        "analysis_key": "a3f9c2e1",
        "analysis_state": "not_analyzed",
        "last_run_id": None,
        "last_completed_run_id": None,
        "last_error": None,
        "created": "2026-09-26T00:00:00",
        "updated": "2026-09-26T00:00:00",
    }
    row.update(overrides)
    return row


def _run_row(**overrides):
    row = {
        "id": "repair_analysis_run:run1",
        "report_ids": ["repair_report:abc123"],
        "manifest": [],
        "status": "queued",
        "command_id": None,
        "error": None,
        "record_count": None,
        "equipment_count": None,
        "failure_mode_count": None,
        "guide_count": None,
        "created": "2026-09-26T00:00:00",
        "started_at": None,
        "finished_at": None,
    }
    row.update(overrides)
    return row


def _repo_router(state):
    """Route repo_query calls to canned responses for router-level tests."""

    async def _repo(query, params=None):
        if query.startswith("CREATE repair_report"):
            return [state.get("created", _report_row())]
        if "FROM repair_report ORDER BY" in query:
            return state.get("reports", [_report_row()])
        if "FROM repair_report WHERE" in query:
            found = state.get("report")
            return [found] if found else []
        if query.startswith("CREATE repair_analysis_run"):
            return [_run_row()]
        if "FROM repair_analysis_run" in query and "WHERE" not in query:
            return state.get("runs", [])
        if "FROM repair_analysis_run WHERE" in query:
            return state.get("runs", [])
        if "FROM command" in query:
            return state.get("commands", [])
        if query.startswith("UPDATE"):
            return []
        raise AssertionError(f"unexpected query: {query}")

    return _repo


# --- upload -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_registers_report(client, tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "REPAIR_REPORTS_FOLDER", str(tmp_path))
    content = _workbook_bytes(_sample_rows(count=2))
    with patch.object(
        reports, "repo_query", new_callable=AsyncMock
    ) as mock_repo:
        mock_repo.side_effect = _repo_router(
            {"created": _report_row(data_rows=2, column_count=9)}
        )
        resp = client.post(
            "/api/repair-reports",
            files={
                "file": (
                    "cmms.xlsx",
                    content,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "cmms.xlsx"
    assert body["analysis_state"] == "not_analyzed"
    assert body["data_rows"] == 2
    assert "stored_filename" not in body
    assert "repair-reports" not in resp.text
    assert "/data/" not in resp.text and "E:\\" not in resp.text


def test_upload_rejects_non_excel(client):
    resp = client.post(
        "/api/repair-reports",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_rejects_empty_file(client):
    resp = client.post(
        "/api/repair-reports",
        files={"file": ("empty.xlsx", b"", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_upload_rejects_unreadable_workbook(client):
    resp = client.post(
        "/api/repair-reports",
        files={"file": ("junk.xlsx", b"not a workbook", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_upload_rejects_headerless_workbook(client):
    import openpyxl

    book = openpyxl.Workbook()
    buffer = BytesIO()
    book.save(buffer)
    resp = client.post(
        "/api/repair-reports",
        files={"file": ("blank.xlsx", buffer.getvalue(), "application/octet-stream")},
    )
    assert resp.status_code == 400


# --- list / detail -----------------------------------------------------------


@pytest.mark.asyncio
async def test_list_reports(client):
    with patch.object(
        reports, "repo_query", new_callable=AsyncMock
    ) as mock_repo:
        mock_repo.side_effect = _repo_router(
            {"reports": [_report_row(), _report_row(id="repair_report:def456")]}
        )
        resp = client.get("/api/repair-reports")
    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()] == [
        "repair_report:abc123",
        "repair_report:def456",
    ]


@pytest.mark.asyncio
async def test_get_report_detail_unknown(client):
    with patch.object(
        reports, "repo_query", new_callable=AsyncMock
    ) as mock_repo:
        mock_repo.side_effect = _repo_router({"report": None})
        resp = client.get("/api/repair-reports/repair_report:missing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_report_detail_includes_last_run(client):
    run = _run_row(status="completed")
    with patch.object(
        reports, "repo_query", new_callable=AsyncMock
    ) as mock_repo:
        mock_repo.side_effect = _repo_router(
            {
                "report": _report_row(
                    analysis_state="completed",
                    last_run_id="repair_analysis_run:run1",
                ),
                "runs": [run],
            }
        )
        # Detail looks up the run by id; route both run queries at it.
        resp = client.get("/api/repair-reports/repair_report:abc123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report"]["analysis_state"] == "completed"
    assert body["last_run"]["id"] == "repair_analysis_run:run1"
    assert body["last_run"]["status"] == "completed"


# --- preview ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_ten_rows(tmp_path, monkeypatch, client):
    content = _workbook_bytes(_sample_rows(count=12))
    monkeypatch.setattr(reports, "REPAIR_REPORTS_FOLDER", str(tmp_path))
    stored = tmp_path / "cmms.xlsx"
    stored.write_bytes(content)
    with patch.object(
        reports, "repo_query", new_callable=AsyncMock
    ) as mock_repo:
        mock_repo.side_effect = _repo_router({"report": _report_row()})
        resp = client.get("/api/repair-reports/repair_report:abc123/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["columns"][:4] == HEADERS[:4]
    assert len(body["rows"]) == 10
    assert body["total_data_rows"] == 12
    assert body["truncated"] is True
    # Persian text survives; empty cells are null-friendly.
    assert "عیب شماره 1" in body["rows"][0][4]


@pytest.mark.asyncio
async def test_preview_short_file_not_truncated(tmp_path, monkeypatch, client):
    content = _workbook_bytes(_sample_rows(count=3))
    monkeypatch.setattr(reports, "REPAIR_REPORTS_FOLDER", str(tmp_path))
    (tmp_path / "cmms.xlsx").write_bytes(content)
    with patch.object(
        reports, "repo_query", new_callable=AsyncMock
    ) as mock_repo:
        mock_repo.side_effect = _repo_router({"report": _report_row()})
        resp = client.get("/api/repair-reports/repair_report:abc123/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["rows"]) == 3
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_preview_unknown_report(client):
    with patch.object(
        reports, "repo_query", new_callable=AsyncMock
    ) as mock_repo:
        mock_repo.side_effect = _repo_router({"report": None})
        resp = client.get("/api/repair-reports/repair_report:missing/preview")
    assert resp.status_code == 404


# --- analysis lifecycle --------------------------------------------------------


@pytest.mark.asyncio
async def test_start_analysis_empty_collection(client):
    with patch.object(
        reports, "repo_query", new_callable=AsyncMock
    ) as mock_repo:
        mock_repo.side_effect = _repo_router({"reports": [], "runs": []})
        resp = client.post("/api/repair-reports/analyze")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_start_analysis_rejects_concurrent_run(client):
    active = _run_row(status="processing", command_id="command:live")
    with patch.object(
        reports, "repo_query", new_callable=AsyncMock
    ) as mock_repo:
        mock_repo.side_effect = _repo_router(
            {
                "reports": [_report_row()],
                "runs": [active],
                "commands": [{"status": "running"}],
            }
        )
        resp = client.post("/api/repair-reports/analyze")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_start_analysis_submits_command_and_queues(client):
    updates = []

    async def _repo(query, params=None):
        if "FROM repair_analysis_run" in query:
            return []
        if "FROM repair_report ORDER BY" in query:
            return [_report_row(), _report_row(id="repair_report:def456")]
        if query.startswith("CREATE repair_analysis_run"):
            return [_run_row()]
        if query.startswith("UPDATE"):
            updates.append((query, params))
            return []
        raise AssertionError(f"unexpected query: {query}")

    with (
        patch.object(reports, "repo_query", new_callable=AsyncMock) as mock_repo,
        patch(
            "api.command_service.CommandService.submit_command_job",
            new=AsyncMock(return_value="command:job1"),
        ),
    ):
        mock_repo.side_effect = _repo
        resp = client.post("/api/repair-reports/analyze")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run"]["command_id"] == "command:job1"
    assert body["run"]["report_ids"] == [
        "repair_report:abc123",
        "repair_report:def456",
    ]
    queued = [
        params
        for query, params in updates
        if "analysis_state" in query and params.get("state") == "queued"
    ]
    assert len(queued) == 2


@pytest.mark.asyncio
async def test_stale_run_self_heals_and_unblocks():
    """A run whose worker died is finalized; the next analyze may proceed."""
    stale = _run_row(status="processing", command_id="command:dead")
    seen_updates = []

    async def _repo(query, params=None):
        if "FROM repair_analysis_run" in query:
            return [stale]
        if "FROM command" in query:
            return [{"status": "failed"}]
        if query.startswith("UPDATE"):
            seen_updates.append(query)
            return []
        if "FROM repair_report WHERE" in query:
            return [_report_row(analysis_state="processing")]
        raise AssertionError(f"unexpected query: {query}")

    with patch.object(reports, "repo_query", new_callable=AsyncMock) as mock_repo:
        mock_repo.side_effect = _repo
        assert await reports.get_active_run() is None
    assert any("finished_at" in query for query in seen_updates)


# --- aggregate builder (pure, no DB) --------------------------------------------


def test_aggregate_namespaces_record_ids(tmp_path):
    file_a = tmp_path / "a.xlsx"
    file_b = tmp_path / "b.xlsx"
    file_a.write_bytes(_workbook_bytes(_sample_rows(prefix="B", start=1, count=2)))
    # Same natural IDs as file A: without namespacing these would collide.
    file_b.write_bytes(_workbook_bytes(_sample_rows(prefix="B", start=1, count=2)))
    dest = tmp_path / "aggregate.xlsx"
    manifest = reports.build_aggregate_workbook(
        [
            {
                "report_id": "repair_report:aaa",
                "filename": "a.xlsx",
                "analysis_key": "11111111",
                "path": str(file_a),
            },
            {
                "report_id": "repair_report:bbb",
                "filename": "b.xlsx",
                "analysis_key": "22222222",
                "path": str(file_b),
            },
        ],
        dest,
    )
    assert [entry["report_id"] for entry in manifest] == [
        "repair_report:aaa",
        "repair_report:bbb",
    ]
    assert manifest[0]["row_count"] == 2
    assert manifest[0]["first_row"] == 2
    assert manifest[1]["first_row"] == 4

    import openpyxl

    book = openpyxl.load_workbook(str(dest), read_only=True, data_only=True)
    sheet = book.active
    rows = list(sheet.iter_rows(values_only=True))
    headers = list(rows[0])
    prefix_pos = headers.index("پیشوند درخواست")
    prefixes = [row[prefix_pos] for row in rows[1:]]
    assert prefixes == ["11111111-B", "11111111-B", "22222222-B", "22222222-B"]
    book.close()


def test_namespaced_prefix_preserves_empty_cells():
    assert reports._namespaced_prefix("aa", None) is None
    assert reports._namespaced_prefix("aa", "  ") is None
    assert reports._namespaced_prefix("aa", "BR") == "aa-BR"
    assert reports._namespaced_prefix("aa", 210) == "aa-210"


# --- end-to-end chain (real engine, tmp only) ------------------------------------


def test_chain_aggregate_engine_runtime(tmp_path, monkeypatch):
    """upload bytes → aggregate → engine → runtime adapter reads."""
    from maintenance_troubleshooting import EngineConfig, analyze_workbook

    import api.troubleshooting_service as troubleshooting_service

    file_a = tmp_path / "a.xlsx"
    file_b = tmp_path / "b.xlsx"
    file_a.write_bytes(_workbook_bytes(_sample_rows(prefix="B", start=1, count=3)))
    file_b.write_bytes(_workbook_bytes(_sample_rows(prefix="M", start=1, count=3)))

    dest = tmp_path / "aggregate.xlsx"
    reports.build_aggregate_workbook(
        [
            {
                "report_id": "repair_report:aaa",
                "filename": "a.xlsx",
                "analysis_key": "11111111",
                "path": str(file_a),
            },
            {
                "report_id": "repair_report:bbb",
                "filename": "b.xlsx",
                "analysis_key": "22222222",
                "path": str(file_b),
            },
        ],
        dest,
    )
    db_path = tmp_path / "knowledge.db"
    result = analyze_workbook(
        dest, configuration=EngineConfig.default(), output_path=db_path
    )
    assert len(result.records) == 6
    record_ids = [record.record_id for record in result.records]
    assert len(set(record_ids)) == 6
    assert any(rid.startswith("11111111-") for rid in record_ids)
    assert any(rid.startswith("22222222-") for rid in record_ids)

    monkeypatch.setenv("TROUBLESHOOTING_DB_PATH", str(db_path))
    status = troubleshooting_service.get_status()
    assert status["state"] == "available"
    equipment = troubleshooting_service.list_equipment()
    assert {item["code"] for item in equipment} == {"B104"}
    modes = troubleshooting_service.list_failure_modes("B104")
    assert len(modes) >= 1
    guide = troubleshooting_service.get_guide("B104", modes[0]["id"])
    assert guide["causes"], "expected mined causes"
    evidence_ids = [
        row["record_id"]
        for cause in guide["causes"]
        for row in cause["evidence"]
    ]
    assert evidence_ids, "expected provenance on causes"
    assert any(
        rid.startswith(("11111111-", "22222222-")) for rid in evidence_ids
    ), "evidence must trace to namespaced source records"
