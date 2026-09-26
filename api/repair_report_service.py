"""Repair-report collection service (گزارشات تعمیر).

Owns the raw maintenance/repair-history workbooks uploaded by users and the
analysis runs that turn them into the precomputed Troubleshooting Database:

- ``repair_report`` records: one per uploaded ``.xlsx`` file (raw input
  artifact; the file itself stays on disk under ``REPAIR_REPORTS_FOLDER``
  and is never modified).
- ``repair_analysis_run`` records: one per knowledge-generation run. Every
  run snapshots the full report collection and regenerates the runtime
  database from all of it, so analyzing a newly uploaded file never
  silently discards previously generated knowledge.

Analysis itself runs in the background worker
(``commands/repair_report_commands.py``) through the existing
surreal-commands infrastructure and the standalone
``maintenance-troubleshooting-engine`` package. This module never mines,
clusters, or scores anything — it only stores files, builds the
deterministic aggregate workbook, and tracks states.

All SurrealDB access goes through ``repo_query`` (single mock seam).
Filesystem paths never leave this module: API responses carry the report
``id`` and original ``filename`` only.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from openpyxl import load_workbook

from open_notebook.config import REPAIR_REPORTS_FOLDER
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.exceptions import InvalidInputError, NotFoundError

TABLE_REPORT = "repair_report"
TABLE_RUN = "repair_analysis_run"

ANALYZE_COMMAND_NAME = "analyze_repair_reports"

#: Report analysis states surfaced to the UI.
STATE_NOT_ANALYZED = "not_analyzed"
STATE_QUEUED = "queued"
STATE_PROCESSING = "processing"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"

ACTIVE_REPORT_STATES = (STATE_QUEUED, STATE_PROCESSING)

#: Run lifecycle states.
RUN_QUEUED = "queued"
RUN_PROCESSING = "processing"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"

ACTIVE_RUN_STATUSES = (RUN_QUEUED, RUN_PROCESSING)

#: surreal-commands job statuses that mean "still working".
ACTIVE_COMMAND_STATUSES = ("new", "queued", "running")

#: Preview contract: column names + at most this many data rows.
PREVIEW_ROW_LIMIT = 10

#: Longest cell text returned by the preview (wide-column safety).
PREVIEW_CELL_LIMIT = 2000

#: Canonical request-prefix header in the default engine column mapping.
#: The aggregate builder namespaces this column per source file so record
#: IDs stay unique across files (engine PK: maintenance_records.record_id).
REQUEST_PREFIX_HEADER = "پیشوند درخواست"


# --- storage ---------------------------------------------------------------


def _storage_dir() -> Path:
    folder = Path(REPAIR_REPORTS_FOLDER)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def generate_unique_filename(original_filename: str) -> str:
    """Atomically reserve a unique name under the repair-reports folder.

    Mirrors ``api/routers/sources.py::generate_unique_filename`` (basename
    strip, path-traversal guard, O_EXCL claim) without importing the router
    layer into this service.
    """
    folder = _storage_dir()
    safe_filename = os.path.basename(original_filename)
    if not safe_filename:
        raise ValueError("Invalid filename")
    stem = Path(safe_filename).stem
    suffix = Path(safe_filename).suffix
    safe_root = folder.resolve()
    counter = 0
    while True:
        candidate = safe_filename if counter == 0 else f"{stem} ({counter}){suffix}"
        full_path = folder / candidate
        resolved = full_path.resolve()
        if not str(resolved).startswith(str(safe_root) + os.sep):
            raise ValueError("Invalid filename: path traversal detected")
        try:
            resolved.touch(exist_ok=False)
            return str(resolved)
        except FileExistsError:
            counter += 1


def _write_file_sync(file_path: str, content: bytes) -> None:
    try:
        with open(file_path, "wb") as handle:
            handle.write(content)
    except Exception:
        if os.path.exists(file_path):
            os.unlink(file_path)
        raise


def stored_path(report: Dict[str, Any]) -> Path:
    """Resolve the on-disk workbook for a report record (server-side only)."""
    return _storage_dir() / str(report["stored_filename"])


# --- workbook reading ------------------------------------------------------


def _format_cell(value: Any) -> Any:
    """JSON-safe cell formatting for the 10-row preview.

    Dates become ISO strings, numbers pass through untouched, text is
    preserved verbatim (Persian/English) with a length cap, and empty
    cells become ``None``. Never runs the engine.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    if not text.strip():
        return None
    return text if len(text) <= PREVIEW_CELL_LIMIT else text[:PREVIEW_CELL_LIMIT] + "…"


