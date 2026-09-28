"""LLM troubleshooting-knowledge service (M12).

Second, independent knowledge-generation path beside the deterministic
text-mining pipeline:

- Mining knowledge lives in the offline SQLite Troubleshooting Database
  (``api/troubleshooting_service.py`` + the
  ``maintenance-troubleshooting-engine`` package, untouched by this
  module).
- LLM-derived knowledge lives here in SurrealDB (``llm_knowledge_build``
  + ``llm_knowledge_record`` tables, migration 28). The stores never
  merge: this module never reads the mining database and never writes
  mining-shaped rows.

Pipeline per record (no embeddings anywhere — §26 is not RAG)::

    repair workbook bytes
    → deterministic row extraction (reuses repair_report_service readers)
    → LLM structured extraction (api/llm_generation.py)
    → validation (malformed JSON / missing fields / bad enums rejected)
    → semantic post-rules (closure/test phrasing is never a corrective
      action — mirrors the engine's TechnicalVerification /
      PostRepairEvent distinction without importing the engine)
    → SurrealDB persistence with DATA_SUPPORTED vs LLM_INFERRED
      provenance per item

All SurrealDB access goes through ``repo_query`` (single mock seam).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.exceptions import (
    ConfigurationError,
    InvalidInputError,
    NotFoundError,
)

TABLE_BUILD = "llm_knowledge_build"
TABLE_RECORD = "llm_knowledge_record"

#: Prompt/system contract version recorded on every build for audit.
PROMPT_VERSION = "m12-v1"

#: Build lifecycle states (mirrors the repair-run vocabulary + partial).
BUILD_QUEUED = "queued"
BUILD_RUNNING = "running"
BUILD_COMPLETED = "completed"
BUILD_FAILED = "failed"
BUILD_PARTIAL = "partial"
BUILD_CANCELLED = "cancelled"

ACTIVE_BUILD_STATUSES = (BUILD_QUEUED, BUILD_RUNNING)
TERMINAL_BUILD_STATUSES = (BUILD_COMPLETED, BUILD_FAILED, BUILD_PARTIAL, BUILD_CANCELLED)

#: surreal-commands job statuses that mean "still working".
ACTIVE_COMMAND_STATUSES = ("new", "running")

#: A queued build without a command record younger than this is a
#: submission still in flight, not a stale build (mirrors the repair
#: SUBMIT_GRACE_SECONDS pattern).
SUBMIT_GRACE_SECONDS = 300

#: A worker that stops writing without finishing is declared dead past
#: this age (mirrors RUNNING_LEASE_SECONDS; LLM builds are shorter but
#: share the conservative lease so slow providers are never killed).
RUNNING_LEASE_SECONDS = 1800

#: Provenance basis per extracted item (§7: never collapsed).
BASIS_SUPPORTED = "DATA_SUPPORTED"
BASIS_INFERRED = "LLM_INFERRED"
VALID_BASES = (BASIS_SUPPORTED, BASIS_INFERRED)

KNOWLEDGE_SOURCE_LLM = "LLM"

COMMAND_NAME = "generate_llm_knowledge"


# --- structured output contract (§6) ----------------------------------------


class LLMItem(BaseModel):
    """One extracted statement with explicit provenance."""

    text: str = Field(..., description="Extracted statement, verbatim-ish")
    basis: Literal["DATA_SUPPORTED", "LLM_INFERRED"] = Field(
        ..., description="Historical record states it vs LLM derived it"
    )
    source_quote: Optional[str] = Field(
        None, description="Supporting source span, when explicitly stated"
    )


class LLMExtraction(BaseModel):
    """Validated structured extraction for one source record (§6).

    Empty/unknown is explicit: ``symptom`` may be null and any list may
    be empty — the LLM must return those instead of inventing facts.
    """

    symptom: Optional[str] = None
    findings: List[LLMItem] = Field(default_factory=list)
    candidate_causes: List[LLMItem] = Field(default_factory=list)
    diagnostic_steps: List[LLMItem] = Field(default_factory=list)
    corrective_actions: List[LLMItem] = Field(default_factory=list)
    verification_steps: List[LLMItem] = Field(default_factory=list)
    post_repair_events: List[LLMItem] = Field(
        default_factory=list,
        description="Handover/outcome history re-filed by semantic post-rules",
    )


EXTRACTION_LIST_FIELDS = (
    "findings",
    "candidate_causes",
    "diagnostic_steps",
    "corrective_actions",
    "verification_steps",
)


# --- LLM prompt / system contract (§9) ---------------------------------------


def build_extraction_prompt(source_text: str, source_record_id: str) -> Tuple[str, str]:
    """System + user prompt for one record's structured extraction.

    Encodes the generation rules (§9) and the engine's semantic
    distinctions (§8): TechnicalVerification vs RepairAction,
    PostRepairEvent vs RepairAction, standalone ``تست شد`` as
    verification only, and closure/handover never as a corrective
    action.
    """
    system = (
        "You extract structured troubleshooting knowledge from a single "
        "historical maintenance record. Rules:\n"
        "1. Use ONLY the supplied source material. Never use outside knowledge.\n"
        "2. Do not invent components, parts, or equipment names.\n"
        "3. Do not invent measurements, parameters, or values.\n"
        "4. Do not invent corrective actions the source does not support.\n"
        "5. Administrative closure text (e.g. تحویل شد, تحویل گردید, "
        "تست و تحویل شد as handover, مشکل رفع شد, برطرف گردید) is NOT a "
        "corrective action. A standalone test note (تست شد) is a "
        "verification step, never a corrective action.\n"
        "6. Preserve source references: set source_quote to the exact "
        "source span when the information is explicitly stated.\n"
        "7. Mark every item DATA_SUPPORTED (explicitly stated in the "
        "source) or LLM_INFERRED (derived from context, not stated). "
        "Never label an inference as DATA_SUPPORTED.\n"
        "8. Return structured JSON ONLY, matching the schema. No prose, "
        "no markdown fences, no commentary.\n"
        "9. Where evidence is insufficient, return null (symptom) or [] "
        "(lists), or an item with basis LLM_INFERRED — never hallucinate "
        "a fact to fill the schema."
    )
    schema = (
        '{"symptom": string|null, "findings": [{"text": string, '
        '"basis": "DATA_SUPPORTED"|"LLM_INFERRED", "source_quote": '
        "string|null}], "
        '"candidate_causes": [...], "diagnostic_steps": [...], '
        '"corrective_actions": [...], "verification_steps": [...]}'
    )
    user = (
        f"Source record {source_record_id}:\n{source_text}\n\n"
        f"Return JSON matching this schema:\n{schema}"
    )
    return system, user


# --- validation layer (§11) ---------------------------------------------------


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop opening fence (``` or ```json) and trailing fence.
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_llm_extraction(raw: Any) -> Tuple[Optional[LLMExtraction], List[str]]:
    """Parse + validate one LLM response (never raises on bad content).

    Returns ``(extraction, errors)``: ``extraction`` is None when the
    response is malformed, misses required fields, carries invalid enum
    values, has the wrong shape, or is empty — the caller persists the
    errors traceably on the record instead of discarding them silently.
    Extra top-level keys are tolerated (forward compatibility) and
    reported as warnings inside ``errors`` with a ``warning:`` prefix
    so they stay visible without failing the record.
    """
    errors: List[str] = []
    if raw is None:
        return None, ["empty_response"]
    if not isinstance(raw, str):
        return None, ["unexpected_output_shape: response is not text"]
    text = _strip_fences(raw)
    if not text:
        return None, ["empty_response"]
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError) as e:
        return None, [f"malformed_json: {e}"]
    if isinstance(parsed, list):
        return None, ["unexpected_output_shape: top-level list, expected object"]
    if not isinstance(parsed, dict):
        return None, ["unexpected_output_shape: expected JSON object"]
    if "symptom" not in parsed:
        return None, ["missing_required_field: symptom"]
    for field in EXTRACTION_LIST_FIELDS:
        if field not in parsed:
            return None, [f"missing_required_field: {field}"]
        if parsed[field] is not None and not isinstance(parsed[field], list):
            return None, [f"unexpected_output_shape: {field} is not a list"]
    known = {"symptom"} | set(EXTRACTION_LIST_FIELDS)
    for key in sorted(set(parsed) - known):
        errors.append(f"warning: unexpected_field_ignored: {key}")
    symptom = parsed.get("symptom")
    if symptom is not None and not isinstance(symptom, str):
        return None, ["invalid_field: symptom is not a string"]
    if isinstance(symptom, str) and not symptom.strip():
        symptom = None
    items: Dict[str, List[LLMItem]] = {}
    for field in EXTRACTION_LIST_FIELDS:
        validated: List[LLMItem] = []
        for index, entry in enumerate(parsed.get(field) or []):
            if not isinstance(entry, dict):
                return None, [f"invalid_field: {field}[{index}] is not an object"]
            entry_text = entry.get("text")
            if not isinstance(entry_text, str) or not entry_text.strip():
                return None, [f"invalid_field: {field}[{index}].text is empty"]
            basis = entry.get("basis")
            if basis not in VALID_BASES:
                return None, [
                    f"invalid_enum: {field}[{index}].basis={basis!r} "
                    f"(expected DATA_SUPPORTED or LLM_INFERRED)"
                ]
            quote = entry.get("source_quote")
            if quote is not None and not isinstance(quote, str):
                return None, [
                    f"invalid_field: {field}[{index}].source_quote is not a string"
                ]
            validated.append(
                LLMItem(
                    text=entry_text.strip(),
                    basis=basis,
                    source_quote=quote.strip() if isinstance(quote, str) and quote.strip() else None,
                )
            )
        items[field] = validated
    try:
        extraction = LLMExtraction(symptom=symptom.strip() if symptom else None, **items)
    except ValidationError as e:
        return None, [f"invalid_field: {e}"]
    return extraction, errors


# --- semantic post-rules (§8: engine semantics stay authoritative) -------------

#: Closure/handover/outcome phrasing that is history, never a repair
#: action. Mirrors the engine's history-only phrases
#: (stages/repairs.py ``_HISTORY_ONLY_PHRASES`` + ``_emit_standalone_history``):
#: standalone تست شد → verification; تست و تحویل شد → verification +
#: handover event; تحویل* → handover; برطرف/رفع outcome → verification.
_CLOSURE_MARKERS = (
    "تحویل شد",
    "تحویل گردید",
    "تحویل داده شد",
    "تست و تحویل شد",
    "تست و تحویل گردید",
    "مشکل رفع شد",
    "مشکل برطرف شد",
    "برطرف گردید",
    "برطرف شد",
    "رفع گردید",
    "تست شد",
)

#: Repair verbs: when none is present alongside a closure marker, the
#: sentence carries no corrective content (deterministic safety net —
#: the prompt already forbids closure-as-action, this enforces it).
_REPAIR_VERBS = (
    "تعویض",
    "تعويض",
    "تعمیر",
    "تنظیم",
    "رگلاژ",
    "جوش",
    "سرویس",
    "روغن",
    "گریس",
    "تمیز",
    "شست",
    "بازدید",
    "تعمییر",
    "نصب",
    "مونتاژ",
    "دمونتاژ",
    "تراش",
    "سنگ",
    "جایگزین",
    "آچار",
    "بستن",
    "باز کردن",
    "لحیم",
    "سیم",
    "کابل",
    "بلبرینگ",
    "یاتاقان",
    "فیلتر",
    "تسمه",
    "پمپ",
    "موتور",
    "گیربکس",
    "شیر",
    "سنسور",
    "کنتاکتور",
    "فیوز",
    "برد",
)


def _contains_any(text: str, phrases: Tuple[str, ...]) -> bool:
    return any(marker in text for marker in phrases)


def apply_semantic_rules(extraction: LLMExtraction) -> LLMExtraction:
    """Enforce engine semantics on a validated extraction (pure).

    - A corrective action that is only closure/handover/test phrasing
      (no repair verb) is NOT a corrective action: test phrasing moves
      to ``verification_steps`` (standalone ``تست شد`` → Technical
      Verification), handover/outcome phrasing moves to
      ``post_repair_events`` — the record keeps the history, nothing is
      silently dropped.
    - Never invents: only re-files the LLM's own items.
    """
    kept_actions: List[LLMItem] = []
    verifications = list(extraction.verification_steps)
    events = list(extraction.post_repair_events)
    for action in extraction.corrective_actions:
        text = action.text
        if _contains_any(text, _CLOSURE_MARKERS) and not _contains_any(
            text, _REPAIR_VERBS
        ):
            has_test = "تست" in text
            has_handover = "تحویل" in text
            has_outcome = _contains_any(text, ("رفع", "برطرف", "مشکل"))
            # Engine parity: standalone تست شد → verification only;
            # تست و تحویل شد → verification + handover event; pure
            # handover → event only; رفع/برطرف outcome → verification.
            if has_test or has_outcome or not has_handover:
                verifications.append(
                    LLMItem(
                        text=text,
                        basis=action.basis,
                        source_quote=action.source_quote,
                    )
                )
            if has_handover:
                events.append(
                    LLMItem(
                        text=text,
                        basis=action.basis,
                        source_quote=action.source_quote,
                    )
                )
            continue
        kept_actions.append(action)
    return LLMExtraction(
        symptom=extraction.symptom,
        findings=list(extraction.findings),
        candidate_causes=list(extraction.candidate_causes),
        diagnostic_steps=list(extraction.diagnostic_steps),
        corrective_actions=kept_actions,
        verification_steps=verifications,
        post_repair_events=events,
    )


# --- deterministic record extraction (no embeddings) --------------------------


def build_record_source_text(headers: List[str], values: List[Any]) -> str:
    """Verbatim ``column: value`` lines for one workbook row.

    Empty cells are skipped; nothing is rewritten or summarized — the
    LLM input stays traceable to the original historical text.
    """
    lines: List[str] = []
    for header, value in zip(headers, values):
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        label = (header or "").strip() or "—"
        lines.append(f"{label}: {text}")
    return "\n".join(lines)


def extract_record_inputs(
    analysis_key: str, sheet: str, headers: List[str], rows: List[List[Any]]
) -> List[Dict[str, Any]]:
    """One deterministic LLM input per non-empty workbook row.

    ``source_record_id`` is ``<analysis_key>-LLMROW-<sheet>-<excel_row>``:
    stable per report (analysis_key), unique across files, 1-based Excel
    row numbers, never the filename. Rows with no text are skipped
    (recorded by the caller as warnings, not failures).
    """
    inputs: List[Dict[str, Any]] = []
    for offset, values in enumerate(rows):
        padded = list(values[: len(headers)])
        padded.extend([None] * (len(headers) - len(padded)))
        source_text = build_record_source_text(headers, padded)
        if not source_text.strip():
            continue
        excel_row = offset + 2  # +1 header row, +1 for 1-based numbering
        inputs.append(
            {
                "source_record_id": f"{analysis_key}-LLMROW-{sheet}-{excel_row}",
                "source_text": source_text,
            }
        )
    return inputs


# --- build records ------------------------------------------------------------


def _build_row(row: Dict[str, Any]) -> Dict[str, Any]:
    def _str(value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    return {
        "id": _str(row.get("id")),
        "source_report_ids": [str(item) for item in row.get("source_report_ids") or []],
        "manifest": row.get("manifest") or [],
        "status": row.get("status", BUILD_QUEUED),
        "command_id": _str(row.get("command_id")),
        "model": row.get("model"),
        "prompt_version": row.get("prompt_version"),
        "error": row.get("error"),
        "warnings": row.get("warnings") or [],
        "record_count": row.get("record_count"),
        "failed_record_count": row.get("failed_record_count"),
        "created": _str(row.get("created")),
        "started_at": _str(row.get("started_at")),
        "finished_at": _str(row.get("finished_at")),
    }


def _record_row(row: Dict[str, Any]) -> Dict[str, Any]:
    def _str(value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    return {
        "id": _str(row.get("id")),
        "build_id": _str(row.get("build_id")),
        "source_report_id": _str(row.get("source_report_id")),
        "source_record_id": row.get("source_record_id"),
        "source_text": row.get("source_text"),
        "symptom": row.get("symptom"),
        "findings": row.get("findings") or [],
        "candidate_causes": row.get("candidate_causes") or [],
        "diagnostic_steps": row.get("diagnostic_steps") or [],
        "corrective_actions": row.get("corrective_actions") or [],
        "verification_steps": row.get("verification_steps") or [],
        "post_repair_events": row.get("post_repair_events") or [],
        "record_error": row.get("record_error"),
        "created": _str(row.get("created")),
    }


def _parse_time(value: Any) -> Optional[float]:
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


def _same_report_set(left: List[str], right: List[str]) -> bool:
    return sorted(str(item) for item in left) == sorted(str(item) for item in right)


async def list_builds(limit: int = 20) -> List[Dict[str, Any]]:
    rows = await repo_query(
        f"SELECT * FROM {TABLE_BUILD} ORDER BY created DESC LIMIT $limit",
        {"limit": limit},
    )
    return [_build_row(row) for row in rows or []]


async def get_build(build_id: str) -> Dict[str, Any]:
    rows = await repo_query(
        f"SELECT * FROM {TABLE_BUILD} WHERE id = $rid",
        {"rid": ensure_record_id(build_id)},
    )
    if not rows:
        raise NotFoundError(f"Unknown LLM knowledge build: {build_id}.")
    return _build_row(rows[0])


async def _get_build_internal(build_id: str) -> Dict[str, Any]:
    rows = await repo_query(
        f"SELECT * FROM {TABLE_BUILD} WHERE id = $rid",
        {"rid": ensure_record_id(build_id)},
    )
    if not rows:
        raise NotFoundError(f"Unknown LLM knowledge build: {build_id}.")
    return rows[0]


async def create_build(
    report_ids: List[str],
    manifest: List[Dict[str, Any]],
    model: Optional[str],
) -> Dict[str, Any]:
    """Register a new build (previous builds are never touched)."""
    rows = await repo_query(
        f"CREATE {TABLE_BUILD} CONTENT {{source_report_ids: $report_ids, "
        "manifest: $manifest, status: $status, command_id: NONE, "
        "model: $model, prompt_version: $prompt, error: NONE, warnings: [], "
        "record_count: NONE, failed_record_count: NONE, created: time::now(), "
        "started_at: NONE, finished_at: NONE} RETURN AFTER",
        {
            "report_ids": [ensure_record_id(item) for item in report_ids],
            "manifest": manifest,
            "status": BUILD_QUEUED,
            "model": model,
            "prompt": PROMPT_VERSION,
        },
    )
    if not rows:
        raise RuntimeError("Failed to create LLM knowledge build")
    logger.info(f"Registered LLM knowledge build over {len(report_ids)} report(s)")
    return _build_row(rows[0])


async def attach_command(build_id: str, command_id: str) -> None:
    await repo_query(
        "UPDATE $rid SET command_id = $cid",
        {
            "rid": ensure_record_id(build_id),
            "cid": ensure_record_id(command_id),
        },
    )


async def mark_build_running(build_id: str) -> None:
    await repo_query(
        f"UPDATE $rid SET status = $status, started_at = time::now()",
        {"rid": ensure_record_id(build_id), "status": BUILD_RUNNING},
    )


async def mark_build_finished(
    build_id: str,
    *,
    status: str,
    record_count: int,
    failed_record_count: int,
    warnings: List[str],
    error: Optional[str] = None,
) -> None:
    await repo_query(
        f"UPDATE $rid SET status = $status, error = $error, "
        "record_count = $records, failed_record_count = $failed, "
        "warnings = $warnings, finished_at = time::now()",
        {
            "rid": ensure_record_id(build_id),
            "status": status,
            "error": error,
            "records": record_count,
            "failed": failed_record_count,
            "warnings": warnings,
        },
    )


async def mark_build_failed(build_id: str, error: str) -> None:
    await repo_query(
        f"UPDATE $rid SET status = $status, error = $error, "
        "finished_at = time::now()",
        {
            "rid": ensure_record_id(build_id),
            "status": BUILD_FAILED,
            "error": error[:500],
        },
    )


async def _finalize_stale_build(build: Dict[str, Any], reason: str) -> None:
    """Flip a build whose worker died to failed (never stuck in queued)."""
    build_id = str(build["id"])
    logger.warning(f"Finalizing stale LLM knowledge build {build_id}: {reason}")
    await mark_build_failed(build_id, reason)
    command_id = str(build.get("command_id")) if build.get("command_id") else None
    if command_id:
        try:
            from api import repair_report_service as reports

            command = await reports._read_command(command_id)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"Could not read orphan command {command_id}: {e}")
            command = None
        if command is not None and str(command.get("status")) == "running":
            try:
                await repo_query(
                    "UPDATE $cid SET status = $status, "
                    "error_message = $error, updated_at = time::now()",
                    {
                        "cid": ensure_record_id(command_id),
                        "status": "failed",
                        "error": "Orphaned: LLM build worker liveness expired.",
                    },
                )
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(f"Could not finalize orphan command {command_id}: {e}")


def _command_live(command: Dict[str, Any], build: Dict[str, Any]) -> bool:
    """Liveness for a build's command (mirrors the repair-run seam)."""
    status = str(command.get("status"))
    if status == "new":
        return True
    if status != "running":
        return False
    now = datetime.now(timezone.utc).timestamp()
    heartbeat = _parse_time(command.get("updated_at"))
    if heartbeat is not None:
        return (now - heartbeat) < RUNNING_LEASE_SECONDS
    started = _parse_time(build.get("started_at") or build.get("created"))
    if started is None:
        return True
    return (now - started) < RUNNING_LEASE_SECONDS


