"""Repair-report analysis worker (surreal-commands).

``analyze_repair_reports`` runs the standalone maintenance troubleshooting
engine over the report collection snapshotted in a ``repair_analysis_run``
record and atomically replaces the runtime Troubleshooting Database.

Concurrency: at most one knowledge-generation operation may replace the
runtime database at a time. The API refuses to submit while a run is
active (409), and this command re-checks at start — a late duplicate
fails transiently so it retries after the active run finishes. The
engine's own writer (tmp database → integrity validation → ``os.replace``)
guarantees runtime readers only ever see the previous or the new valid
database, never a partial one.

Permanent problems (unknown run, missing workbook, unreadable input,
engine configuration) raise ``ValueError`` so the job is marked
``failed`` without burning retries; anything else retries.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from api import repair_report_service as reports
from open_notebook.exceptions import ConfigurationError


class AnalyzeRepairReportsInput(CommandInput):
    run_id: str


class AnalyzeRepairReportsOutput(CommandOutput):
    success: bool
    run_id: str
    records: int = 0
    equipment_count: int = 0
    failure_mode_count: int = 0
    processing_time: float = 0.0
    error_message: Optional[str] = None


def _load_engine() -> Dict[str, Any]:
    """Import the engine's public batch API (installed or vendored).

    Mirrors ``api/troubleshooting_service._load_package`` so the worker
    behaves identically with a pip-installed engine or a source checkout.
    """
    try:
        from maintenance_troubleshooting import EngineConfig, analyze_workbook

        return {"EngineConfig": EngineConfig, "analyze_workbook": analyze_workbook}
    except ImportError as first_error:
        candidate = (
            Path(__file__).resolve().parent.parent
            / "packages"
            / "maintenance-troubleshooting-engine"
            / "src"
        )
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            try:
                from maintenance_troubleshooting import (
                    EngineConfig,
                    analyze_workbook,
                )

                return {
                    "EngineConfig": EngineConfig,
                    "analyze_workbook": analyze_workbook,
                }
            except ImportError as second_error:
                raise ValueError(
                    "Maintenance troubleshooting engine is not installed."
                ) from second_error
        raise ValueError(
            "Maintenance troubleshooting engine is not installed."
        ) from first_error


def _resolve_database_path() -> Path:
    from api import troubleshooting_service

    return troubleshooting_service.resolve_database_path()


@command(
    "analyze_repair_reports",
    app="open_notebook",
    retry={
        "max_attempts": 3,
        "wait_strategy": "exponential_jitter",
        "wait_min": 5,
        "wait_max": 120,
        "stop_on": [ValueError, ConfigurationError],
        "retry_log_level": "debug",
    },
)
async def analyze_repair_reports_command(
    input_data: AnalyzeRepairReportsInput,
) -> AnalyzeRepairReportsOutput:
    """Run the engine over one run's report snapshot (idempotent resume)."""
    start_time = time.time()
    run_id = input_data.run_id
    logger.info(f"Starting repair-report analysis run: {run_id}")

    run = await reports._get_run_internal(run_id)
    if run.get("status") == reports.RUN_COMPLETED:
        logger.info(f"Analysis run {run_id} already completed; skipping")
        return AnalyzeRepairReportsOutput(
            success=True,
            run_id=run_id,
            records=int(run.get("record_count") or 0),
            equipment_count=int(run.get("equipment_count") or 0),
            failure_mode_count=int(run.get("failure_mode_count") or 0),
            processing_time=0.0,
        )

    # Single-writer guard: another live run means this submission raced the
    # API check — fail transiently so the retry lands after it finishes.
    active = await reports.get_active_run()
    if active is not None and str(active["id"]) != run_id:
        raise RuntimeError(
            f"Another analysis run ({active['id']}) is already in progress."
        )

    report_ids = [str(item) for item in run.get("report_ids") or []]
    if not report_ids:
        message = f"Analysis run {run_id} has no reports."
        await reports.mark_run_failed(run_id, message)
        raise ValueError(message)

    entries: List[Dict[str, Any]] = []
    for report_id in report_ids:
        try:
            internal = await reports._get_report_internal(report_id)
        except Exception as e:
            message = f"Repair report {report_id} is unknown: {e}"
            await _fail_run(run_id, report_ids, message)
            raise ValueError(message) from e
        path = reports.stored_path(internal)
        if not path.exists():
            message = f"Stored file for report {report_id} is missing."
            await _fail_run(run_id, report_ids, message)
            raise ValueError(message) from None
        entries.append(
            {
                "report_id": report_id,
                "filename": internal.get("filename"),
                "analysis_key": internal.get("analysis_key"),
                "path": str(path),
            }
        )
    entries.sort(key=lambda e: e["report_id"])

    for report_id in report_ids:
        await reports._set_report_state(
            report_id, reports.STATE_PROCESSING, run_id=run_id, error=None
        )

    tmp_dir = tempfile.mkdtemp(prefix="repair-analysis-")
    aggregate_path = Path(tmp_dir) / f"aggregate-{run_id.replace(':', '_')}.xlsx"
    try:
        manifest = await _build_aggregate(entries, aggregate_path)
        await reports.mark_run_processing(run_id, manifest)

        engine = _load_engine()
        database_path = _resolve_database_path()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"Running troubleshooting engine for run {run_id} "
            f"over {len(entries)} report(s)"
        )
        result = await asyncio.to_thread(
            engine["analyze_workbook"],
            aggregate_path,
            engine["EngineConfig"].default(),
            None,
            database_path,
        )
        counts = {
            "record_count": len(result.records),
            "equipment_count": len(result.equipment),
            "failure_mode_count": len(result.failure_modes),
            "guide_count": len(result.guides),
        }
        await reports.mark_run_completed(run_id, counts)
        for report_id in report_ids:
            await reports._set_report_completed(report_id, run_id)
        processing_time = time.time() - start_time
        logger.info(
            f"Analysis run {run_id} completed in {processing_time:.1f}s: "
            f"{counts['record_count']} records, {counts['equipment_count']} "
            "equipment"
        )
        return AnalyzeRepairReportsOutput(
            success=True,
            run_id=run_id,
            records=counts["record_count"],
            equipment_count=counts["equipment_count"],
            failure_mode_count=counts["failure_mode_count"],
            processing_time=processing_time,
        )
    except (ValueError, ConfigurationError) as e:
        # Permanent failure: mark the run + workable reports failed now so
        # the job lands in `failed` (stop_on) with honest states.
        message = str(e) or type(e).__name__
        logger.error(f"Analysis run {run_id} failed permanently: {message}")
        await _fail_run(run_id, report_ids, message)
        raise
    except Exception:
        # Transient: leave run/reports in processing so the retry resumes.
        logger.debug(f"Transient error in analysis run {run_id}; will retry")
        raise
    finally:
        try:
            if aggregate_path.exists():
                aggregate_path.unlink()
            os.rmdir(tmp_dir)
        except OSError:
            pass


async def _build_aggregate(
    entries: List[Dict[str, Any]], dest: Path
) -> List[Dict[str, Any]]:
    """Prepare the deterministic aggregate workbook off the event loop."""
    import asyncio

    try:
        return await asyncio.to_thread(
            reports.build_aggregate_workbook, entries, dest
        )
    except Exception as e:
        raise ValueError(f"Could not prepare repair-report input: {e}") from e


async def _fail_run(
    run_id: str, report_ids: List[str], message: str
) -> None:
    """Mark a run failed; keep previously-completed reports completed.

    The runtime database still holds their knowledge (replacement is
    atomic and only happens on success), so only reports that never
    contributed become failed.
    """
    await reports.mark_run_failed(run_id, message)
    for report_id in report_ids:
        try:
            internal = await reports._get_report_internal(report_id)
        except Exception:
            continue
        if internal.get("analysis_state") not in reports.ACTIVE_REPORT_STATES:
            continue
        if internal.get("last_completed_run_id"):
            await reports.restore_report_completed(
                report_id, run_id, str(internal["last_completed_run_id"])
            )
        else:
            await reports._set_report_state(
                report_id, reports.STATE_FAILED, run_id=run_id, error=message
            )
