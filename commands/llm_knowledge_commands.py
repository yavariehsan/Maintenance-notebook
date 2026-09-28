"""LLM knowledge-build worker (surreal-commands, M12).

``generate_llm_knowledge`` runs one ``llm_knowledge_build``: deterministic
row extraction per report (no embeddings), one structured LLM call per
record, validation + semantic post-rules, then persistence. Previous
builds, mining knowledge, reports, and embeddings are never touched.

Idempotent resume: records already persisted for the build (unique index
on build_id + source_record_id) are skipped, so a retried job continues
instead of duplicating. A failed record is persisted with its
``record_error`` and never invalidates the records that succeeded
(completed / partial / failed terminal states reflect the mix).

Permanent problems (unknown build, missing workbook, unconfigured
language model) raise ``ValueError``/``ConfigurationError`` so the job
is marked ``failed`` without burning retries; anything else retries and
resumes.

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
from open_notebook.exceptions import ConfigurationError


class GenerateLLMKnowledgeInput(CommandInput):
    build_id: str


class GenerateLLMKnowledgeOutput(CommandOutput):
    success: bool
    build_id: str
    records: int = 0
    failed_records: int = 0
    processing_time: float = 0.0
    error_message: Optional[str] = None


#: (source_text, source_record_id, model_id) -> raw LLM response text.
#: Module seam: tests inject a fake; production uses the real generator.
GenerateFn = Callable[[str, str, Optional[str]], Awaitable[str]]


async def _default_generate_fn(
    source_text: str, source_record_id: str, model_id: Optional[str]
) -> str:
    from api.llm_generation import default_generate

    return await default_generate(source_text, source_record_id, model_id)


_GENERATE_FN: GenerateFn = _default_generate_fn


def set_generate_fn(fn: GenerateFn) -> None:
    """Override the LLM call (tests only — never in production)."""
    global _GENERATE_FN
    _GENERATE_FN = fn


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
        "stop_on": [ValueError, ConfigurationError],
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
            done_ids = await llm_knowledge.existing_source_record_ids(build_id)
        except Exception as e:
            raise ValueError(f"Could not read existing LLM records: {e}") from e

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

        ok_count = len(done_ids)
        failed_count = 0
        warnings: List[str] = []

        for entry in manifest:
            report_id = str(entry.get("report_id") or "")
            if not report_id:
                warnings.append("manifest_entry_without_report_id")
                continue
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
            inputs = llm_knowledge.extract_record_inputs(
                analysis_key, sheet, headers, data_rows
            )
            if not inputs:
                warnings.append(f"no_text_rows:{report_id}")
                continue
            for record_input in inputs:
                source_record_id = str(record_input["source_record_id"])
                if source_record_id in done_ids:
                    continue
                source_text = str(record_input["source_text"])
                try:
                    raw = await _GENERATE_FN(source_text, source_record_id, model_id)
                except (ValueError, ConfigurationError):
                    raise
                except Exception as e:
                    record_error = f"provider_error: {e}"[:500]
                    try:
                        await llm_knowledge.save_record(
                            build_id,
                            report_id,
                            source_record_id,
                            source_text,
                            None,
                            record_error,
                        )
                    except Exception as save_error:  # pragma: no cover - defensive
                        logger.error(f"Could not persist failed LLM record: {save_error}")
                    failed_count += 1
                    done_ids.add(source_record_id)
                    continue
                extraction, parse_errors = llm_knowledge.parse_llm_extraction(raw)
                if extraction is None:
                    record_error = "; ".join(parse_errors)[:500] or "invalid_llm_output"
                    try:
                        await llm_knowledge.save_record(
                            build_id,
                            report_id,
                            source_record_id,
                            source_text,
                            None,
                            record_error,
                        )
                    except Exception as save_error:  # pragma: no cover - defensive
                        logger.error(f"Could not persist failed LLM record: {save_error}")
                    failed_count += 1
                    done_ids.add(source_record_id)
                    continue
                extraction = llm_knowledge.apply_semantic_rules(extraction)
                record_warnings = [
                    message for message in parse_errors if message.startswith("warning:")
                ]
                try:
                    await llm_knowledge.save_record(
                        build_id,
                        report_id,
                        source_record_id,
                        source_text,
                        extraction,
                        "; ".join(record_warnings)[:500] if record_warnings else None,
                    )
                except Exception as e:
                    # Unique-index collision means a retried attempt already
                    # wrote this record — count it once, never duplicate.
                    message = str(e)
                    if "unique" in message.lower() or "duplicate" in message.lower():
                        logger.debug(f"LLM record {source_record_id} already stored")
                    else:
                        raise
                ok_count += 1
                done_ids.add(source_record_id)

        if ok_count > 0 and failed_count == 0:
            terminal = llm_knowledge.BUILD_COMPLETED
        elif ok_count > 0:
            terminal = llm_knowledge.BUILD_PARTIAL
        else:
            terminal = llm_knowledge.BUILD_FAILED
        error = (
            None
            if terminal != llm_knowledge.BUILD_FAILED
            else "All LLM extractions failed; see record_error on records."
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
    except Exception:
        # Transient: leave the build running for retry (resume skips
        # records already persisted — never duplicates).
        raise
    finally:
        stop_heartbeat.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
