from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.exceptions import NotFoundError

router = APIRouter()


class TaskActiveError(Exception):
    """A task-record deletion was requested while the job is still active."""


class TaskItem(BaseModel):
    """A single background job with real progress state.

    Embedding jobs carry chunk progress; repair-analysis jobs carry the
    analysis run context instead (no chunk counts exist there, and none
    are invented — indeterminate progress while active, 100% when done).
    """

    job_id: str = Field(..., description="Command/job ID")
    item_type: str = Field(
        ...,
        description="Job family: 'source', 'repair_analysis' or 'llm_knowledge'",
    )
    command_name: Optional[str] = Field(
        None, description="surreal-commands command name"
    )
    run_id: Optional[str] = Field(
        None, description="Analysis run ID (repair jobs only)"
    )
    title: Optional[str] = Field(
        None, description="Display title (repair report filenames)"
    )
    source_id: Optional[str] = Field(None, description="Source being embedded")
    source_title: Optional[str] = Field(None, description="Source title, if known")
    status: str = Field(
        ..., description="Job status: new, running, completed, failed, canceled"
    )
    processed_chunks: Optional[int] = Field(
        None, description="Chunks embedded so far (real worker progress)"
    )
    total_chunks: Optional[int] = Field(
        None, description="Total chunks, once the worker has chunked the text"
    )
    percentage: Optional[float] = Field(
        None,
        description="processed/total*100 when total is known, else null (indeterminate)",
    )
    chunks_created: Optional[int] = Field(
        None, description="Final chunk count for completed jobs"
    )
    created: Optional[str] = Field(None, description="Submission time, if recorded")
    updated: Optional[str] = Field(
        None, description="Last update time (completion time when finished)"
    )
    started_at: Optional[str] = Field(
        None, description="When the worker started embedding (new jobs)"
    )
    updated_at: Optional[str] = Field(
        None,
        description="Last worker progress write; completion time for finished jobs",
    )
    error_message: Optional[str] = Field(None, description="Failure reason, if any")


@router.get("/tasks", response_model=List[TaskItem])
async def list_tasks(limit: int = Query(50, ge=1, le=200)):
    """
    List recent background jobs with real progress.

    Reads the persisted surreal-commands `command` records (which survive
    API restarts and page reloads): source-embedding jobs with the
    per-batch progress the embed worker writes back, plus repair-analysis
    jobs linked to their analysis runs. No estimated or fake progress:
    percentage is processed/total*100 only when the worker has reported
    a total, otherwise null (UI shows an indeterminate state).
    """
    from open_notebook.database.repository import repo_query

    try:
        records = await repo_query(
            "SELECT * FROM command WHERE app = 'open_notebook' "
            "AND name = 'embed_source' ORDER BY created DESC LIMIT $limit",
            {"limit": limit},
        )
    except Exception as e:
        logger.error(f"Failed to list embedding tasks: {e}")
        records = []

    # Enrich with source titles in one query (sources may have been deleted).
    titles: dict = {}
    try:
        for row in await repo_query("SELECT id, title FROM source"):
            titles[str(row.get("id"))] = row.get("title")
    except Exception as e:
        logger.debug(f"Failed to load source titles for tasks: {e}")

    tasks: List[TaskItem] = []
    for cmd in records or []:
        args = cmd.get("args") or {}
        result = cmd.get("result") or {}
        status = str(cmd.get("status") or "unknown")
        source_id = args.get("source_id")

        processed = cmd.get("progress_processed")
        total = cmd.get("progress_total")
        chunks_created = result.get("chunks_created")

        if status == "completed":
            # Worker-reported totals are authoritative; fall back to the
            # final chunk count for jobs finished before progress existed.
            total = total if isinstance(total, int) else chunks_created
            processed = (
                processed if isinstance(processed, int) else chunks_created
            )

        percentage: Optional[float] = None
        if isinstance(total, int) and total > 0 and isinstance(processed, int):
            percentage = round(processed / total * 100, 1)
        elif status == "completed":
            # A finished job is 100% done even when no chunk total was ever
            # reported (e.g. jobs from before progress tracking existed).
            percentage = 100.0

        tasks.append(
            TaskItem(
                job_id=str(cmd.get("id")),
                item_type="source",
                command_name="embed_source",
                run_id=None,
                title=None,
                source_id=str(source_id) if source_id else None,
                source_title=titles.get(str(source_id)) if source_id else None,
                status=status,
                processed_chunks=processed if isinstance(processed, int) else None,
                total_chunks=total if isinstance(total, int) else None,
                percentage=percentage,
                chunks_created=chunks_created
                if isinstance(chunks_created, int)
                else None,
                created=str(cmd.get("created"))
                if cmd.get("created") is not None
                else None,
                updated=str(cmd.get("updated"))
                if cmd.get("updated") is not None
                else None,
                started_at=str(cmd.get("started_at"))
                if cmd.get("started_at") is not None
                else None,
                updated_at=str(cmd.get("updated_at"))
                if cmd.get("updated_at") is not None
                else None,
                error_message=cmd.get("error_message"),
            )
        )

    tasks.extend(await _repair_analysis_tasks(limit))
    tasks.extend(await _llm_knowledge_tasks(limit))

    # Most recently updated first across both job families (canonical
    # last-update ordering; creation time then stable job ID break ties
    # deterministically when timestamps match or are absent).
    tasks.sort(key=_task_sort_key, reverse=True)
    return tasks[:limit]


