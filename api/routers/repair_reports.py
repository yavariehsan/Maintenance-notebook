"""Repair-report collection API (گزارشات تعمیر).

Thin routes over ``api/repair_report_service.py``:

- upload / list / detail of raw repair-history workbooks
- 10-row workbook preview (generated safely with openpyxl, no engine)
- collection-wide + single-report analysis runs (background worker + engine)
- analysis-run history
- report-scoped actions (repair actions / verifications / events filtered
  by the report's stable analysis key — read-only, never invented)

The runtime Troubleshooting Database itself stays behind the existing
read-only ``/api/troubleshooting/*`` endpoints — nothing here exposes
filesystem paths or raw storage references.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel, Field

from api import repair_report_service as reports
from open_notebook.exceptions import InvalidInputError, NotFoundError

router = APIRouter()


class RepairReportItem(BaseModel):
    """One uploaded repair-history file with its analysis state."""

    id: str = Field(..., description="Stable report identifier")
    filename: str = Field(..., description="Original uploaded filename")
    size_bytes: Optional[int] = Field(None, description="Stored file size")
    sheet: Optional[str] = Field(None, description="Previewed worksheet")
    column_count: Optional[int] = Field(None, description="Header columns")
    data_rows: Optional[int] = Field(None, description="Non-empty data rows")
    analysis_state: str = Field(
        ..., description="not_analyzed | queued | processing | completed | failed"
    )
    last_run_id: Optional[str] = Field(
        None, description="Latest analysis run covering this report"
    )
    last_error: Optional[str] = Field(None, description="Failure reason, if any")
    created: Optional[str] = Field(None, description="Upload time")
    updated: Optional[str] = Field(None, description="Last state change")


class AnalysisRunManifestEntry(BaseModel):
    report_id: str
    filename: Optional[str] = None
    analysis_key: Optional[str] = None
    source_sheet: Optional[str] = None
    aggregate_sheet: Optional[str] = None
    first_row: Optional[int] = None
    last_row: Optional[int] = None
    row_count: Optional[int] = None


class AnalysisRunItem(BaseModel):
    """One knowledge-generation run over a report snapshot."""

    id: str
    report_ids: List[str] = Field(
        default_factory=list,
        description="Exact report set this run was generated from",
    )
    manifest: List[AnalysisRunManifestEntry] = Field(default_factory=list)
    status: str = Field(..., description="queued | processing | completed | failed")
    command_id: Optional[str] = Field(None, description="Worker job id")
    error: Optional[str] = Field(None, description="Failure reason, if any")
    record_count: Optional[int] = None
    equipment_count: Optional[int] = None
    failure_mode_count: Optional[int] = None
    guide_count: Optional[int] = None
    created: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class RepairReportDetail(BaseModel):
    report: RepairReportItem
    last_run: Optional[AnalysisRunItem] = Field(
        None, description="Latest run covering this report, if any"
    )


class PreviewResponse(BaseModel):
    """Up-to-10-row preview of the uploaded workbook (محتوا tab)."""

    sheet: str
    columns: List[str]
    rows: List[List[Any]]
    total_data_rows: int = Field(..., description="Non-empty data rows in the sheet")
    truncated: bool = Field(..., description="True when rows were cut to 10")


class StartAnalysisResponse(BaseModel):
    run: AnalysisRunItem
    message: str = Field(..., description="Human-readable acknowledgement")


class ReportActionItem(BaseModel):
    """One repair action attributable to this report (read-only)."""

    id: Optional[str] = Field(None, description="Action ID")
    category: Optional[str] = Field(None, description="Action taxonomy category")
    role: Optional[str] = Field(
        None, description="diagnostic | corrective | verification | observed_issue"
    )
    action_text: Optional[str] = Field(None, description="Original repair sentence")
    source_record_ids: List[str] = Field(
        default_factory=list, description="This report's supporting record IDs"
    )
    frequency: Optional[int] = Field(None, description="Supporting record count")
    guide_instruction: Optional[str] = Field(
        None, description="Guide-facing synthesized instruction, when approved"
    )


class ReportVerificationItem(BaseModel):
    """One verification step attested in this report's sentences."""

    id: Optional[str] = Field(None, description="Verification ID")
    record_id: Optional[str] = Field(None, description="Source record ID")
    sentence: Optional[str] = Field(None, description="Verbatim source sentence")
    event_type: Optional[str] = Field(None, description="test | outcome")
    repair_action_id: Optional[str] = Field(
        None, description="Linked repair action, when mixed"
    )


