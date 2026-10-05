"""LLM knowledge-build worker (surreal-commands, M12/M19).

``generate_llm_knowledge`` runs one ``llm_knowledge_build``: deterministic
scope planning per (Equipment, Failure Mode) — never mixing equipment or
failure modes — one direct LLM call per scope producing the final Persian
troubleshooting insight, which is persisted as-is (never rewritten).
Previous builds, mining knowledge, reports, and embeddings are never
touched.

Idempotent resume: scopes already guided for the build (unique index on
build_id + equipment + failure_mode) are skipped, so a retried job
continues instead of duplicating. A failed scope never invalidates the
scopes that succeeded (completed / partial / failed terminal states
reflect the mix).

Permanent problems (unknown build, missing workbook, unconfigured
language model) raise ``ValueError``/``ConfigurationError`` so the job
is marked ``failed`` without burning retries. Unexpected failures
finalize the build as failed with the cause recorded — a build is never
left running.

NOTE: this module must NOT use ``from __future__ import annotations``.
The surreal-commands registry resolves the command's input/output type
hints at registration time and cannot resolve postponed (string)
annotations — no other command module uses the future import either.
"""

import asyncio
import time
from typing import Awaitable, Callable, List, Optional

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from api import llm_knowledge_service as llm_knowledge
from api import repair_report_service as reports
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.exceptions import (
    ConfigurationError,
    ContextLengthExceededError,
)


class GenerateLLMKnowledgeInput(CommandInput):
    build_id: str


class GenerateLLMKnowledgeOutput(CommandOutput):
    success: bool
    build_id: str
    records: int = 0
    failed_records: int = 0
    processing_time: float = 0.0
    error_message: Optional[str] = None


#: (system, user, scope_id, model_id, max_tokens) -> raw LLM response text.
#: Module seam: tests inject a fake; production uses the real generator.
BatchGenerateFn = Callable[
    [str, str, str, Optional[str], Optional[int]], Awaitable[str]
]


async def _default_batch_generate_fn(
    system: str, user: str, batch_id: str, model_id: Optional[str],
    max_tokens: Optional[int] = None,
) -> str:
    from api.llm_generation import LLMKnowledgeGenerator

    return await LLMKnowledgeGenerator(model_id).generate_from_messages(
        system, user, max_tokens=max_tokens
    )


_BATCH_GENERATE_FN: BatchGenerateFn = _default_batch_generate_fn


def set_generate_fn(fn: BatchGenerateFn) -> None:
    """Override the LLM call (tests only — never in production)."""
    global _BATCH_GENERATE_FN
    _BATCH_GENERATE_FN = fn


async def _heartbeat_once(command_id: str) -> None:
    """Best-effort liveness write so stale-sweeps see a live worker."""
    try:
        await repo_query(
            "UPDATE $cid SET updated_at = time::now()",
            {"cid": ensure_record_id(command_id)},
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"LLM build heartbeat write failed: {e}")