def _open_sheet(content: bytes) -> tuple[Any, str]:
    """Open the active sheet of a workbook byte payload (read-only)."""
    try:
        workbook = load_workbook(
            BytesIO(content), read_only=True, data_only=True
        )
    except Exception as e:
        raise InvalidInputError(
            "The uploaded file is not a readable Excel workbook."
        ) from e
    try:
        sheet = workbook.active
        if sheet is None:
            raise InvalidInputError("The workbook has no readable worksheet.")
        title = str(sheet.title)
        rows = list(sheet.iter_rows(values_only=True))
        return rows, title
    finally:
        workbook.close()


def scan_workbook(content: bytes) -> Dict[str, Any]:
    """Validate + summarize an uploaded workbook (no engine involved)."""
    if not content:
        raise InvalidInputError("The uploaded file is empty.")
    rows, sheet = _open_sheet(content)
    if not rows:
        raise InvalidInputError("The workbook has no header row.")
    headers = [
        str(cell).strip() if cell is not None else "" for cell in rows[0]
    ]
    if not any(headers):
        raise InvalidInputError("The workbook has no header row.")
    data_rows = sum(
        1
        for row in rows[1:]
        if any(
            cell is not None and not (isinstance(cell, str) and not cell.strip())
            for cell in row
        )
    )
    if data_rows == 0:
        raise InvalidInputError("The workbook contains no data rows.")
    return {
        "sheet": sheet,
        "column_count": len(headers),
        "data_rows": data_rows,
    }


def preview_workbook(content: bytes, limit: int = PREVIEW_ROW_LIMIT) -> Dict[str, Any]:
    """Column names + up to ``limit`` non-empty data rows for the محتوا tab."""
    rows, sheet = _open_sheet(content)
    headers = [
        str(cell).strip() if cell is not None else "" for cell in rows[0]
    ]
    preview: List[List[Any]] = []
    total = 0
    for row in rows[1:]:
        cells = [_format_cell(cell) for cell in row]
        # Pad short rows / trim ragged rows to the header width.
        if len(cells) < len(headers):
            cells.extend([None] * (len(headers) - len(cells)))
        else:
            cells = cells[: len(headers)]
        if all(cell is None for cell in cells):
            continue
        total += 1
        if len(preview) < limit:
            preview.append(cells)
    return {
        "sheet": sheet,
        "columns": headers,
        "rows": preview,
        "total_data_rows": total,
        "truncated": total > len(preview),
    }


# --- report records --------------------------------------------------------