def _task_sort_key(task: TaskItem) -> tuple:
    """Updated-first ordering with deterministic tie-breakers."""
    return (
        task.updated_at or task.updated or "",
        task.created or task.started_at or "",
        task.job_id or "",
    )


#: Task families surfaced on the Tasks page (and only these are managed
#: by the history endpoints below — process_source and other command
#: families are never touched).
TASK_COMMAND_FAMILIES = (
    "embed_source",
    "embed_note",
    "embed_insight",
    "analyze_repair_reports",
    "generate_llm_knowledge",
)

#: Command statuses that are safe to clear: terminal history only.
_TERMINAL_TASK_STATUSES = ("completed", "failed", "canceled")


class ClearHistoryResult(BaseModel):
    """Acknowledgement for clearing terminal historical task records."""

    deleted: int = Field(..., description="Terminal task records removed")


@router.delete("/tasks/history", response_model=ClearHistoryResult)
async def clear_tasks_history():
    """Delete terminal historical task records (Clear History).

    Removes `completed`/`failed`/`canceled` command rows for the task
    families shown on the Tasks page. Active jobs (`new`/`running`) are
    never touched, never canceled, and never deleted; run history,
    sources, reports, and the knowledge database are preserved. Safe to
    call repeatedly (a second call deletes 0).
    """
    from open_notebook.database.repository import repo_delete, repo_query

    try:
        rows = await repo_query(
            "SELECT id, status FROM command WHERE app = 'open_notebook' "
            "AND name IN $names AND status IN $statuses",
            {
                "names": list(TASK_COMMAND_FAMILIES),
                "statuses": list(_TERMINAL_TASK_STATUSES),
            },
        )
    except Exception as e:
        logger.error(f"Failed to list terminal tasks: {e}")
        raise HTTPException(status_code=500, detail="Error clearing task history")
    deleted = 0
    for row in rows or []:
        # Defensive: only terminal rows are ever removed, even if the
        # query above were ever widened. Active jobs are never touched.
        if str((row or {}).get("status") or "") not in _TERMINAL_TASK_STATUSES:
            continue
        try:
            from open_notebook.database.repository import ensure_record_id

            await repo_delete(ensure_record_id(str(row.get("id"))))
            deleted += 1
        except Exception as e:
            logger.warning(f"Failed to delete terminal task {row.get('id')}: {e}")
    return ClearHistoryResult(deleted=deleted)