async def _heartbeat_loop(command_id: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=reports.HEARTBEAT_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            await _heartbeat_once(command_id)


async def _fail_build(build_id: str, message: str) -> None:
    try:
        await llm_knowledge.mark_build_failed(build_id, message)
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Failed to mark LLM build {build_id} failed: {e}")


@command(
    "generate_llm_knowledge",
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
async def generate_llm_knowledge_command(
    input_data: GenerateLLMKnowledgeInput,
) -> GenerateLLMKnowledgeOutput:
    """Generate validated LLM knowledge for one build (idempotent resume)."""
    start_time = time.time()
    build_id = input_data.build_id
    logger.info(f"Starting LLM knowledge build: {build_id}")

    try:
        build = await llm_knowledge._get_build_internal(build_id)
    except Exception as e:
        raise ValueError(f"Unknown LLM knowledge build: {build_id}: {e}") from e

    status = str(build.get("status"))
    if status in (llm_knowledge.BUILD_COMPLETED, llm_knowledge.BUILD_PARTIAL):
        logger.info(f"LLM knowledge build {build_id} already finished; skipping")
        return GenerateLLMKnowledgeOutput(
            success=True,
            build_id=build_id,
            records=int(build.get("record_count") or 0),
            failed_records=int(build.get("failed_record_count") or 0),
            processing_time=0.0,
        )
    if status in (llm_knowledge.BUILD_FAILED, llm_knowledge.BUILD_CANCELLED):
        message = str(build.get("error") or "LLM knowledge build was already failed.")
        logger.warning(f"LLM knowledge build {build_id} is {status}; not executing")
        raise ValueError(message)

    command_id = (
        str(input_data.execution_context.command_id)
        if input_data.execution_context
        else None
    )
    stop_heartbeat = asyncio.Event()
    heartbeat_task: Optional[asyncio.Task] = None

    try:
        await llm_knowledge.mark_build_running(build_id)
        if command_id:
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(command_id, stop_heartbeat)
            )

        try:
            done_scopes = await llm_knowledge._existing_stage_b_scopes(build_id)
        except Exception as e:
            raise ValueError(f"Could not read existing LLM guides: {e}") from e

        model_id = build.get("model")
        if not model_id:
            try:
                model_id = await llm_knowledge.resolve_llm_model_id()
            except ConfigurationError:
                raise
            except Exception as e:
                raise ValueError(f"Could not resolve LLM model: {e}") from e

        manifest = build.get("manifest") or []
        if not manifest:
            raise ValueError("LLM knowledge build has no report manifest.")

        ok_count = len(done_scopes)
        failed_count = 0
        warnings: List[str] = []
        seen_reports = set()

        for entry in manifest:
            report_id = str(entry.get("report_id") or "")
            if not report_id:
                warnings.append("manifest_entry_without_report_id")
                continue
            if report_id in seen_reports:
                warnings.append(f"duplicate_manifest_report:{report_id}")
                continue
            seen_reports.add(report_id)
            try:
                content = await reports.read_report_file(report_id)
            except Exception as e:
                raise ValueError(
                    f"Stored file for repair report {report_id} is missing: {e}"
                ) from e
            try:
                rows, sheet = await asyncio.to_thread(
                    reports._open_sheet, content
                )
            except Exception as e:
                raise ValueError(f"Unreadable workbook for {report_id}: {e}") from e
            headers = [
                str(cell).strip() if cell is not None else "" for cell in rows[0]
            ]
            data_rows = [list(row) for row in rows[1:]]
            try:
                internal = await reports._get_report_internal(report_id)
                analysis_key = str(internal.get("analysis_key") or "nokey")
            except Exception as e:
                raise ValueError(f"Unknown repair report: {report_id}: {e}") from e
            scopes = llm_knowledge.plan_scope_insights(
                analysis_key, sheet, headers, data_rows
            )
            if not scopes:
                warnings.append(f"no_text_rows:{report_id}")
                continue
            scope_records = {
                str(scope["scope_id"]): llm_knowledge.plan_scope_records(
                    scope, headers, data_rows)
                for scope in scopes
            }
            ok, failed, scope_warnings = \
                await llm_knowledge.run_scope_insights_for_build(
                    scopes, scope_records, build_id, model_id,
                    _BATCH_GENERATE_FN,
                )
            ok_count += ok
            failed_count += failed
            warnings.extend(scope_warnings)
            done_scopes = await llm_knowledge._existing_stage_b_scopes(build_id)

        if ok_count > 0 and failed_count == 0:
            terminal = llm_knowledge.BUILD_COMPLETED
        elif ok_count > 0:
            terminal = llm_knowledge.BUILD_PARTIAL
        else:
            terminal = llm_knowledge.BUILD_FAILED
        error = (
            None
            if terminal != llm_knowledge.BUILD_FAILED
            else "All LLM insight scopes failed; see build warnings."
        )
        await llm_knowledge.mark_build_finished(
            build_id,
            status=terminal,
            record_count=ok_count,
            failed_record_count=failed_count,
            warnings=warnings,
            error=error,
        )
        logger.info(
            f"LLM knowledge build {build_id} finished: {terminal} "
            f"({ok_count} ok, {failed_count} failed)"
        )
        return GenerateLLMKnowledgeOutput(
            success=terminal != llm_knowledge.BUILD_FAILED,
            build_id=build_id,
            records=ok_count,
            failed_records=failed_count,
            processing_time=time.time() - start_time,
        )
    except (ValueError, ConfigurationError) as e:
        await _fail_build(build_id, str(e))
        raise
    except Exception as e:
        # Never leave the build running: an unexpected failure finalizes
        # it as failed (with the cause recorded) instead of orphaning it
        # for a retry that can no longer resume anything.
        message = f"LLM knowledge build failed: {e}"[:500]
        await _fail_build(build_id, message)
        return GenerateLLMKnowledgeOutput(
            success=False,
            build_id=build_id,
            records=0,
            failed_records=0,
            processing_time=time.time() - start_time,
            error_message=message,
        )
    finally:
        stop_heartbeat.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