async def find_active_build_for_reports(
    report_ids: List[str],
) -> Optional[Dict[str, Any]]:
    """Latest active build over the exact same report set, if any.

    Idempotency (§20): a repeated submission while an equivalent build
    is genuinely active returns that build (router maps to 409) instead
    of creating an uncontrolled duplicate. Builds over different report
    sets are independent and never block each other. Stale builds
    (worker dead) are finalized first so they never block forever.
    """
    from api import repair_report_service as reports

    rows = await repo_query(
        f"SELECT * FROM {TABLE_BUILD} WHERE status IN $statuses "
        "ORDER BY created DESC",
        {"statuses": list(ACTIVE_BUILD_STATUSES)},
    )
    for build in rows or []:
        build_reports = [str(item) for item in build.get("source_report_ids") or []]
        if not _same_report_set(build_reports, report_ids):
            continue
        command_id = str(build.get("command_id")) if build.get("command_id") else None
        if command_id is None:
            created = _parse_time(build.get("created"))
            now = datetime.now(timezone.utc).timestamp()
            if created is None or (now - created) < SUBMIT_GRACE_SECONDS:
                return _build_row(build)
            await _finalize_stale_build(build, "The LLM worker never started.")
            continue
        try:
            command = await reports._read_command(command_id)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(
                f"Could not read command status for {command_id}: {e}"
            )
            return _build_row(build)
        if command is None:
            await _finalize_stale_build(build, "The LLM worker never started.")
            continue
        if _command_live(command, build):
            return _build_row(build)
        await _finalize_stale_build(build, "The LLM worker stopped without completing.")
    return None