async def _repair_analysis_tasks(limit: int) -> List[TaskItem]:
    """Repair-analysis commands as task rows sharing one truth with reports.

    The command record carries execution state (new/running/completed/
    failed); the linked analysis run carries the report set. Displayed
    titles are stored filenames (data, never paths).
    """
    from open_notebook.database.repository import repo_query

    try:
        commands = await repo_query(
            "SELECT * FROM command WHERE app = 'open_notebook' "
            "AND name = 'analyze_repair_reports' ORDER BY created DESC "
            "LIMIT $limit",
            {"limit": limit},
        )
    except Exception as e:
        logger.error(f"Failed to list repair analysis tasks: {e}")
        return []
    if not commands:
        return []

    run_ids = {
        str((cmd.get("args") or {}).get("run_id"))
        for cmd in commands
        if (cmd.get("args") or {}).get("run_id")
    }
    runs: dict = {}
    report_ids: set = set()
    try:
        for row in await repo_query(
            "SELECT id, report_ids FROM repair_analysis_run"
        ):
            rid = str(row.get("id"))
            if rid in run_ids:
                ids = [str(item) for item in row.get("report_ids") or []]
                runs[rid] = ids
                report_ids.update(ids)
    except Exception as e:
        logger.debug(f"Failed to load analysis runs for tasks: {e}")

    filenames: dict = {}
    try:
        for row in await repo_query(
            "SELECT id, filename FROM repair_report"
        ):
            filenames[str(row.get("id"))] = row.get("filename")
    except Exception as e:
        logger.debug(f"Failed to load report filenames for tasks: {e}")

    items: List[TaskItem] = []
    for cmd in commands:
        args = cmd.get("args") or {}
        result = cmd.get("result") or {}
        status = str(cmd.get("status") or "unknown")
        run_id = str(args.get("run_id")) if args.get("run_id") else None
        names = [
            filenames.get(rid, rid)
            for rid in runs.get(run_id, [])
            if run_id is not None
        ]
        items.append(
            TaskItem(
                job_id=str(cmd.get("id")),
                item_type="repair_analysis",
                command_name="analyze_repair_reports",
                run_id=run_id,
                title=", ".join(name for name in names if name) or None,
                source_id=None,
                source_title=None,
                status=status,
                processed_chunks=None,
                total_chunks=None,
                # No chunk counts exist for analysis jobs: indeterminate
                # while active, 100% once completed — never estimated.
                percentage=100.0 if status == "completed" else None,
                chunks_created=None,
                created=str(cmd.get("created"))
                if cmd.get("created") is not None
                else None,
                updated=str(cmd.get("updated"))
                if cmd.get("updated") is not None
                else None,
                started_at=str(cmd.get("started_at"))
                if cmd.get("started_at") is not None
                else None,
                updated_at=str(cmd.get("updated_at"))
                if cmd.get("updated_at") is not None
                else None,
                error_message=cmd.get("error_message") or result.get("error_message"),
            )
        )
    return items