class ReportEventItem(BaseModel):
    """One handover/outcome event attested in this report's sentences."""

    id: Optional[str] = Field(None, description="Event ID")
    record_id: Optional[str] = Field(None, description="Source record ID")
    sentence: Optional[str] = Field(None, description="Verbatim source sentence")
    event_type: Optional[str] = Field(None, description="handover | outcome")
    repair_action_id: Optional[str] = Field(
        None, description="Linked repair action, when mixed"
    )


class ReportActionsResponse(BaseModel):
    """Report-scoped troubleshooting objects (never invented)."""

    report_id: str = Field(..., description="Stable report identifier")
    analysis_key: str = Field(..., description="Per-file namespacing key")
    run_id: Optional[str] = Field(
        None, description="Latest completed run backing the database"
    )
    record_ids: List[str] = Field(
        default_factory=list, description="This report's record IDs in the database"
    )
    repair_actions: List[ReportActionItem] = Field(default_factory=list)
    verifications: List[ReportVerificationItem] = Field(default_factory=list)
    post_repair_events: List[ReportEventItem] = Field(default_factory=list)
    history_only_record_ids: List[str] = Field(
        default_factory=list,
        description="Records with no mined objects (history on the record)",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Empty-state reasons, e.g. report_not_in_latest_db",
    )


@router.post("/repair-reports", response_model=RepairReportItem, status_code=201)
async def upload_repair_report(file: UploadFile = File(...)):
    """Upload a repair-history Excel workbook as a new repair report."""
    try:
        filename = (file.filename or "").strip()
        if not filename.lower().endswith((".xlsx", ".xlsm")):
            raise HTTPException(
                status_code=400,
                detail="Please upload an Excel (.xlsx) file.",
            )
        content = await file.read()
        try:
            report = await reports.create_report(filename, content)
        except InvalidInputError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return RepairReportItem(**report)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading repair report: {e}")
        raise HTTPException(
            status_code=500, detail="Error uploading repair report"
        )


@router.get("/repair-reports", response_model=List[RepairReportItem])
async def list_repair_reports():
    """List uploaded repair reports (newest first) with analysis states."""
    try:
        return [RepairReportItem(**item) for item in await reports.list_reports()]
    except Exception as e:
        logger.error(f"Error listing repair reports: {e}")
        raise HTTPException(
            status_code=500, detail="Error listing repair reports"
        )


@router.get("/repair-reports/runs", response_model=List[AnalysisRunItem])
async def list_analysis_runs(limit: int = Query(20, ge=1, le=100)):
    """List knowledge-generation runs (newest first)."""
    try:
        runs = await reports.list_runs(limit=limit)
        return [AnalysisRunItem(**run) for run in runs]
    except Exception as e:
        logger.error(f"Error listing analysis runs: {e}")
        raise HTTPException(status_code=500, detail="Error listing analysis runs")


class DeleteReportResult(BaseModel):
    """Acknowledgement for a repair-report deletion (record + file)."""

    id: str = Field(..., description="Deleted report identifier")
    deleted: bool = Field(..., description="Always true on success")


@router.delete("/repair-reports/{report_id}", response_model=DeleteReportResult)
async def delete_repair_report(report_id: str):
    """Delete one uploaded repair report by its stable record ID.

    Removes the report record and its stored workbook; run history,
    task rows, and the knowledge database are preserved. 404 for
    unknown reports, 409 while the report is being analyzed.
    """
    try:
        result = await reports.delete_report(report_id)
    except reports.AnalysisInProgressError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting repair report: {e}")
        raise HTTPException(
            status_code=500, detail="Error deleting repair report"
        )
    return DeleteReportResult(**result)


@router.get("/repair-reports/runs/{run_id}", response_model=AnalysisRunItem)
async def get_analysis_run(run_id: str):
    """One analysis run with its exact input manifest."""
    try:
        return AnalysisRunItem(**await reports.get_run(run_id))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error reading analysis run: {e}")
        raise HTTPException(status_code=500, detail="Error reading analysis run")