# --- record persistence + queries ----------------------------------------------


def _item_dicts(items: List[LLMItem]) -> List[Dict[str, Any]]:
    return [
        {"text": item.text, "basis": item.basis, "source_quote": item.source_quote}
        for item in items
    ]


async def save_record(
    build_id: str,
    source_report_id: str,
    source_record_id: str,
    source_text: str,
    extraction: Optional[LLMExtraction],
    record_error: Optional[str],
) -> Dict[str, Any]:
    """Persist one record (validated extraction or traceable failure)."""
    payload: Dict[str, Any] = {
        "build_id": ensure_record_id(build_id),
        "source_report_id": ensure_record_id(source_report_id),
        "source_record_id": source_record_id,
        "source_text": source_text,
        "symptom": extraction.symptom if extraction else None,
        "findings": _item_dicts(extraction.findings) if extraction else [],
        "candidate_causes": _item_dicts(extraction.candidate_causes) if extraction else [],
        "diagnostic_steps": _item_dicts(extraction.diagnostic_steps) if extraction else [],
        "corrective_actions": (
            _item_dicts(extraction.corrective_actions) if extraction else []
        ),
        "verification_steps": (
            _item_dicts(extraction.verification_steps) if extraction else []
        ),
        "post_repair_events": (
            _item_dicts(extraction.post_repair_events) if extraction else []
        ),
        "record_error": record_error,
        "created": "time::now()",
    }
    fields = ", ".join(f"{key}: $val_{key}" for key in payload if key != "created")
    params = {f"val_{key}": value for key, value in payload.items() if key != "created"}
    rows = await repo_query(
        f"CREATE {TABLE_RECORD} CONTENT {{{fields}, created: time::now()}} RETURN AFTER",
        params,
    )
    if not rows:
        raise RuntimeError("Failed to persist LLM knowledge record")
    return _record_row(rows[0])