def _report_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Public report shape (never exposes the storage filename/path)."""
    return {
        "id": str(row.get("id")),
        "filename": row.get("filename"),
        "size_bytes": row.get("size_bytes"),
        "sheet": row.get("sheet"),
        "column_count": row.get("column_count"),
        "data_rows": row.get("data_rows"),
        "analysis_state": row.get("analysis_state", STATE_NOT_ANALYZED),
        "last_run_id": (
            str(row.get("last_run_id")) if row.get("last_run_id") else None
        ),
        "last_error": row.get("last_error"),
        "created": str(row.get("created")) if row.get("created") else None,
        "updated": str(row.get("updated")) if row.get("updated") else None,
    }


async def create_report(filename: str, content: bytes) -> Dict[str, Any]:
    """Validate, store, and register an uploaded repair-history workbook."""
    summary = scan_workbook(content)
    file_path = await asyncio.to_thread(_write_sync_upload, filename, content)
    stored_filename = Path(file_path).name
    rows = await repo_query(
        f"CREATE {TABLE_REPORT} CONTENT {{"
        "filename: $filename, stored_filename: $stored_filename, "
        "size_bytes: $size_bytes, sheet: $sheet, column_count: $column_count, "
        "data_rows: $data_rows, analysis_key: $analysis_key, "
        "analysis_state: $analysis_state, last_run_id: NONE, "
        "last_completed_run_id: NONE, last_error: NONE, "
        "created: time::now(), updated: time::now()} RETURN AFTER",
        {
            "filename": os.path.basename(filename),
            "stored_filename": stored_filename,
            "size_bytes": len(content),
            "sheet": summary["sheet"],
            "column_count": summary["column_count"],
            "data_rows": summary["data_rows"],
            "analysis_key": secrets.token_hex(4),
            "analysis_state": STATE_NOT_ANALYZED,
        },
    )
    if not rows:
        raise RuntimeError("Failed to register repair report")
    logger.info(f"Registered repair report: {os.path.basename(filename)}")
    return _report_row(rows[0])


def _write_sync_upload(filename: str, content: bytes) -> str:
    file_path = generate_unique_filename(filename)
    _write_file_sync(file_path, content)
    return file_path


async def list_reports() -> List[Dict[str, Any]]:
    rows = await repo_query(
        f"SELECT * FROM {TABLE_REPORT} ORDER BY created DESC"
    )
    return [_report_row(row) for row in rows or []]


async def get_report(report_id: str) -> Dict[str, Any]:
    rows = await repo_query(
        f"SELECT * FROM {TABLE_REPORT} WHERE id = $rid",
        {"rid": ensure_record_id(report_id)},
    )
    if not rows:
        raise NotFoundError(f"Unknown repair report: {report_id}.")
    return _report_row(rows[0])


async def _get_report_internal(report_id: str) -> Dict[str, Any]:
    """Full internal row (includes storage + completion bookkeeping)."""
    rows = await repo_query(
        f"SELECT * FROM {TABLE_REPORT} WHERE id = $rid",
        {"rid": ensure_record_id(report_id)},
    )
    if not rows:
        raise NotFoundError(f"Unknown repair report: {report_id}.")
    return rows[0]


async def _set_report_state(
    report_id: str,
    state: str,
    run_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    await repo_query(
        f"UPDATE $rid SET analysis_state = $state, "
        "last_run_id = $run_id, last_error = $error, "
        "updated = time::now()",
        {
            "rid": ensure_record_id(report_id),
            "state": state,
            "run_id": (
                ensure_record_id(run_id) if run_id is not None else None
            ),
            "error": error,
        },
    )


async def _set_report_completed(report_id: str, run_id: str) -> None:
    await repo_query(
        "UPDATE $rid SET analysis_state = $state, last_run_id = $run_id, "
        "last_completed_run_id = $run_id, last_error = NONE, "
        "updated = time::now()",
        {
            "rid": ensure_record_id(report_id),
            "state": STATE_COMPLETED,
            "run_id": ensure_record_id(run_id),
        },
    )


async def restore_report_completed(
    report_id: str, run_id: str, completed_run_id: str
) -> None:
    """Keep a report completed after a later run failed.

    ``last_run_id`` records the latest attempt (the failed run) while
    ``last_completed_run_id`` keeps pointing at the run that produced the
    current runtime database.
    """
    await repo_query(
        "UPDATE $rid SET analysis_state = $state, last_run_id = $run_id, "
        "last_completed_run_id = $completed, last_error = NONE, "
        "updated = time::now()",
        {
            "rid": ensure_record_id(report_id),
            "state": STATE_COMPLETED,
            "run_id": ensure_record_id(run_id),
            "completed": ensure_record_id(completed_run_id),
        },
    )


async def read_report_file(report_id: str) -> bytes:
    """Raw workbook bytes for preview/analysis (server-side only)."""
    internal = await _get_report_internal(report_id)
    path = stored_path(internal)
    if not path.exists():
        raise NotFoundError(
            f"Stored file for repair report {report_id} is missing."
        )
    return await asyncio.to_thread(path.read_bytes)


# --- analysis runs ---------------------------------------------------------


def _run_row(row: Dict[str, Any]) -> Dict[str, Any]:
    def _str(value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    return {
        "id": _str(row.get("id")),
        "report_ids": [str(item) for item in row.get("report_ids") or []],
        "manifest": row.get("manifest") or [],
        "status": row.get("status", RUN_QUEUED),
        "command_id": _str(row.get("command_id")),
        "error": row.get("error"),
        "record_count": row.get("record_count"),
        "equipment_count": row.get("equipment_count"),
        "failure_mode_count": row.get("failure_mode_count"),
        "guide_count": row.get("guide_count"),
        "created": _str(row.get("created")),
        "started_at": _str(row.get("started_at")),
        "finished_at": _str(row.get("finished_at")),
    }


async def list_runs(limit: int = 20) -> List[Dict[str, Any]]:
    rows = await repo_query(
        f"SELECT * FROM {TABLE_RUN} ORDER BY created DESC LIMIT $limit",
        {"limit": limit},
    )
    return [_run_row(row) for row in rows or []]


async def get_run(run_id: str) -> Dict[str, Any]:
    rows = await repo_query(
        f"SELECT * FROM {TABLE_RUN} WHERE id = $rid",
        {"rid": ensure_record_id(run_id)},
    )
    if not rows:
        raise NotFoundError(f"Unknown analysis run: {run_id}.")
    return _run_row(rows[0])


async def _get_run_internal(run_id: str) -> Dict[str, Any]:
    rows = await repo_query(
        f"SELECT * FROM {TABLE_RUN} WHERE id = $rid",
        {"rid": ensure_record_id(run_id)},
    )
    if not rows:
        raise NotFoundError(f"Unknown analysis run: {run_id}.")
    return rows[0]


async def _command_active(command_id: Optional[str]) -> bool:
    """Whether a surreal-commands job is still working (self-healing seam).

    A missing command record means the job never materialized — not active.
    """
    if not command_id:
        return False
    try:
        rows = await repo_query(
            "SELECT status FROM command WHERE id = $cid",
            {"cid": ensure_record_id(command_id)},
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"Could not read command status for {command_id}: {e}")
        return True
    if not rows:
        return False
    return str(rows[0].get("status")) in ACTIVE_COMMAND_STATUSES


async def _finalize_stale_run(run: Dict[str, Any]) -> None:
    """Flip a run whose worker died to failed (never stuck in processing).

    Reports that already contributed to a previous successful run keep
    their completed state (the runtime DB still holds their knowledge);
    the rest return to failed so the next run can include them again.
    """
    run_id = str(run["id"])
    logger.warning(f"Finalizing stale analysis run {run_id} as failed")
    await repo_query(
        f"UPDATE $rid SET status = $status, "
        "error = $error, finished_at = time::now()",
        {
            "rid": ensure_record_id(run_id),
            "status": RUN_FAILED,
            "error": "The analysis worker stopped without completing.",
        },
    )
    for report_id in run.get("report_ids") or []:
        try:
            internal = await _get_report_internal(str(report_id))
        except NotFoundError:
            continue
        if internal.get("analysis_state") not in ACTIVE_REPORT_STATES:
            continue
        if internal.get("last_completed_run_id"):
            await restore_report_completed(
                str(report_id),
                run_id,
                str(internal["last_completed_run_id"]),
            )
        else:
            await _set_report_state(
                str(report_id),
                STATE_FAILED,
                run_id=run_id,
                error="The analysis worker stopped without completing.",
            )


async def get_active_run() -> Optional[Dict[str, Any]]:
    """Latest unfinished run, or ``None`` (stale runs are finalized first)."""
    rows = await repo_query(
        f"SELECT * FROM {TABLE_RUN} WHERE status IN $statuses "
        "ORDER BY created DESC LIMIT 1",
        {"statuses": list(ACTIVE_RUN_STATUSES)},
    )
    if not rows:
        return None
    run = rows[0]
    if await _command_active(
        str(run.get("command_id")) if run.get("command_id") else None
    ):
        return _run_row(run)
    await _finalize_stale_run(run)
    return None


async def create_run(report_ids: List[str]) -> Dict[str, Any]:
    """Snapshot the collection into a new queued run (no command yet)."""
    rows = await repo_query(
        f"CREATE {TABLE_RUN} CONTENT {{report_ids: $report_ids, "
        "manifest: [], status: $status, command_id: NONE, error: NONE, "
        "record_count: NONE, equipment_count: NONE, failure_mode_count: NONE, "
        "guide_count: NONE, created: time::now(), started_at: NONE, "
        "finished_at: NONE} RETURN AFTER",
        {
            "report_ids": [ensure_record_id(item) for item in report_ids],
            "status": RUN_QUEUED,
        },
    )
    if not rows:
        raise RuntimeError("Failed to create analysis run")
    return _run_row(rows[0])


async def attach_command(run_id: str, command_id: str) -> None:
    await repo_query(
        "UPDATE $rid SET command_id = $cid",
        {
            "rid": ensure_record_id(run_id),
            "cid": ensure_record_id(command_id),
        },
    )


async def mark_run_processing(run_id: str, manifest: List[Dict[str, Any]]) -> None:
    await repo_query(
        f"UPDATE $rid SET status = $status, manifest = $manifest, "
        "started_at = time::now()",
        {
            "rid": ensure_record_id(run_id),
            "status": RUN_PROCESSING,
            "manifest": manifest,
        },
    )


async def mark_run_completed(run_id: str, counts: Dict[str, Any]) -> None:
    await repo_query(
        f"UPDATE $rid SET status = $status, error = NONE, "
        "record_count = $records, equipment_count = $equipment, "
        "failure_mode_count = $modes, guide_count = $guides, "
        "finished_at = time::now()",
        {
            "rid": ensure_record_id(run_id),
            "status": RUN_COMPLETED,
            "records": counts.get("record_count"),
            "equipment": counts.get("equipment_count"),
            "modes": counts.get("failure_mode_count"),
            "guides": counts.get("guide_count"),
        },
    )


async def mark_run_failed(run_id: str, error: str) -> None:
    await repo_query(
        f"UPDATE $rid SET status = $status, error = $error, "
        "finished_at = time::now()",
        {
            "rid": ensure_record_id(run_id),
            "status": RUN_FAILED,
            "error": error[:500],
        },
    )


# --- aggregate workbook ----------------------------------------------------


def _namespaced_prefix(analysis_key: str, value: Any) -> Any:
    """Prefix a request-prefix cell with the stable per-file key.

    ``BR`` from report ``a3f9c2e1`` becomes ``a3f9c2e1-BR`` so the engine's
    ``{prefix}-{number}`` record IDs can never collide across files (the
    engine stores ``maintenance_records.record_id`` as PRIMARY KEY).
    Empty cells stay empty; non-string scalars are preserved verbatim.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return f"{analysis_key}-{value}"
    if isinstance(value, (int, float)):
        text = str(int(value)) if float(value).is_integer() else repr(value)
        return f"{analysis_key}-{text}"
    text = str(value).strip()
    if not text:
        return None
    return f"{analysis_key}-{text}"