async def _llm_knowledge_tasks(limit: int) -> List[TaskItem]:
    """LLM knowledge-build commands as task rows (one truth with builds).

    The command record carries execution state; the linked
    ``llm_knowledge_build`` carries the report set. Displayed titles are
    stored filenames (data, never paths). Mining tasks are untouched.
    """
    from open_notebook.database.repository import repo_query

    try:
        commands = await repo_query(
            "SELECT * FROM command WHERE app = 'open_notebook' "
            "AND name = 'generate_llm_knowledge' ORDER BY created DESC "
            "LIMIT $limit",
            {"limit": limit},
        )
    except Exception as e:
        logger.error(f"Failed to list LLM knowledge tasks: {e}")
        return []
    if not commands:
        return []

    build_ids = {
        str((cmd.get("args") or {}).get("build_id"))
        for cmd in commands
        if (cmd.get("args") or {}).get("build_id")
    }
    builds: dict = {}
    report_ids: set = set()
    try:
        for row in await repo_query(
            "SELECT id, source_report_ids FROM llm_knowledge_build"
        ):
            bid = str(row.get("id"))
            if bid in build_ids:
                ids = [str(item) for item in row.get("source_report_ids") or []]
                builds[bid] = ids
                report_ids.update(ids)
    except Exception as e:
        logger.debug(f"Failed to load LLM builds for tasks: {e}")

    filenames: dict = {}
    try:
        for row in await repo_query("SELECT id, filename FROM repair_report"):
            filenames[str(row.get("id"))] = row.get("filename")
    except Exception as e:
        logger.debug(f"Failed to load report filenames for tasks: {e}")

    items: List[TaskItem] = []
    for cmd in commands:
        args = cmd.get("args") or {}
        result = cmd.get("result") or {}
        status = str(cmd.get("status") or "unknown")
        build_id = str(args.get("build_id")) if args.get("build_id") else None
        names = [
            filenames.get(rid, rid)
            for rid in builds.get(build_id, [])
            if build_id is not None
        ]
        title = ", ".join(name for name in names if name) or None
        if title is None and build_id is not None:
            # Report-less builds (e.g. a build that failed before any
            # report resolved) still need a recognizable row: fall back
            # to the short build ID instead of an anonymous entry.
            title = build_id[-6:]
        items.append(
            TaskItem(
                job_id=str(cmd.get("id")),
                item_type="llm_knowledge",
                command_name="generate_llm_knowledge",
                run_id=build_id,
                title=title,
                source_id=None,
                source_title=None,
                status=status,
                processed_chunks=None,
                total_chunks=None,
                percentage=100.0 if status == "completed" else None,
                chunks_created=None,
                created=str(cmd.get("created"))
                if cmd.get("created") is not None
                else None,
                updated=str(cmd.get("updated"))
                if cmd.get("updated") is not None
                else None,
                started_at=str(cmd.get("started_at"))
                if cmd.get("started_at") is not None
                else None,
                updated_at=str(cmd.get("updated_at"))
                if cmd.get("updated_at") is not None
                else None,
                error_message=cmd.get("error_message") or result.get("error_message"),
            )
        )
    return items


class TaskDeleteResult(BaseModel):
    """Acknowledgement for a task-record deletion (command row only)."""

    job_id: str = Field(..., description="Deleted command/job ID")
    deleted: bool = Field(..., description="Always true on success")


@router.delete("/tasks/{job_id}", response_model=TaskDeleteResult)
async def delete_task(job_id: str):
    """Delete a terminal background-job record (Tasks page housekeeping).

    Removes the surreal-commands ``command`` row only — never source
    files, repair reports, analysis runs, or the generated knowledge
    database. Only terminal jobs (``completed`` | ``failed`` |
    ``canceled``) may be deleted; active (``new`` | ``running``) jobs
    get 409 so a live worker run can never be orphaned. 404 for unknown
    job IDs.
    """
    from open_notebook.database.repository import (
        ensure_record_id,
        repo_delete,
        repo_query,
    )

    try:
        try:
            record_id = ensure_record_id(job_id)
        except Exception:
            raise NotFoundError(f"Unknown task: {job_id}.")
        try:
            rows = await repo_query(
                "SELECT * FROM command WHERE id = $cid",
                {"cid": record_id},
            )
        except Exception as e:
            logger.error(f"Failed to read task {job_id}: {e}")
            raise HTTPException(status_code=500, detail="Error deleting task")
        if not rows:
            raise NotFoundError(f"Unknown task: {job_id}.")
        status = str((rows[0] or {}).get("status") or "unknown")
        if status in ("new", "running"):
            raise TaskActiveError(
                "This task is still active; wait for it to finish "
                "or cancel it before deleting."
            )
        try:
            await repo_delete(record_id)
        except Exception as e:
            logger.error(f"Failed to delete task {job_id}: {e}")
            raise HTTPException(status_code=500, detail="Error deleting task")
        return TaskDeleteResult(job_id=str((rows[0] or {}).get("id") or job_id), deleted=True)
    except NotFoundError:
        raise
    except TaskActiveError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting task {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Error deleting task")
