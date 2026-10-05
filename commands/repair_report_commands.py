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

LLM phase (M16): after the mining engine succeeds, this command triggers
the independent LLM Knowledge Generation pipeline over the same reports
and executes it inline (``_run_llm_phase`` → ``generate_llm_knowledge``
with no command context — no queue round-trip, so no single-worker
deadlock). Order is strictly mining → LLM → run completed; the LLM
pipeline reads only the raw workbooks, never mining output. LLM failures
(preflight with no model configured, provider errors, build failures)
are logged explicitly and never fail the mining result: the run still
completes and the LLM build (if created) carries its own terminal
status (completed / partial / failed) for the Repair Guide to display.

NOTE: this module must NOT use ``from __future__ import annotations``.
The surreal-commands registry resolves the command's input/output type
hints at registration time and cannot resolve postponed (string)
annotations — no other command module uses the future import either.
"""

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
from open_notebook.exceptions import (
    ConfigurationError,
    ContextLengthExceededError,
    NotFoundError,
)


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
        "stop_on": [ValueError, ConfigurationError, ContextLengthExceededError],
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
    if run.get("status") == reports.RUN_FAILED:
        # A run the API already failed (submit/attach fallout, stale
        # finalization) must never execute: its command, if one was
        # submitted, is an orphan. Raise permanently so the job lands in
        # `failed` without touching reports or the runtime database.
        message = str(run.get("error") or "Analysis run was already failed.")
        logger.warning(f"Analysis run {run_id} is failed; not executing: {message}")
        raise ValueError(message)

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
    stop_heartbeat = asyncio.Event()
    heartbeat_task: Optional[asyncio.Task[None]] = None
    worker_command_id = str(run.get("command_id")) if run.get("command_id") else None
    try:
        manifest = await _build_aggregate(entries, aggregate_path)
        await reports.mark_run_processing(run_id, manifest)
        if worker_command_id:
            await _heartbeat_once(worker_command_id)
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(worker_command_id, stop_heartbeat)
            )

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
        # Guard against resurrecting a run the API already failed (stale
        # finalization while this worker was still running): only a run
        # that is still `processing` may be completed, so the previous
        # valid database and report states are never overwritten by a
        # superseded run.
        current = await reports._get_run_internal(run_id)
        if current.get("status") != reports.RUN_PROCESSING:
            message = (
                f"Analysis run {run_id} is {current.get('status')}, "
                "refusing to complete it."
            )
            logger.error(message)
            raise ValueError(message)
        # LLM phase (M16): independent knowledge over the same raw
        # reports, executed inline before the run completes. Mining →
        # LLM → completed, strictly sequential; LLM failures never fail
        # the mining result (see _run_llm_phase).
        llm_outcome = await _run_llm_phase(report_ids)
        if llm_outcome is not None:
            logger.info(
                f"Analysis run {run_id} LLM phase: "
                f"build {llm_outcome['build_id']} "
                f"({llm_outcome['status']}, "
                f"{llm_outcome['records']} ok, "
                f"{llm_outcome['failed_records']} failed)"
            )
        else:
            logger.info(
                f"Analysis run {run_id} LLM phase: skipped "
                "(no build; see warning above)"
            )
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
        stop_heartbeat.set()
        if heartbeat_task is not None:
            try:
                await heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            if aggregate_path.exists():
                aggregate_path.unlink()
            os.rmdir(tmp_dir)
        except OSError:
            pass


async def _run_llm_command(build_id: str) -> Any:
    """Execute one LLM build inline (module seam: tests stub this).

    Calls the real ``generate_llm_knowledge`` worker function directly —
    without a queue round-trip — so the analysis worker never deadlocks
    waiting on a job only it can pick up. ``execution_context`` is None,
    which the command tolerates (heartbeat simply stays off).
    """
    from commands.llm_knowledge_commands import (
        GenerateLLMKnowledgeInput,
        generate_llm_knowledge_command,
    )

    return await generate_llm_knowledge_command(
        GenerateLLMKnowledgeInput(build_id=build_id)
    )


async def _run_llm_phase(report_ids: List[str]) -> Optional[Dict[str, Any]]:
    """Trigger and execute LLM generation for one analysis run.

    Returns an outcome dict (build_id, status, records, failed_records;
    status is one of completed/partial/failed) or None when no build
    could start (e.g. no language model configured). Permanent LLM
    failures are logged explicitly and never fail the mining run.
    Transient errors (DB conflicts, provider timeouts) propagate so the
    analysis job retries; mining re-runs in seconds and the LLM build
    resumes instead of duplicating.
    """
    from api import llm_knowledge_service as llm
    from open_notebook.exceptions import InvalidInputError

    # Retry-after-completion: finished knowledge for this exact report
    # set is reused, never rebuilt (the active-build guard only covers
    # queued/running builds).
    finished = await llm.find_latest_finished_build_for_reports(report_ids)
    if finished is not None:
        build_id = str(finished["id"])
        logger.info(
            f"Reusing finished LLM knowledge build {build_id} "
            f"({finished.get('status')}) for analysis"
        )
        return {
            "build_id": build_id,
            "status": str(finished.get("status")),
            "records": int(finished.get("record_count") or 0),
            "failed_records": int(finished.get("failed_record_count") or 0),
        }
    try:
        # Inline execution: no worker command is submitted (exactly one
        # executor — this job — so a queued duplicate can never race it).
        build = await llm.start_build(report_ids, submit_command=False)
        build_id = str(build["id"])
        logger.info(f"Analysis triggered LLM knowledge build {build_id}")
    except llm.BuildInProgressError as e:
        # Retry/resume path: an equivalent build is already active.
        # Reuse it instead of creating a duplicate.
        build_id = str(e.build_id)
        logger.info(
            f"Reusing active LLM knowledge build {build_id} for analysis"
        )
    except (ConfigurationError, InvalidInputError, NotFoundError) as e:
        logger.warning(
            f"Skipping LLM knowledge generation: {e}. "
            "Mining output is unaffected."
        )
        return None
    # Any other submit error is transient: propagate for retry rather
    # than completing the run with a silent LLM gap.
    try:
        outcome = await _run_llm_command(build_id)
    except (ValueError, ConfigurationError, ContextLengthExceededError) as e:
        # Permanent: the generate command already marked the build
        # failed. Mining still completes; the failed build stays
        # visible in Repair Guide (explicit, never silent success).
        logger.warning(
            f"LLM knowledge build {build_id} failed permanently: {e}. "
            "Mining output is unaffected."
        )
        return {
            "build_id": build_id,
            "status": "failed",
            "records": 0,
            "failed_records": 0,
        }
    # Any other exception is transient (DB read/write conflict, provider
    # timeout, LLM wall-clock): propagate so the analysis job retries.
    # Mining re-runs in seconds and the LLM build resumes via
    # equivalent-build reuse + persisted-record skip — never duplicates.
    if outcome.success and outcome.failed_records:
        status = "partial"
    elif outcome.success:
        status = "completed"
    else:
        status = "failed"
    logger.info(
        f"LLM knowledge build {build_id} finished inline: "
        f"{outcome.records} ok, {outcome.failed_records} failed"
    )
    return {
        "build_id": build_id,
        "status": status,
        "records": outcome.records,
        "failed_records": outcome.failed_records,
    }


async def _heartbeat_once(command_id: str) -> None:
    """Best-effort liveness write so a live run is never mistaken for dead.

    The framework only flips ``new → running → completed|failed`` with no
    progress signal in between; without this, a worker killed mid-run
    leaves ``running`` forever and every future analysis 409s. Failures
    here must never fail the run itself.
    """
    try:
        from open_notebook.database.repository import ensure_record_id, repo_query

        await repo_query(
            "UPDATE $cid SET analysis_heartbeat = time::now(), "
            "updated_at = time::now()",
            {"cid": ensure_record_id(command_id)},
        )
    except Exception as e:
        logger.debug(f"Analysis heartbeat failed (ignored): {e}")


async def _heartbeat_loop(command_id: str, stop: asyncio.Event) -> None:
    """Write liveness every HEARTBEAT_INTERVAL_SECONDS until stopped."""
    while not stop.is_set():
        await _heartbeat_once(command_id)
        try:
            await asyncio.wait_for(stop.wait(), timeout=reports.HEARTBEAT_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def _build_aggregate(
    entries: List[Dict[str, Any]], dest: Path
) -> List[Dict[str, Any]]:
    """Prepare the deterministic aggregate workbook off the event loop."""
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