async def existing_source_record_ids(build_id: str) -> set:
    """Source records already persisted for a build (worker resume seam)."""
    rows = await repo_query(
        f"SELECT VALUE source_record_id FROM {TABLE_RECORD} WHERE build_id = $bid",
        {"bid": ensure_record_id(build_id)},
    )
    return {str(item) for item in rows or []}


async def list_records(
    build_id: str, source_report_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    if source_report_id is not None:
        rows = await repo_query(
            f"SELECT * FROM {TABLE_RECORD} WHERE build_id = $bid "
            "AND source_report_id = $sid ORDER BY source_record_id",
            {
                "bid": ensure_record_id(build_id),
                "sid": ensure_record_id(source_report_id),
            },
        )
    else:
        rows = await repo_query(
            f"SELECT * FROM {TABLE_RECORD} WHERE build_id = $bid "
            "ORDER BY source_record_id",
            {"bid": ensure_record_id(build_id)},
        )
    return [_record_row(row) for row in rows or []]


async def resolve_llm_model_id(explicit_model_id: Optional[str] = None) -> str:
    """Configured language-model ID for generation (never an embedding model).

    Explicit request wins; otherwise the transformation default (which
    falls back to chat). Raises ``ConfigurationError`` (→ HTTP 422)
    when nothing is configured — the mining path never requires this.
    """
    from open_notebook.ai.models import model_manager

    if explicit_model_id:
        return explicit_model_id
    defaults = await model_manager.get_defaults()
    model_id = (
        defaults.default_transformation_model or defaults.default_chat_model
    )
    if not model_id:
        raise ConfigurationError(
            "No language model configured for LLM knowledge generation. "
            "Please go to Manage → Models and configure a default model."
        )
    return str(model_id)


# --- orchestration ---------------------------------------------------------------


async def start_build(
    report_ids: List[str], model_id: Optional[str] = None
) -> Dict[str, Any]:
    """Validate reports, dedupe against an active equivalent, submit work.

    Raises ``BuildInProgressError`` (router maps to 409 carrying the
    live build) while an equivalent build is active; ``NotFoundError``
    for unknown reports; ``InvalidInputError`` for an empty set.
    Reports, mining knowledge, and embeddings are never touched here —
    only a new build row plus a worker command are created.
    """
    from api import repair_report_service as reports
    from api.command_service import CommandService

    cleaned = [str(item).strip() for item in report_ids or [] if str(item).strip()]
    if not cleaned:
        raise InvalidInputError("Select at least one repair report.")
    # Stable identity (record IDs, never filenames); duplicates collapse.
    seen: List[str] = []
    for item in cleaned:
        if item not in seen:
            seen.append(item)
    manifest: List[Dict[str, Any]] = []
    for report_id in seen:
        try:
            internal = await reports._get_report_internal(report_id)
        except NotFoundError:
            raise
        except Exception as e:
            raise NotFoundError(f"Unknown repair report: {report_id}.") from e
        manifest.append(
            {
                "report_id": str(internal["id"]),
                "filename": internal.get("filename"),
                "analysis_key": internal.get("analysis_key"),
            }
        )
    resolved = [entry["report_id"] for entry in manifest]

    active = await find_active_build_for_reports(resolved)
    if active is not None:
        raise BuildInProgressError(active["id"], "An equivalent LLM knowledge build is already in progress.")

    try:
        import commands.llm_knowledge_commands  # noqa: F401
    except ImportError as e:
        raise InvalidInputError("LLM knowledge worker is unavailable.") from e

    model_id = await resolve_llm_model_id(model_id)
    build = await create_build(resolved, manifest, model_id)
    try:
        command_id = await CommandService.submit_command_job(
            "open_notebook",
            COMMAND_NAME,
            {"build_id": build["id"]},
        )
    except Exception as e:
        await mark_build_failed(str(build["id"]), f"Failed to submit LLM build: {e}")
        raise
    try:
        await attach_command(str(build["id"]), command_id)
    except Exception as e:
        await mark_build_failed(str(build["id"]), f"Failed to attach LLM build: {e}")
        raise
    build["command_id"] = command_id
    logger.info(f"Submitted LLM knowledge build {build['id']}")
    return build


# --- LLM guide assembly (§15–§18) -------------------------------------------------


async def assemble_llm_guide(
    build_id: str, source_report_id: str
) -> Dict[str, Any]:
    """Records of one build + one source report as a guide (§15–§18).

    Never mixes sources: only records whose ``source_report_id``
    matches exactly are returned. Empty states are explicit
    (``no_records_for_source``), and a deleted backing report keeps its
    stable identity with ``source_deleted`` — never remapped to another
    same-named file. Provenance (§17) rides on every response; the UI
    splits historical evidence (DATA_SUPPORTED) from LLM-derived
    interpretation (LLM_INFERRED) per record.
    """
    from api import repair_report_service as reports

    build = await get_build(build_id)
    try:
        report_internal = await reports._get_report_internal(source_report_id)
        report_filename = report_internal.get("filename")
        source_deleted = False
    except NotFoundError:
        report_filename = None
        source_deleted = True
    except Exception:
        report_filename = None
        source_deleted = True

    records = await list_records(build_id, source_report_id)
    if source_deleted:
        return {
            "knowledge_source": KNOWLEDGE_SOURCE_LLM,
            "build_id": str(build["id"]),
            "model": build.get("model"),
            "prompt_version": build.get("prompt_version"),
            "source_report_id": source_report_id,
            "source_filename": None,
            "source_deleted": True,
            "records": [],
            "warnings": ["source_deleted"],
        }
    if not records:
        return {
            "knowledge_source": KNOWLEDGE_SOURCE_LLM,
            "build_id": str(build["id"]),
            "model": build.get("model"),
            "prompt_version": build.get("prompt_version"),
            "source_report_id": source_report_id,
            "source_filename": report_filename,
            "source_deleted": False,
            "records": [],
            "warnings": ["no_records_for_source"],
        }
    return {
        "knowledge_source": KNOWLEDGE_SOURCE_LLM,
        "build_id": str(build["id"]),
        "model": build.get("model"),
        "prompt_version": build.get("prompt_version"),
        "source_report_id": source_report_id,
        "source_filename": report_filename,
        "source_deleted": False,
        "records": records,
        "warnings": [],
    }


class BuildInProgressError(Exception):
    """An equivalent LLM build is active; carries the live build ID."""

    def __init__(self, build_id: str, message: str):
        super().__init__(message)
        self.build_id = build_id
