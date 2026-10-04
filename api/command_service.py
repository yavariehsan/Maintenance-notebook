from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from surreal_commands import get_command_status, submit_command

#: A `running` command with no worker heartbeat (or any activity timestamp)
#: fresher than this is considered orphaned: restarted workers only resume
#: `new` commands, so nothing can ever complete it. Mirrors
#: `RUNNING_LEASE_SECONDS` in repair_report_service / llm_knowledge_service.
STALE_COMMAND_LEASE_SECONDS = 1800


def _parse_time(value: Any) -> Optional[float]:
    """SurrealDB timestamp (datetime or ISO string) → epoch seconds."""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _latest_activity(command: Dict[str, Any]) -> Optional[float]:
    """Freshest liveness evidence on a command row (heartbeat wins)."""
    candidates = [
        _parse_time(command.get("analysis_heartbeat")),
        _parse_time(command.get("updated_at")),
        _parse_time(command.get("started_at")),
        _parse_time(command.get("created")),
    ]
    fresh = [value for value in candidates if value is not None]
    return max(fresh) if fresh else None


class CommandService:
    """Generic service layer for command operations"""

    @staticmethod
    async def submit_command_job(
        module_name: str,  # Actually app_name for surreal-commands
        command_name: str,
        command_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Submit a generic command job for background processing"""
        try:
            # Ensure command modules are imported before submitting
            # This is needed because submit_command validates against local registry
            try:
                import commands.podcast_commands  # noqa: F401
            except ImportError as import_err:
                logger.error(f"Failed to import command modules: {import_err}")
                raise ValueError("Command modules not available")

            # surreal-commands expects: submit_command(app_name, command_name, args)
            cmd_id = submit_command(
                module_name,  # This is actually the app name (e.g., "open_notebook")
                command_name,  # Command name (e.g., "generate_podcast")
                command_args,  # Input data
            )
            # Convert RecordID to string if needed
            if not cmd_id:
                raise ValueError("Failed to get cmd_id from submit_command")
            cmd_id_str = str(cmd_id)
            logger.info(
                f"Submitted command job: {cmd_id_str} for {module_name}.{command_name}"
            )
            return cmd_id_str

        except Exception as e:
            logger.error(f"Failed to submit command job: {e}")
            raise

    @staticmethod
    async def get_command_status(job_id: str) -> Dict[str, Any]:
        """Get status of any command job"""
        try:
            status = await get_command_status(job_id)
            return {
                "job_id": job_id,
                "status": status.status if status else "unknown",
                "result": status.result if status else None,
                "error_message": getattr(status, "error_message", None)
                if status
                else None,
                "created": str(status.created)
                if status and hasattr(status, "created") and status.created
                else None,
                "updated": str(status.updated)
                if status and hasattr(status, "updated") and status.updated
                else None,
                "progress": getattr(status, "progress", None) if status else None,
            }
        except Exception as e:
            logger.error(f"Failed to get command status: {e}")
            raise

    @staticmethod
    async def list_command_jobs(
        module_filter: Optional[str] = None,
        command_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List command jobs with optional filtering"""
        # This will be implemented with proper SurrealDB queries
        # For now, return empty list as this is foundation phase
        return []

    @staticmethod
    async def cancel_command_job(job_id: str) -> bool:
        """Cancel a running command job"""
        try:
            # Implementation depends on surreal-commands cancellation support
            # For now, just log the attempt
            logger.info(f"Attempting to cancel job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel command job: {e}")
            raise

    @staticmethod
    async def reconcile_stale_commands(
        lease_seconds: int = STALE_COMMAND_LEASE_SECONDS,
        limit: int = 200,
        allow_bare: bool = False,
    ) -> Dict[str, Any]:
        """Flip provably-orphaned `running` commands to `failed`.

        Shutdown semantics: a task interrupted by application shutdown,
        worker crash, or machine restart must never remain falsely
        `running`. Restarted workers only resume `new` commands
        (surreal-commands worker boots from ``status = 'new'`` and its
        live listener ignores `running`), so a `running` command with
        no process capable of completing it is an orphan.

        Protection for genuine work (never blindly fail everything):
        - only `running` rows are examined (`new` jobs resume on restart);
        - rows with fresh activity (heartbeat/updated/started/created
          within the lease) are always left untouched;
        - rows with NO timestamps at all (``allow_bare=False``, the
          Tasks read path) are left untouched: mid-session a live
          worker may own them (non-heartbeat families write nothing);
        - ``allow_bare=True`` (API startup, which runs before the worker
          process starts) additionally flips timestamp-less rows, but
          ONLY under system-wide quiescence: no `running` row anywhere
          shows fresh activity, i.e. no worker generation can currently
          be alive. A single fresh heartbeat anywhere vetoes the flip.

        Never raises: reconciliation must not take down API startup or
        the Tasks read path.
        """
        from open_notebook.database.repository import (
            ensure_record_id,
            repo_query,
        )

        summary: Dict[str, Any] = {
            "checked": 0,
            "reconciled": 0,
            "reconciled_ids": [],
            "errors": [],
        }
        try:
            rows = await repo_query(
                "SELECT id, status, updated_at, started_at, created, "
                "analysis_heartbeat FROM command "
                "WHERE app = 'open_notebook' AND status = 'running' "
                "ORDER BY updated_at ASC LIMIT $limit",
                {"limit": limit},
            )
        except Exception as e:
            logger.warning(f"Stale-command reconciliation read failed: {e}")
            summary["errors"].append(str(e)[:200])
            return summary
        summary["checked"] = len(rows or [])
        now = datetime.now(timezone.utc).timestamp()
        quiescent: Optional[bool] = None
        if allow_bare and (rows or []):
            quiescent = True
            for command in rows or []:
                latest = _latest_activity(command or {})
                if latest is not None and (now - latest) < lease_seconds:
                    quiescent = False
                    break
        for command in rows or []:
            try:
                if str((command or {}).get("status")) != "running":
                    continue
                latest = _latest_activity(command or {})
                if latest is None:
                    # No liveness evidence either way. Mid-session this may
                    # be a live worker's fresh pickup (untouchable); at
                    # startup under quiescence no worker can own it.
                    if not (allow_bare and quiescent):
                        continue
                elif (now - latest) < lease_seconds:
                    continue
                command_id = str((command or {}).get("id"))
                await repo_query(
                    "UPDATE $cid SET status = $status, "
                    "error_message = $error, updated_at = time::now()",
                    {
                        "cid": ensure_record_id(command_id),
                        "status": "failed",
                        "error": (
                            "Orphaned: worker stopped without completing "
                            "(no heartbeat within lease)."
                        ),
                    },
                )
                summary["reconciled"] += 1
                summary["reconciled_ids"].append(command_id)
                logger.warning(
                    f"Reconciled stale running command {command_id} as failed"
                )
            except Exception as e:
                logger.warning(
                    f"Could not reconcile command "
                    f"{(command or {}).get('id')}: {e}"
                )
                summary["errors"].append(str(e)[:200])
        return summary