def build_aggregate_workbook(
    entries: List[Dict[str, Any]], dest: Path
) -> List[Dict[str, Any]]:
    """Merge report workbooks into one deterministic batch input.

    - Files are concatenated in the given (stable) order; headers are the
      union in first-seen order so files sharing the CMMS export format
      align column-for-column.
    - The request-prefix column is namespaced per file (see
      :func:`_namespaced_prefix`); every other cell is copied verbatim.
    - Only the engine's active-sheet contract is honored: each file
      contributes its active worksheet.

    Returns the per-file manifest (report id, filename, key, source
    sheet, aggregate row range, row count) for the run record. The engine
    itself is untouched — this is plain input preparation.
    """
    from openpyxl import Workbook

    union_headers: List[str] = []
    file_blocks: List[Dict[str, Any]] = []
    for entry in entries:
        content = Path(entry["path"]).read_bytes()
        rows, sheet = _open_sheet(content)
        headers = [
            str(cell).strip() if cell is not None else "" for cell in rows[0]
        ]
        for header in headers:
            if header not in union_headers:
                union_headers.append(header)
        try:
            prefix_index = headers.index(REQUEST_PREFIX_HEADER)
        except ValueError:
            prefix_index = -1
        data: List[List[Any]] = []
        for row in rows[1:]:
            if all(
                cell is None or (isinstance(cell, str) and not cell.strip())
                for cell in row
            ):
                continue
            values = list(row[: len(headers)])
            values.extend([None] * (len(headers) - len(values)))
            if prefix_index >= 0:
                values[prefix_index] = _namespaced_prefix(
                    entry["analysis_key"], values[prefix_index]
                )
            data.append(values)
        file_blocks.append(
            {
                "report_id": entry["report_id"],
                "filename": entry["filename"],
                "analysis_key": entry["analysis_key"],
                "source_sheet": sheet,
                "headers": headers,
                "rows": data,
            }
        )

    book = Workbook(write_only=False)
    sheet = book.active
    sheet.title = "repair_reports"
    sheet.append(union_headers)
    manifest: List[Dict[str, Any]] = []
    current_row = 2  # 1-based: row 1 holds headers
    for block in file_blocks:
        index_of = {header: pos for pos, header in enumerate(block["headers"])}
        start = current_row
        for values in block["rows"]:
            aligned = [None] * len(union_headers)
            for pos, header in enumerate(union_headers):
                source_pos = index_of.get(header)
                if source_pos is not None:
                    aligned[pos] = values[source_pos]
            sheet.append(aligned)
            current_row += 1
        manifest.append(
            {
                "report_id": block["report_id"],
                "filename": block["filename"],
                "analysis_key": block["analysis_key"],
                "source_sheet": block["source_sheet"],
                "aggregate_sheet": "repair_reports",
                "first_row": start,
                "last_row": current_row - 1,
                "row_count": len(block["rows"]),
            }
        )
    book.save(str(dest))
    book.close()
    return manifest