@router.get("/repair-reports/{report_id}", response_model=RepairReportDetail)
async def get_repair_report(report_id: str):
    """One repair report plus its latest analysis run, if any."""
    try:
        report = await reports.get_report(report_id)
        last_run: Optional[Dict[str, Any]] = None
        if report.get("last_run_id"):
            try:
                last_run = await reports.get_run(str(report["last_run_id"]))
            except NotFoundError:
                last_run = None
        return RepairReportDetail(
            report=RepairReportItem(**report),
            last_run=AnalysisRunItem(**last_run) if last_run else None,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading repair report: {e}")
        raise HTTPException(
            status_code=500, detail="Error reading repair report"
        )


@router.get(
    "/repair-reports/{report_id}/preview", response_model=PreviewResponse
)
async def preview_repair_report(report_id: str):
    """Preview column names + up to 10 data rows (never runs the engine)."""
    try:
        content = await reports.read_report_file(report_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error reading repair report file: {e}")
        raise HTTPException(
            status_code=500, detail="Error reading repair report file"
        )
    try:
        preview = await _preview_off_loop(content)
    except InvalidInputError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error previewing repair report: {e}")
        raise HTTPException(
            status_code=500, detail="Error previewing repair report"
        )
    return PreviewResponse(**preview)


async def _preview_off_loop(content: bytes) -> Dict[str, Any]:
    """Run the CPU-bound workbook scan off the event loop."""
    import asyncio

    return await asyncio.to_thread(reports.preview_workbook, content)


@router.post(
    "/repair-reports/analyze", response_model=StartAnalysisResponse
)
async def start_repair_analysis():
    """Start a collection-wide analysis run (تحلیل محتوا).

    The run regenerates the Troubleshooting Database from every uploaded
    report, so new files add knowledge without discarding previous work.
    Returns 409 while another run is active — only one
    knowledge-generation operation may replace the runtime database.

    Kept for backward compatibility; prefer
    ``POST /repair-reports/{id}/analyze`` for single-report runs with no
    implicit process-everything.
    """
    try:
        run = await reports.start_analysis()
    except reports.AnalysisInProgressError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting repair analysis: {e}")
        raise HTTPException(
            status_code=500, detail="Error starting repair analysis"
        )
    return StartAnalysisResponse(
        run=AnalysisRunItem(**run),
        message="Analysis started. The troubleshooting guide updates when it completes.",
    )


@router.post(
    "/repair-reports/{report_id}/analyze", response_model=StartAnalysisResponse
)
async def start_single_report_analysis(report_id: str):
    """Start a single-report analysis run (تحلیل محتوا for one file).

    The run snapshots exactly this report — the generated database
    represents this file alone (atomic single-writer replacement). Only
    ``not_analyzed`` and ``failed`` reports may start (no
    force-reprocess of ``completed``); 404 for unknown reports, 409
    while any run is active.
    """
    try:
        run = await reports.start_analysis_for_report(report_id)
    except reports.AnalysisInProgressError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting single-report analysis: {e}")
        raise HTTPException(
            status_code=500, detail="Error starting repair analysis"
        )
    return StartAnalysisResponse(
        run=AnalysisRunItem(**run),
        message="Analysis started. The troubleshooting guide updates when it completes.",
    )


@router.get(
    "/repair-reports/{report_id}/actions", response_model=ReportActionsResponse
)
async def get_report_actions(report_id: str):
    """Repair actions/verifications/events attributable to one report.

    Read-only over the precomputed Troubleshooting Database, filtered by
    the report's stable ``analysis_key`` (plus manifest row ranges for
    fallback IDs). Separate ``repair_actions`` / ``verifications`` /
    ``post_repair_events`` / ``history_only_record_ids`` lists; empty
    states carry ``warnings`` instead of invented data. 404 for unknown
    reports, 422 when the database is unavailable.
    """
    from open_notebook.exceptions import ConfigurationError

    try:
        payload = await reports.get_report_actions(report_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConfigurationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error reading report actions: {e}")
        raise HTTPException(
            status_code=500, detail="Error reading report actions"
        )
    return ReportActionsResponse(**payload)