# --- orchestration ---------------------------------------------------------


async def start_analysis() -> Dict[str, Any]:
    """Create a collection-wide analysis run and submit the worker command.

    The run snapshots every uploaded report: the generated database always
    represents the whole collection, never just the newest file. Raises a
    409-style ``InvalidInputError``-adjacent error when a run is active —
    the router maps the dedicated ``AnalysisInProgressError`` below.
    """
    from api.command_service import CommandService

    active = await get_active_run()
    if active is not None:
        raise AnalysisInProgressError(
            "An analysis run is already in progress."
        )
    reports = await list_reports()
    if not reports:
        raise InvalidInputError("No repair reports to analyze yet.")
    run = await create_run([report["id"] for report in reports])

    try:
        import commands.repair_report_commands  # noqa: F401
    except ImportError as e:
        await mark_run_failed(run["id"], f"Analysis worker unavailable: {e}")
        raise InvalidInputError("Analysis worker is unavailable.") from e

    try:
        command_id = await CommandService.submit_command_job(
            "open_notebook",
            ANALYZE_COMMAND_NAME,
            {"run_id": run["id"]},
        )
    except Exception as e:
        await mark_run_failed(run["id"], f"Failed to submit analysis: {e}")
        raise

    await attach_command(run["id"], command_id)
    for report in reports:
        await _set_report_state(
            report["id"], STATE_QUEUED, run_id=run["id"], error=None
        )
    run["command_id"] = command_id
    run["report_ids"] = [report["id"] for report in reports]
    logger.info(f"Submitted repair-report analysis run {run['id']}")
    return run


class AnalysisInProgressError(Exception):
    """A second analysis run was requested while one is still active."""
