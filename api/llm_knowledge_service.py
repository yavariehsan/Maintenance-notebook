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

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
PROMPT_VERSION = "insight-v1"

#: Default output budgets (brief §10). Explicit > env > default; the
#: input token budget (llm_batching) packs requests, these cap responses.
#: Stage B's guide is substantially longer than Stage A evidence JSON.
LLM_STAGE_A_MAX_TOKENS_DEFAULT = 8000
LLM_STAGE_B_MAX_TOKENS_DEFAULT = 12000


def _resolve_positive_int(
    env_name: str, explicit: Optional[int], default: int
) -> int:
    if explicit is not None and isinstance(explicit, int) and explicit > 0:
        return explicit
    raw = os.environ.get(env_name, "").strip()
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return default


def resolve_generation_budgets(
    stage_a_max_tokens: Optional[int] = None,
    stage_b_max_tokens: Optional[int] = None,
) -> Dict[str, int]:
    """Explicit output budgets for both stages (auditable, env-tunable)."""
    return {
        "stage_a": _resolve_positive_int(
            "LLM_STAGE_A_MAX_TOKENS", stage_a_max_tokens,
            LLM_STAGE_A_MAX_TOKENS_DEFAULT),
        "stage_b": _resolve_positive_int(
            "LLM_STAGE_B_MAX_TOKENS", stage_b_max_tokens,
            LLM_STAGE_B_MAX_TOKENS_DEFAULT),
    }


def build_stage_a_preflight_prompt() -> Tuple[str, str, List[str]]:
    """One-record Stage A probe for the preflight gate (M14 §7 shape)."""
    record_id = "preflight-LLMROW-Sheet1-2"
    fields = {
        "کد فرایندی": "M3",
        "شرح درخواست": "مشکل در تعویض ابزار (تعویض ابزار)",
        "شرح تعمیر": "با nck مشکل حل شد",
        "مکانیزم خرابی": "",
        "دلیل بروز عیب": "",
        "حالت خرابی": "مشکل در تعویض ابزار (تعویض ابزار)",
    }
    records = [{"source_record_id": record_id, "fields": fields}]
    system, user = build_stage_a_prompt("M3", fields["حالت خرابی"], records)
    return system, user, [record_id]

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


def _excel_row_of(source_record_id: str) -> int:
    try:
        return int(str(source_record_id).rsplit("-", 1)[1])
    except (ValueError, IndexError):
        return 0


# --- Stage A output contract (two-stage guide generation) ----------------------


class StageARecordEvidence(BaseModel):
    """Per-record evidence within one Stage A package (brief §5.14)."""

    record_id: str
    primary_focus: str = ""
    symptoms: List[str] = Field(default_factory=list)
    observations: List[str] = Field(default_factory=list)
    mechanism: str = ""
    cause: str = ""
    diagnostic_checks: List[str] = Field(default_factory=list)
    corrective_actions: List[str] = Field(default_factory=list)
    verification: List[str] = Field(default_factory=list)
    unresolved: bool = False


class StageAFocusCategory(BaseModel):
    """Primary failure-focus category with historical shares (§5.10)."""

    name: str = ""
    record_ids: List[str] = Field(default_factory=list)
    record_count: int = 0
    percentage: float = 0.0
    subsystems: List[str] = Field(default_factory=list)
    symptoms: List[str] = Field(default_factory=list)
    components: List[str] = Field(default_factory=list)
    historical_actions: List[str] = Field(default_factory=list)
    verification_patterns: List[str] = Field(default_factory=list)


class StageAEvidencePackage(BaseModel):
    """Validated Stage A evidence package for one batch (brief §5.14)."""

    equipment: str = ""
    failure_mode: str = ""
    record_count: int = 0
    records: List[StageARecordEvidence] = Field(default_factory=list)
    focus_categories: List[StageAFocusCategory] = Field(default_factory=list)
    recurring_patterns: List[str] = Field(default_factory=list)
    unresolved_cases: List[str] = Field(default_factory=list)


STAGE_A_TOP_KEYS = (
    "equipment",
    "failure_mode",
    "record_count",
    "records",
    "focus_categories",
    "recurring_patterns",
    "unresolved_cases",
)


def _stage_a_str_list(value: Any, where: str) -> tuple:
    """Validate an optional list-of-strings field."""
    if value is None:
        return [], None
    if not isinstance(value, list):
        return None, f"invalid_field: {where} is not a list"
    cleaned = []
    for entry in value:
        if not isinstance(entry, str):
            return None, f"invalid_field: {where} has a non-string entry"
        cleaned.append(entry)
    return cleaned, None


def parse_stage_a_evidence(
    raw: Any, batch_member_ids: List[str]
) -> Tuple[Optional[StageAEvidencePackage], List[str]]:
    """Parse + validate one Stage A response (never raises on bad content).

    Fail-closed: malformed JSON (fences/prose NOT stripped — the contract
    is JSON only), missing top-level keys, non-member ``record_id``
    references, wrong shapes, or category counts exceeding the batch size
    all yield ``(None, errors)``. Unknown top-level keys are tolerated
    silently. Percentages are kept as returned — never rewritten.
    """
    members = set(str(item) for item in batch_member_ids or [])
    if not isinstance(raw, str):
        return None, ["empty_response"]
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as e:
        return None, [f"malformed_json: {e}"]
    if not isinstance(parsed, dict):
        return None, ["unexpected_output_shape: expected JSON object"]
    for key in STAGE_A_TOP_KEYS:
        if key not in parsed:
            return None, [f"missing_required_field: {key}"]
    equipment = parsed.get("equipment")
    failure_mode = parsed.get("failure_mode")
    if not isinstance(equipment, str) or not isinstance(failure_mode, str):
        return None, ["invalid_field: equipment/failure_mode must be strings"]
    record_count = parsed.get("record_count")
    if not isinstance(record_count, int) or isinstance(record_count, bool):
        return None, ["invalid_field: record_count is not an integer"]
    if not isinstance(parsed.get("records"), list):
        return None, ["invalid_field: records is not a list"]
    records: List[StageARecordEvidence] = []
    for index, entry in enumerate(parsed["records"]):
        where = f"records[{index}]"
        if not isinstance(entry, dict):
            return None, [f"invalid_field: {where} is not an object"]
        rid = entry.get("record_id")
        if not isinstance(rid, str) or not rid.strip() or rid not in members:
            return None, [
                f"invalid_field: {where}.record_id is not a batch member"
            ]
        checked: Dict[str, Any] = {"record_id": rid}
        for field in ("symptoms", "observations", "diagnostic_checks",
                      "corrective_actions", "verification"):
            cleaned, error = _stage_a_str_list(
                entry.get(field, []), f"{where}.{field}")
            if error is not None:
                return None, [error]
            checked[field] = cleaned
        for field in ("primary_focus", "mechanism", "cause"):
            value = entry.get(field, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                return None, [f"invalid_field: {where}.{field} is not a string"]
            checked[field] = value
        unresolved = entry.get("unresolved", False)
        if not isinstance(unresolved, bool):
            return None, [f"invalid_field: {where}.unresolved is not a boolean"]
        checked["unresolved"] = unresolved
        try:
            records.append(StageARecordEvidence(**checked))
        except ValidationError as e:
            return None, [f"invalid_field: {e}"]
    if not isinstance(parsed.get("focus_categories"), list):
        return None, ["invalid_field: focus_categories is not a list"]
    categories: List[StageAFocusCategory] = []
    counted = 0
    for index, entry in enumerate(parsed["focus_categories"]):
        where = f"focus_categories[{index}]"
        if not isinstance(entry, dict):
            return None, [f"invalid_field: {where} is not an object"]
        name = entry.get("name", "")
        if name is None:
            name = ""
        if not isinstance(name, str):
            return None, [f"invalid_field: {where}.name is not a string"]
        ref_ids = entry.get("record_ids", [])
        if not isinstance(ref_ids, list) or any(
                not isinstance(item, str) for item in ref_ids):
            return None, [f"invalid_field: {where}.record_ids is not a string list"]
        unknown = [item for item in ref_ids if item not in members]
        if unknown:
            return None, [
                f"invalid_field: {where}.record_id references outside the batch"
            ]
        count = entry.get("record_count", 0)
        if not isinstance(count, int) or isinstance(count, bool):
            return None, [f"invalid_field: {where}.record_count is not an integer"]
        percentage = entry.get("percentage", 0)
        if isinstance(percentage, bool) or not isinstance(percentage, (int, float)):
            return None, [f"invalid_field: {where}.percentage is not a number"]
        checked_cat: Dict[str, Any] = {
            "name": name, "record_ids": list(ref_ids),
            "record_count": count, "percentage": float(percentage),
        }
        for field in ("subsystems", "symptoms", "components",
                      "historical_actions", "verification_patterns"):
            cleaned, error = _stage_a_str_list(
                entry.get(field, []), f"{where}.{field}")
            if error is not None:
                return None, [error]
            checked_cat[field] = cleaned
        counted += count
        try:
            categories.append(StageAFocusCategory(**checked_cat))
        except ValidationError as e:
            return None, [f"invalid_field: {e}"]
    if counted > len(members):
        return None, [
            f"count_inconsistency: category record_counts sum to {counted} "
            f"over {len(members)} batch records"
        ]
    recurring, error = _stage_a_str_list(
        parsed.get("recurring_patterns", []), "recurring_patterns")
    if error is not None:
        return None, [error]
    unresolved_cases, error = _stage_a_str_list(
        parsed.get("unresolved_cases", []), "unresolved_cases")
    if error is not None:
        return None, [error]
    try:
        package = StageAEvidencePackage(
            equipment=equipment, failure_mode=failure_mode,
            record_count=record_count, records=records,
            focus_categories=categories, recurring_patterns=recurring,
            unresolved_cases=unresolved_cases,
        )
    except ValidationError as e:
        return None, [f"invalid_field: {e}"]
    return package, []


def parse_stage_a_preflight(raw: Any) -> Tuple[bool, List[str]]:
    """Minimal provider-capability check for preflight (never semantic).

    Verifies only that the provider/model returned a structurally
    parseable JSON object shaped like evidence: a ``records`` list with
    at least one entry carrying a string ``record_id``. Everything else
    — array contents, categories, percentages, unresolved cases — is
    deliberately ignored: preflight tests that the generation path works
    (connectivity, model resolution, JSON mode, parsing), not that an
    arbitrary sample satisfies the full Stage A evidence semantics.
    Real Stage A outputs are still validated by ``parse_stage_a_evidence``.
    """
    if not isinstance(raw, str):
        return False, ["empty_response"]
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as e:
        return False, [f"malformed_json: {e}"]
    if not isinstance(parsed, dict):
        return False, ["unexpected_output_shape: expected JSON object"]
    records = parsed.get("records")
    if records is None:
        return False, ["missing_required_field: records"]
    if not isinstance(records, list) or not records:
        return False, ["invalid_field: records must be a non-empty list"]
    for index, entry in enumerate(records):
        if not isinstance(entry, dict):
            return False, [f"invalid_field: records[{index}] is not an object"]
        rid = entry.get("record_id")
        if not isinstance(rid, str) or not rid.strip():
            return False, [f"invalid_field: records[{index}].record_id is not a string"]
    return True, []




# --- Stage A six-field contract (two-stage guide generation) -------------------
#
# Stage A receives EXACTLY six workbook fields per record. No other column
# may enter the prompt. Internal record IDs ride alongside for provenance;
# they are metadata, not a seventh field.


#: The six Stage A source fields, in contract order (brief §2).
STAGE_A_FIELDS: tuple = (
    "کد فرایندی",
    "شرح درخواست",
    "شرح تعمیر",
    "مکانیزم خرابی",
    "دلیل بروز عیب",
    "حالت خرابی",
)


def extract_stage_a_values(
    headers: List[str], values: List[Any]
) -> Dict[str, str]:
    """Six faithful field values for one workbook row.

    Missing columns, ``None`` and blanks all yield ``""`` — never a
    replacement, never a rewrite. Values are stripped, not normalized.
    """
    padded = list(values[: len(headers)])
    padded.extend([None] * (len(headers) - len(padded)))
    positional: Dict[str, Any] = {}
    for pos, header in enumerate(headers):
        label = (header or "").strip()
        if label and label not in positional:
            positional[label] = padded[pos]
    extracted: Dict[str, str] = {}
    for field in STAGE_A_FIELDS:
        raw = positional.get(field)
        if raw is None:
            extracted[field] = ""
            continue
        extracted[field] = str(raw)
    return extracted


def serialize_stage_a_record(values: Dict[str, str]) -> str:
    """Six ``header: value`` lines in contract order; blanks stay empty."""
    return "\n".join(f"{field}: {values.get(field, '')}" for field in STAGE_A_FIELDS)


STAGE_A_SYSTEM_PROMPT = (
    "You are a maintenance-history analysis engine.\n"
    "\n"
    "Your task is to analyze historical maintenance records for ONE equipment unit and ONE failure mode and extract evidence that will later be used to construct a practical maintenance troubleshooting guide.\n"
    "\n"
    "The supplied historical records are the ONLY factual source of truth.\n"
    "\n"
    "## 1. SOURCE OF TRUTH\n"
    "\n"
    "Use only the information explicitly contained in the supplied records.\n"
    "\n"
    "Do not use:\n"
    "\n"
    "* general engineering knowledge;\n"
    "* textbook knowledge;\n"
    "* manufacturer knowledge;\n"
    "* internet knowledge;\n"
    "* knowledge about similar machines;\n"
    "* knowledge from other equipment;\n"
    "* knowledge from other failure modes;\n"
    "* Text Mining results;\n"
    "* canonicalized causes or actions;\n"
    "* assumptions about how the machine should normally work.\n"
    "\n"
    "Do not invent components, sensors, mechanisms, alarms, parameters, measurements, thresholds, causes, repair actions, or verification procedures.\n"
    "\n"
    "## 2. INPUT FIELDS\n"
    "\n"
    "Every historical record contains exactly these six source fields:\n"
    "\n"
    "1. کد فرایندی\n"
    "2. شرح درخواست\n"
    "3. شرح تعمیر\n"
    "4. مکانیزم خرابی\n"
    "5. دلیل بروز عیب\n"
    "6. حالت خرابی\n"
    "\n"
    "Treat the values exactly as historical evidence.\n"
    "\n"
    "The semantic role of each field is:\n"
    "\n"
    "* کد فرایندی = equipment identity\n"
    "* شرح درخواست = reported symptom or problem\n"
    "* شرح تعمیر = observed condition, diagnostic activity, corrective action, adjustment, replacement, test, or outcome\n"
    "* مکانیزم خرابی = recorded technical failure mechanism or affected subsystem\n"
    "* دلیل بروز عیب = recorded historical cause classification\n"
    "* حالت خرابی = failure-mode scope\n"
    "\n"
    "## 3. RECORD-LEVEL EVIDENCE\n"
    "\n"
    "For every record, identify:\n"
    "\n"
    "* reported symptom(s);\n"
    "* observed condition(s);\n"
    "* affected subsystem/component;\n"
    "* explicit cause;\n"
    "* diagnostic checks;\n"
    "* corrective action;\n"
    "* adjustment;\n"
    "* replacement;\n"
    "* verification/test;\n"
    "* unresolved status;\n"
    "* any explicit alarm, sensor, pocket, tool, position, parameter, or other technical identifier.\n"
    "\n"
    "Preserve uncertainty.\n"
    "\n"
    "If the record says that no fault was found, do not convert that into a confirmed cause.\n"
    "\n"
    "If the record says that the cause was unknown or not identified, preserve it as unresolved.\n"
    "\n"
    "## 4. CROSS-RECORD SYNTHESIS\n"
    "\n"
    "Analyze all records in this batch collectively.\n"
    "\n"
    "Identify recurring:\n"
    "\n"
    "* symptoms;\n"
    "* affected subsystems;\n"
    "* components;\n"
    "* causes;\n"
    "* diagnostic checks;\n"
    "* corrective actions;\n"
    "* verification patterns.\n"
    "\n"
    "Semantically equivalent observations may be consolidated.\n"
    "\n"
    "Do not merge technically different mechanisms merely because they appear related.\n"
    "\n"
    "## 5. HISTORICAL EVIDENCE VS INFERENCE\n"
    "\n"
    "Classify every extracted fact as one of:\n"
    "\n"
    "DATA_SUPPORTED\n"
    "\n"
    "* explicitly stated in at least one supplied record.\n"
    "\n"
    "CROSS_RECORD_SUPPORTED\n"
    "\n"
    "* a recurring pattern supported by multiple supplied records.\n"
    "\n"
    "OPERATIONAL_SYNTHESIS\n"
    "\n"
    "* an ordering or troubleshooting sequence created by organizing documented historical checks/actions without introducing new technical facts.\n"
    "\n"
    "UNRESOLVED\n"
    "\n"
    "* the records do not establish a cause.\n"
    "\n"
    "Never represent an inference as an explicitly documented fact.\n"
    "\n"
    "## 6. CORRECTIVE ACTIONS\n"
    "\n"
    "Only actions supported by the historical records may be included.\n"
    "\n"
    "A historical action may be converted into conditional technician language.\n"
    "\n"
    "Examples:\n"
    "\n"
    "Historical:\n"
    "\"سنسور تنظیم شد\"\n"
    "\n"
    "Acceptable synthesis:\n"
    "\"سنسور بررسی و در صورت نیاز تنظیم شود.\"\n"
    "\n"
    "Historical:\n"
    "\"پاکت معیوب تعویض گردید\"\n"
    "\n"
    "Acceptable synthesis:\n"
    "\"پاکت مشکوک بررسی و در صورت تأیید خرابی تعویض شود.\"\n"
    "\n"
    "Do not convert every historical action into a mandatory action.\n"
    "\n"
    "Do not invent actions.\n"
    "\n"
    "## 7. TROUBLESHOOTING SEQUENCING\n"
    "\n"
    "When several historical records document different checks and repairs, organize them into a practical diagnostic progression.\n"
    "\n"
    "Prefer this general logic only when supported by the records:\n"
    "\n"
    "1. preserve the failure condition;\n"
    "2. identify where the failure stopped;\n"
    "3. perform direct visual/mechanical checks;\n"
    "4. check sensors and feedback;\n"
    "5. check pneumatic/mechanical actuation where historically relevant;\n"
    "6. inspect the affected subsystem;\n"
    "7. check control/parameter/sequence causes where historically documented;\n"
    "8. apply the supported corrective action;\n"
    "9. verify the repair.\n"
    "\n"
    "This is a synthesis framework, not permission to introduce unsupported technical procedures.\n"
    "\n"
    "## 8. HISTORICAL FAILURE-FOCUS CATEGORIES\n"
    "\n"
    "Identify technical focus categories only from evidence in the records.\n"
    "\n"
    "Potential category names may include:\n"
    "\n"
    "* Tool Pocket / Magazine\n"
    "* Gripper / Clamping\n"
    "* Sensors / Feedback\n"
    "* Door System\n"
    "* Pneumatic System\n"
    "* Control / Software / Parameter\n"
    "\n"
    "These are examples, not mandatory categories.\n"
    "\n"
    "If the records support another category, use it.\n"
    "\n"
    "If a record cannot be assigned confidently, classify it as Unknown / Unresolved.\n"
    "\n"
    "## 9. PRIMARY CATEGORY ASSIGNMENT\n"
    "\n"
    "For historical share calculations, each record must have exactly ONE primary failure-focus category.\n"
    "\n"
    "Use this hierarchy:\n"
    "\n"
    "1. explicit failure mechanism;\n"
    "2. explicit failed component or subsystem in شرح تعمیر;\n"
    "3. explicit symptom strongly identifying the affected subsystem;\n"
    "4. Unknown / Unresolved when evidence is insufficient.\n"
    "\n"
    "Secondary observations may be preserved, but they must not cause the same record to be counted twice in historical shares.\n"
    "\n"
    "## 10. HISTORICAL COUNTS\n"
    "\n"
    "For every primary category, preserve:\n"
    "\n"
    "* record count;\n"
    "* percentage of all supplied records;\n"
    "* supporting record IDs.\n"
    "\n"
    "The denominator is the total number of supplied records.\n"
    "\n"
    "One record may contribute only once to the primary-category denominator.\n"
    "\n"
    "Percentages must be calculated from actual record counts.\n"
    "\n"
    "Do not fabricate percentages.\n"
    "\n"
    "## 11. PRIORITY\n"
    "\n"
    "Priority is historical, not speculative.\n"
    "\n"
    "A category may receive a higher priority because it has:\n"
    "\n"
    "* greater historical frequency;\n"
    "* repeated occurrence;\n"
    "* explicit failure evidence;\n"
    "* repeated corrective actions;\n"
    "* strong symptom association.\n"
    "\n"
    "Do not claim that a category is \"most likely\" merely because it is technically plausible.\n"
    "\n"
    "Use historical language such as:\n"
    "\n"
    "* بیشترین تکرار تاریخی\n"
    "* در سوابق متعدد مشاهده شده\n"
    "* در این سوابق با این نشانه همراه بوده\n"
    "\n"
    "## 12. VERIFICATION\n"
    "\n"
    "Extract only documented verification patterns.\n"
    "\n"
    "Examples include:\n"
    "\n"
    "* test and handover;\n"
    "* repeated tool changes;\n"
    "* testing multiple tools;\n"
    "* testing after adjustment;\n"
    "* checking that the alarm does not recur.\n"
    "\n"
    "Do not invent a required number of test cycles.\n"
    "\n"
    "## 13. UNKNOWN CASES\n"
    "\n"
    "Keep unresolved cases explicitly separate.\n"
    "\n"
    "Examples:\n"
    "\n"
    "* cause not identified;\n"
    "* no fault found;\n"
    "* failure not reproduced;\n"
    "* insufficient evidence.\n"
    "\n"
    "Never force an unresolved record into a specific cause.\n"
    "\n"
    "## 14. OUTPUT\n"
    "\n"
    "Return JSON only.\n"
    "\n"
    "The JSON is an intermediate evidence package, not the final technician guide.\n"
    "\n"
    "Use this structure:\n"
    "\n"
    "{\n"
    "\"equipment\": \"...\",\n"
    "\"failure_mode\": \"...\",\n"
    "\"record_count\": 0,\n"
    "\"records\": [\n"
    "{\n"
    "\"record_id\": \"...\",\n"
    "\"primary_focus\": \"...\",\n"
    "\"symptoms\": [],\n"
    "\"observations\": [],\n"
    "\"mechanism\": \"...\",\n"
    "\"cause\": \"...\",\n"
    "\"diagnostic_checks\": [],\n"
    "\"corrective_actions\": [],\n"
    "\"verification\": [],\n"
    "\"unresolved\": false\n"
    "}\n"
    "],\n"
    "\"focus_categories\": [\n"
    "{\n"
    "\"name\": \"...\",\n"
    "\"record_ids\": [],\n"
    "\"record_count\": 0,\n"
    "\"percentage\": 0,\n"
    "\"subsystems\": [],\n"
    "\"symptoms\": [],\n"
    "\"components\": [],\n"
    "\"historical_actions\": [],\n"
    "\"verification_patterns\": []\n"
    "}\n"
    "],\n"
    "\"recurring_patterns\": [],\n"
    "\"unresolved_cases\": []\n"
    "}\n"
    "\n"
    "All percentages must be based only on the records in this batch.\n"
    "\n"
    "Preserve record IDs exactly.\n"
    "\n"
    "Do not return prose outside the JSON.\n"
    "\n"
    "Do not return markdown.\n"
    "\n"
    "Do not cite knowledge outside the supplied records."
)


def serialize_stage_a_records(
    records: List[Dict[str, Any]],
) -> str:
    """Deterministic serialization of one batch's six-field records."""
    blocks = []
    for item in records:
        fields = item.get("fields") or {}
        block = f"Record {item['source_record_id']}:\n" + \
            serialize_stage_a_record(fields)
        blocks.append(block)
    return "\n\n".join(blocks)


def build_stage_a_user_body(
    equipment: str,
    failure_mode: str,
    records: List[Dict[str, Any]],
) -> str:
    """User head + serialized records (no schema footer)."""
    return (
        "Analyze the following historical maintenance records.\n"
        "\n"
        f"Equipment:\n{equipment}\n"
        "\n"
        f"Failure Mode:\n{failure_mode}\n"
        "\n"
        f"Batch record count:\n{len(records)}\n"
        "\n"
        "The following records are the complete source material for this batch.\n"
        "\n"
        "Each record contains exactly these six fields:\n"
        "\n"
        "* کد فرایندی\n"
        "* شرح درخواست\n"
        "* شرح تعمیر\n"
        "* مکانیزم خرابی\n"
        "* دلیل بروز عیب\n"
        "* حالت خرابی\n"
        "\n"
        "Historical records:\n"
        "\n"
        f"{serialize_stage_a_records(records)}"
    )


_STAGE_A_USER_SUFFIX = (
    "\n"
    "\n"
    "Analyze the records collectively according to the system instructions.\n"
    "\n"
    "Return the intermediate evidence package as JSON only."
)


def build_stage_a_prompt(
    equipment: str,
    failure_mode: str,
    records: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """System + user prompt for one Stage A batch (brief §5 verbatim)."""
    user = build_stage_a_user_body(equipment, failure_mode, records) + \
        _STAGE_A_USER_SUFFIX
    return STAGE_A_SYSTEM_PROMPT, user


def _enrich_stage_a_rows(
    analysis_key: str,
    sheet: str,
    headers: List[str],
    rows: List[List[Any]],
) -> List[Dict[str, Any]]:
    """Shared enrichment: six-field rows grouped later by scope or batch.

    Skips all-blank rows, tags equipment + normalized failure mode, and
    sorts by Excel row for deterministic order. Internal record IDs ride
    alongside for provenance; they are metadata, not a seventh field.
    """
    from api import llm_batching as batching

    enriched: List[Dict[str, Any]] = []
    for offset, values in enumerate(rows):
        padded = list(values[: len(headers)])
        padded.extend([None] * (len(headers) - len(padded)))
        fields = extract_stage_a_values(headers, padded)
        if not any(str(value).strip() for value in fields.values()):
            continue
        excel_row = offset + 2  # +1 header row, +1 for 1-based numbering
        equipment = batching.equipment_key(fields["کد فرایندی"])
        failure_mode = batching.failure_mode_key(fields["حالت خرابی"])
        enriched.append({
            "source_record_id": f"{analysis_key}-LLMROW-{sheet}-{excel_row}",
            "equipment": equipment,
            "failure_mode": failure_mode,
            "fields": fields,
        })
    enriched.sort(key=lambda item: _excel_row_of(str(item["source_record_id"])))
    return enriched


def scope_id_for(analysis_key: str, equipment: str, failure_mode: str) -> str:
    """Deterministic scope ID for one (Equipment, Failure Mode) group."""
    digest = hashlib.sha1(
        f"{equipment}\x00{failure_mode}".encode("utf-8")).hexdigest()[:8]
    return f"{analysis_key}-LLMSCOPE-{digest}"


def plan_scope_insights(
    analysis_key: str,
    sheet: str,
    headers: List[str],
    rows: List[List[Any]],
) -> List[Dict[str, Any]]:
    """One insight scope per (equipment, normalized failure mode).

    Unlike batch planning, a scope is NEVER split: every member record of
    the semantic group belongs to exactly one scope plan, in Excel-row
    order. Different equipment or failure modes never share a scope.
    """
    enriched = _enrich_stage_a_rows(analysis_key, sheet, headers, rows)
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for item in enriched:
        groups.setdefault((item["equipment"], item["failure_mode"]), []).append(item)
    plans: List[Dict[str, Any]] = []
    for (equipment, failure_mode), members in groups.items():
        member_ids = [str(item["source_record_id"]) for item in members]
        plans.append({
            "scope_id": scope_id_for(analysis_key, str(equipment),
                                     str(failure_mode)),
            "equipment": equipment,
            "failure_mode": failure_mode,
            "record_count": len(members),
            "source_record_ids": member_ids,
        })
    return plans


def plan_scope_records(
    scope: Dict[str, Any],
    headers: List[str],
    rows: List[List[Any]],
) -> List[Dict[str, Any]]:
    """Re-resolve a scope's member six-field records (worker + tests)."""
    return plan_stage_a_records(scope, headers, rows)


#: Required marker: the practical troubleshooting sequence (§4.1).
#: A response without it is not a troubleshooting insight.
INSIGHT_SECTION_SEQUENCE = "# ترتیب پیشنهادی تعمیرکار"

#: Remaining markers (§4.2–§4.3 + unresolved cases). Missing ones are
#: recorded as warnings — the guide is still persisted as-is.
INSIGHT_SECTION_CATEGORIES = "# دسته‌بندی کانون‌های اصلی خرابی"
INSIGHT_SECTION_TABLE = "راهنمای کاربردی تعمیر:"
INSIGHT_SECTION_UNKNOWN = "### موارد نامشخص / بدون علت قطعی"


INSIGHT_SYSTEM_PROMPT = (
    "You are a maintenance troubleshooting assistant.\n"
    "\n"
    "Your task is to synthesize the supplied historical maintenance records for ONE equipment unit and ONE failure mode into a practical Persian troubleshooting guide.\n"
    "\n"
    "## 1. SOURCE OF TRUTH\n"
    "\n"
    "Use only the information explicitly contained in the supplied records.\n"
    "\n"
    "Do not use general engineering knowledge, textbook knowledge, manufacturer knowledge, internet knowledge, knowledge about similar machines, other equipment, other failure modes, Text Mining results, or assumptions about how the machine should normally work.\n"
    "\n"
    "Do not invent components, sensors, mechanisms, alarms, parameters, measurements, thresholds, causes, repair actions, or verification procedures.\n"
    "\n"
    "## 2. INPUT FIELDS\n"
    "\n"
    "Every historical record contains exactly these six source fields:\n"
    "\n"
    "1. کد فرایندی\n"
    "2. شرح درخواست\n"
    "3. شرح تعمیر\n"
    "4. مکانیزم خرابی\n"
    "5. دلیل بروز عیب\n"
    "6. حالت خرابی\n"
    "\n"
    "Treat the values exactly as historical evidence. Blank values mean the record does not establish that information.\n"
    "\n"
    "## 3. SYNTHESIS\n"
    "\n"
    "Analyze all records in this scope collectively. Repeated historical evidence — the same symptom, cause, check, or action appearing in several records — may be synthesized into a single troubleshooting step.\n"
    "\n"
    "Organize the documented checks and repairs into a practical diagnostic progression: preserve the failure condition, identify where the failure stopped, perform direct visual and mechanical checks first, then check sensors and feedback, pneumatic and mechanical actuation, gripper and clamping, the door system, pocket and magazine and tool mapping where historically documented, and control, parameter, or software causes only where historically documented. Verify the repair at the end.\n"
    "\n"
    "This is a synthesis framework, not permission to introduce unsupported technical procedures. The result must be operational and useful, not a record-by-record summary.\n"
    "\n"
    "## 4. HISTORICAL SHARES\n"
    "\n"
    "Derive every count and share from the supplied records only: count how many records support each focus area or cause, divide by the total number of supplied records, and report the result. Each record contributes only once to a share denominator.\n"
    "\n"
    "Do not fabricate percentages. Do not invent counts.\n"
    "\n"
    "## 5. UNCERTAINTY\n"
    "\n"
    "Keep unresolved cases explicitly separate. If the records do not establish a cause, say so. Never force an unresolved record into a specific cause. If a record says that no fault was found, do not convert that into a confirmed cause.\n"
    "\n"
    "A historical action may be converted into conditional technician language without introducing new technical facts.\n"
    "\n"
    "## 6. REQUIRED FINAL FORMAT\n"
    "\n"
    "Write the entire final answer in Persian. Return exactly the following structure.\n"
    "\n"
    "# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی\n"
    "\n"
    "(practical ordered troubleshooting sequence grounded in the supplied evidence)\n"
    "\n"
    "# دسته‌بندی کانون‌های اصلی خرابی {equipment}\n"
    "\n"
    "| کانون اصلی | زیرمجموعه‌ها | علائم شاخص | قطعاتی که باید در این کانون بررسی شوند | سهم تاریخی |\n"
    "\n"
    "(one row per evidence-supported focus area; shares computed from the supplied records)\n"
    "\n"
    "راهنمای کاربردی تعمیر:\n"
    "\n"
    "| اولویت بررسی | علت / کانون محتمل | سهم در سوابق | نشانه اصلی | اثر خرابی | اقدام پیشنهادی |\n"
    "\n"
    "(priority-oriented troubleshooting table grounded in the supplied evidence)\n"
    "\n"
    "### موارد نامشخص / بدون علت قطعی\n"
    "\n"
    "(unresolved historical cases; only what the records establish)\n"
    "\n"
    "Do not add any other top-level sections. Do not return JSON. Do not ask the user to provide additional input. Return only the final Persian guide."
)


def build_insight_prompt(
    equipment: str,
    failure_mode: str,
    records: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """System + user prompt for one direct scope insight (§3–§4)."""
    user = (
        "Generate the final operational troubleshooting guide for:\n"
        "\n"
        f"Equipment:\n{equipment}\n"
        "\n"
        f"Failure Mode:\n{failure_mode}\n"
        "\n"
        f"Total historical records:\n{len(records)}\n"
        "\n"
        "The following records are the complete historical evidence "
        "for this Equipment + Failure Mode.\n"
        "\n"
        "Each record contains exactly these six fields:\n"
        "\n"
        "* کد فرایندی\n"
        "* شرح درخواست\n"
        "* شرح تعمیر\n"
        "* مکانیزم خرابی\n"
        "* دلیل بروز عیب\n"
        "* حالت خرابی\n"
        "\n"
        "Historical records:\n"
        "\n"
        f"{serialize_stage_a_records(records)}"
        "\n"
        "\n"
        "Synthesize all supplied records according to the system instructions.\n"
        "\n"
        "Return only the final Persian operational troubleshooting guide."
    )
    return INSIGHT_SYSTEM_PROMPT, user


def validate_insight_markdown(
    markdown: Any,
) -> Tuple[bool, List[str], List[str]]:
    """Validate a direct insight response without rewriting it.

    Returns ``(ok, problems, warnings)``. Empty responses and responses
    missing the troubleshooting sequence are invalid and must never be
    persisted; other missing sections are warnings only. The content
    itself is never modified — it is stored as-is or not at all.
    """
    if not isinstance(markdown, str) or not markdown.strip():
        return False, ["empty_insight"], []
    if INSIGHT_SECTION_SEQUENCE not in markdown:
        return False, ["missing_section: troubleshooting_sequence"], []
    warnings: List[str] = []
    for marker in (INSIGHT_SECTION_CATEGORIES, INSIGHT_SECTION_TABLE,
                   INSIGHT_SECTION_UNKNOWN):
        if marker not in markdown:
            warnings.append(f"missing_section: {marker[:24]}")
    return True, [], warnings


def plan_stage_a_batches(
    analysis_key: str,
    sheet: str,
    headers: List[str],
    rows: List[List[Any]],
    max_records: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Deterministic Stage A batch plans for one report's workbook content."""
    from api import llm_batching as batching

    enriched = _enrich_stage_a_rows(analysis_key, sheet, headers, rows)

    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for item in enriched:
        groups.setdefault((item["equipment"], item["failure_mode"]), []).append(item)
    plans: List[Dict[str, Any]] = []
    for (equipment, failure_mode), members in groups.items():
        def _group_prefix(
            accumulated: List[Dict[str, Any]],
            _eq: str = str(equipment),
            _fm: str = str(failure_mode),
        ) -> str:
            return build_stage_a_user_body(_eq, _fm, accumulated)

        for plan in batching.plan_batches(
            members, STAGE_A_SYSTEM_PROMPT, _group_prefix,
            _STAGE_A_USER_SUFFIX, max_records=max_records,
            max_tokens=max_tokens,
        ):
            plans.append(plan)
    return plans


def plan_stage_a_records(
    plan: Dict[str, Any],
    headers: List[str],
    rows: List[List[Any]],
) -> List[Dict[str, Any]]:
    """Re-resolve a plan's member six-field records (worker + tests)."""
    ordered: List[Dict[str, Any]] = []
    for rid in plan.get("source_record_ids") or []:
        row_no = _excel_row_of(str(rid))
        fields: Dict[str, str] = {field: "" for field in STAGE_A_FIELDS}
        if 2 <= row_no < len(rows) + 2:
            values = list(rows[row_no - 2][: len(headers)])
            values.extend([None] * (len(headers) - len(values)))
            fields = extract_stage_a_values(headers, values)
        if any(str(value).strip() for value in fields.values()):
            ordered.append({"source_record_id": str(rid), "fields": fields})
    return ordered


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
        "stage_a_evidence": row.get("stage_a_evidence"),
        "record_error": row.get("record_error"),
        "created": _str(row.get("created")),
        # Batch provenance (M19; absent on legacy per-record rows).
        "batch_index": row.get("batch_index"),
        "equipment": row.get("equipment"),
        "failure_mode": row.get("failure_mode"),
        "batch_record_ids": row.get("batch_record_ids") or [],
        "est_input_tokens": row.get("est_input_tokens"),
        "batch_config": row.get("batch_config") or {},
        "oversized": bool(row.get("oversized") or False),
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
    if not report_ids or not manifest:
        raise InvalidInputError(
            "Cannot create an LLM knowledge build with no reports."
        )
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
    stored = _build_row(rows[0])
    if not stored["source_report_ids"] or not stored["manifest"]:
        # Defense in depth (campact): a schemafull table silently drops
        # array values on SurrealDB 2.6.5, so the stored row can come
        # back empty despite non-empty input. Fail the orphan explicitly
        # (never a lingering queued row) and refuse it BEFORE any worker
        # command is submitted — a build without its report set could
        # never execute.
        message = (
            "LLM knowledge build was not persisted with its report set "
            "(source_report_ids/manifest came back empty). The database "
            "schema is dropping array values; refusing to submit a build "
            "that could never execute."
        )
        build_id = str(stored["id"])
        logger.error(f"LLM knowledge build {build_id}: {message}")
        try:
            await mark_build_failed(build_id, message)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"Could not mark dropped LLM build failed: {e}")
        raise RuntimeError(message)
    logger.info(f"Registered LLM knowledge build over {len(report_ids)} report(s)")
    return stored


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
            if str(build.get("status")) == BUILD_RUNNING:
                # Inline execution (analysis worker, no command row):
                # liveness comes from started_at + the worker lease, not
                # the submit grace — slow providers must never be
                # declared stale mid-run.
                started = _parse_time(build.get("started_at"))
                now = datetime.now(timezone.utc).timestamp()
                if started is None or (now - started) < RUNNING_LEASE_SECONDS:
                    return _build_row(build)
                await _finalize_stale_build(
                    build, "The LLM worker stopped without completing.")
                continue
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


async def find_latest_build_covering_report(
    report_id: str,
) -> Optional[Dict[str, Any]]:
    """Latest build (any status) covering one report, newest first.

    Used to surface per-report language-model analysis status: the newest
    build whose ``source_report_ids`` contain the report determines what
    the repair table shows. Returns None when no build covers the report.
    """
    rows = await repo_query(
        f"SELECT * FROM {TABLE_BUILD} ORDER BY created DESC",
    )
    wanted = str(report_id)
    for build in rows or []:
        build_reports = [str(item) for item in build.get("source_report_ids") or []]
        if wanted in build_reports:
            return _build_row(build)
    return None


async def find_latest_finished_build_for_reports(
    report_ids: List[str],
) -> Optional[Dict[str, Any]]:
    """Latest finished (completed/partial) build over the exact same set.

    Lets a retried analysis reuse knowledge that already exists instead
    of executing a duplicate full build — the active-build guard only
    covers queued/running builds, so a crash between LLM completion and
    run completion would otherwise build everything twice. Failed builds
    are NOT reused: a new analysis is a fresh chance for generation.
    """
    rows = await repo_query(
        f"SELECT * FROM {TABLE_BUILD} WHERE status IN $statuses "
        "ORDER BY created DESC",
        {"statuses": [BUILD_COMPLETED, BUILD_PARTIAL]},
    )
    for build in rows or []:
        build_reports = [str(item) for item in build.get("source_report_ids") or []]
        if _same_report_set(build_reports, report_ids):
            return _build_row(build)
    return None


# --- record persistence + queries ----------------------------------------------


async def save_stage_a_batch_record(
    build_id: str,
    source_report_id: str,
    plan: Dict[str, Any],
    member_texts: Dict[str, str],
    package: Optional[StageAEvidencePackage],
    record_error: Optional[str],
) -> Dict[str, Any]:
    """Persist one Stage A batch row (evidence package or traceable failure).

    ``plan`` is a ``plan_stage_a_batches`` entry; ``member_texts`` maps
    member ``source_record_id`` → serialized six-field text. Percentages
    and category shares ride through exactly as the model returned them —
    never recomputed, never rewritten.
    """
    ordered_ids = [str(rid) for rid in plan.get("source_record_ids") or []]
    source_text = "\n\n---\n\n".join(
        member_texts.get(rid, "") for rid in ordered_ids
    )
    payload: Dict[str, Any] = {
        "build_id": ensure_record_id(build_id),
        "source_report_id": ensure_record_id(source_report_id),
        "source_record_id": str(plan.get("batch_id")),
        "source_text": source_text,
        "symptom": None,
        "findings": [],
        "candidate_causes": [],
        "diagnostic_steps": [],
        "corrective_actions": [],
        "verification_steps": [],
        "post_repair_events": [],
        "stage_a_evidence": package.model_dump() if package is not None else None,
        "record_error": record_error,
        "batch_index": plan.get("index"),
        "equipment": plan.get("equipment"),
        "failure_mode": plan.get("failure_mode"),
        "batch_record_ids": ordered_ids,
        "est_input_tokens": plan.get("est_input_tokens"),
        "batch_config": plan.get("config") or {},
        "oversized": bool(plan.get("oversized") or False),
        "created": "time::now()",
    }
    fields = ", ".join(f"{key}: $val_{key}" for key in payload if key != "created")
    params = {f"val_{key}": value for key, value in payload.items() if key != "created"}
    rows = await repo_query(
        f"CREATE {TABLE_RECORD} CONTENT {{{fields}, created: time::now()}} RETURN AFTER",
        params,
    )
    if not rows:
        raise RuntimeError("Failed to persist Stage A batch record")
    return _record_row(rows[0])


# --- Stage B full synthesis (two-stage guide generation) -----------------------
#
# After ALL Stage A batches for one Equipment + Failure Mode finish, Stage B
# synthesizes them into the final Persian operational guide. Real LLM call —
# never templated. The application owns scope assembly, reference
# validation and persistence; the LLM owns all substantive content.


TABLE_STAGE_B_GUIDE = "llm_stage_b_guide"

STAGE_B_SYSTEM_PROMPT = (
    "You are a senior maintenance troubleshooting knowledge synthesizer.\n"
    "\n"
    "Your task is to transform evidence extracted from historical maintenance records into a practical operational troubleshooting guide for ONE equipment unit and ONE failure mode.\n"
    "\n"
    "The evidence ultimately originates from raw maintenance reports.\n"
    "\n"
    "You must NOT use external knowledge.\n"
    "\n"
    "## 1. ABSOLUTE SOURCE RULE\n"
    "\n"
    "Use only the supplied historical evidence packages.\n"
    "\n"
    "Do not use:\n"
    "\n"
    "* general engineering knowledge;\n"
    "* textbook knowledge;\n"
    "* manufacturer procedures;\n"
    "* internet knowledge;\n"
    "* assumptions about the equipment;\n"
    "* Text Mining output;\n"
    "* pre-existing troubleshooting guides;\n"
    "* canonical causes;\n"
    "* knowledge from another equipment;\n"
    "* knowledge from another failure mode.\n"
    "\n"
    "If the evidence does not support a statement, do not create that statement.\n"
    "\n"
    "## 2. OBJECTIVE\n"
    "\n"
    "Produce a result similar in structure, depth, and practical usefulness to an experienced maintenance engineer's troubleshooting guide.\n"
    "\n"
    "The result must transform repeated historical maintenance evidence into:\n"
    "\n"
    "1. an operational troubleshooting sequence;\n"
    "2. historical failure-focus categories;\n"
    "3. historical frequency and percentages;\n"
    "4. a prioritized troubleshooting table;\n"
    "5. unresolved/unknown cases.\n"
    "\n"
    "The guide is historical evidence synthesized into an operational form.\n"
    "\n"
    "It is NOT a generic maintenance manual.\n"
    "\n"
    "## 3. EQUIPMENT AND FAILURE MODE\n"
    "\n"
    "All supplied evidence belongs to the same equipment and the same failure mode.\n"
    "\n"
    "Treat all supplied evidence packages as one historical knowledge set.\n"
    "\n"
    "Do not keep batch boundaries in the final answer.\n"
    "\n"
    "Merge evidence across all batches.\n"
    "\n"
    "## 4. RECORD COUNT\n"
    "\n"
    "Use the complete set of unique source records represented across all evidence packages.\n"
    "\n"
    "Each source record must be counted exactly once for primary failure-focus statistics.\n"
    "\n"
    "Do not count the same record twice because it contains multiple components or actions.\n"
    "\n"
    "## 5. PRIMARY FAILURE-FOCUS CATEGORIES\n"
    "\n"
    "Construct a small number of meaningful technical categories from the historical evidence.\n"
    "\n"
    "Possible examples include:\n"
    "\n"
    "* Tool Pocket / Magazine\n"
    "* Gripper / Clamping\n"
    "* Sensors / Feedback\n"
    "* Door System\n"
    "* Pneumatic System\n"
    "* Control / Software / Parameter\n"
    "* Unknown / Unresolved\n"
    "\n"
    "Do not force the evidence into these exact categories.\n"
    "\n"
    "Merge semantically equivalent categories.\n"
    "\n"
    "Keep technically distinct mechanisms separate.\n"
    "\n"
    "## 6. CATEGORY SHARE\n"
    "\n"
    "For each category provide:\n"
    "\n"
    "* category name;\n"
    "* subcomponents;\n"
    "* characteristic symptoms;\n"
    "* components/items to inspect;\n"
    "* historical record count;\n"
    "* historical percentage.\n"
    "\n"
    "The percentage must be:\n"
    "\n"
    "category primary-record count / total unique source-record count × 100\n"
    "\n"
    "Round percentages to one decimal place.\n"
    "\n"
    "The category percentages must sum to approximately 100%, subject only to rounding.\n"
    "\n"
    "## 7. PRIORITY TABLE\n"
    "\n"
    "Create a historical-priority troubleshooting table.\n"
    "\n"
    "Columns:\n"
    "\n"
    "| اولویت بررسی | علت / کانون محتمل | سهم در سوابق | نشانه اصلی | اثر خرابی | اقدام پیشنهادی |\n"
    "\n"
    "The order must be based on historical evidence.\n"
    "\n"
    "Do not call an item \"most likely\" unless that conclusion is explicitly supported by the historical evidence.\n"
    "\n"
    "Prefer historical wording such as:\n"
    "\n"
    "* بیشترین تکرار تاریخی\n"
    "* در سوابق متعدد مشاهده شده\n"
    "* در این سوابق همراه با این نشانه ثبت شده\n"
    "\n"
    "## 8. OPERATIONAL TROUBLESHOOTING SEQUENCE\n"
    "\n"
    "Create a practical sequence for a maintenance technician.\n"
    "\n"
    "The sequence should progress from preserving the failure condition toward diagnosis and verification.\n"
    "\n"
    "A typical structure may contain approximately 7–12 stages, but the number is determined by the evidence.\n"
    "\n"
    "For each stage explain:\n"
    "\n"
    "* what to check;\n"
    "* why this check is relevant to the historical records;\n"
    "* what observation leads to the next branch;\n"
    "* what documented action is appropriate if a fault is found.\n"
    "\n"
    "Use concise operational language.\n"
    "\n"
    "Examples of acceptable formulations:\n"
    "\n"
    "* بررسی شود.\n"
    "* کنترل شود.\n"
    "* در صورت مشاهده خرابی، تعویض شود.\n"
    "* در صورت نیاز تنظیم شود.\n"
    "* در صورت مشاهده نشتی، مسیر مربوطه بررسی و رفع شود.\n"
    "\n"
    "Do not invent measurements, thresholds, parameter values, or component specifications.\n"
    "\n"
    "## 9. PRESERVE THE FAILURE CONDITION\n"
    "\n"
    "If the historical records contain evidence that resetting, changing machine state, or losing the alarm condition can hide the original fault, this should be reflected in the initial stage.\n"
    "\n"
    "Do not create this recommendation merely from general knowledge.\n"
    "\n"
    "It must be supported by the supplied evidence.\n"
    "\n"
    "## 10. SYMPTOM-TO-PATH RELATIONSHIPS\n"
    "\n"
    "Where historical records support them, connect symptoms to troubleshooting paths.\n"
    "\n"
    "Examples:\n"
    "\n"
    "* problem associated with a particular Pocket;\n"
    "* gripper not holding/releasing;\n"
    "* spindle clamping problem;\n"
    "* door confirmation problem;\n"
    "* sensor/input problem;\n"
    "* pneumatic movement problem;\n"
    "* sequence or parameter-related problem.\n"
    "\n"
    "Do not introduce a symptom that does not appear in the evidence.\n"
    "\n"
    "## 11. DIAGNOSTIC ORDER\n"
    "\n"
    "The final order should be an evidence-based synthesis.\n"
    "\n"
    "It may organize recurring historical checks into a practical order, but it must not claim to be the manufacturer's official procedure.\n"
    "\n"
    "Do not add generic steps solely because they are normally performed in industry.\n"
    "\n"
    "## 12. CORRECTIVE ACTIONS\n"
    "\n"
    "Every corrective action must be traceable to one or more historical records.\n"
    "\n"
    "Convert historical actions into conditional operational instructions.\n"
    "\n"
    "Do not turn a one-time historical action into an unconditional universal instruction.\n"
    "\n"
    "## 13. VERIFICATION\n"
    "\n"
    "The final stage must reflect documented historical verification.\n"
    "\n"
    "Examples:\n"
    "\n"
    "* repeated tool changes;\n"
    "* tests using multiple tools;\n"
    "* tests involving different pockets;\n"
    "* alarm recurrence checks;\n"
    "* machine test and handover.\n"
    "\n"
    "Do not invent test counts.\n"
    "\n"
    "## 14. UNRESOLVED CASES\n"
    "\n"
    "Create an explicit unresolved section.\n"
    "\n"
    "Cases where the cause was:\n"
    "\n"
    "* unknown;\n"
    "* not identified;\n"
    "* not reproduced;\n"
    "* not observed;\n"
    "* insufficiently documented\n"
    "\n"
    "must remain unresolved.\n"
    "\n"
    "Do not assign a technical cause merely to make the guide complete.\n"
    "\n"
    "## 15. LANGUAGE\n"
    "\n"
    "Write the entire final answer in Persian.\n"
    "\n"
    "Preserve technical English terminology from the evidence where it improves precision.\n"
    "\n"
    "Do not translate technical component names into invented terminology.\n"
    "\n"
    "## 16. REQUIRED FINAL FORMAT\n"
    "\n"
    "Return exactly the following structure.\n"
    "\n"
    "# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی\n"
    "\n"
    "### مرحله 1 — ...\n"
    "\n"
    "...\n"
    "\n"
    "### مرحله 2 — ...\n"
    "\n"
    "...\n"
    "\n"
    "Continue until the evidence-supported troubleshooting sequence is complete.\n"
    "\n"
    "Then:\n"
    "\n"
    "# دسته‌بندی کانون‌های اصلی خرابی {equipment}\n"
    "\n"
    "| کانون اصلی | زیرمجموعه‌ها | علائم شاخص | قطعاتی که باید در این کانون بررسی شوند | سهم تاریخی |\n"
    "| ---------- | ------------ | ---------- | -------------------------------------- | ---------- |\n"
    "\n"
    "Then:\n"
    "\n"
    "راهنمای کاربردی تعمیر:\n"
    "\n"
    "| اولویت بررسی | علت / کانون محتمل | سهم در سوابق | نشانه اصلی | اثر خرابی | اقدام پیشنهادی |\n"
    "| ------------ | ----------------- | ------------ | ---------- | --------- | -------------- |\n"
    "\n"
    "Then:\n"
    "\n"
    "### موارد نامشخص / بدون علت قطعی\n"
    "\n"
    "List unresolved historical cases and explain only what the records establish.\n"
    "\n"
    "## 17. FINAL QUALITY CONTROL\n"
    "\n"
    "Before returning the final answer, verify internally:\n"
    "\n"
    "* every technical component appears in the supplied evidence;\n"
    "* every troubleshooting branch has historical support;\n"
    "* every corrective action is historically supported;\n"
    "* unknown causes remain unknown;\n"
    "* no source record is double-counted;\n"
    "* the denominator is the total number of unique source records;\n"
    "* percentages are mathematically consistent;\n"
    "* category labels represent evidence-supported groupings;\n"
    "* the guide does not introduce external engineering knowledge;\n"
    "* the final sequence is practical but evidence-grounded;\n"
    "* the result contains no discussion of these instructions.\n"
    "\n"
    "Return only the final Persian guide."
)


#: Required Stage B section markers (§16). A synthesis missing any of
#: these is invalid — the format is part of the contract.
STAGE_B_REQUIRED_SECTIONS = (
    "# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی",
    "# دسته‌بندی کانون‌های اصلی خرابی",
    "راهنمای کاربردی تعمیر:",
    "### موارد نامشخص / بدون علت قطعی",
)


class StageBSynthesis(BaseModel):
    """Persisted Stage B synthesis for one (build, equipment, FM) scope."""

    equipment: str = ""
    failure_mode: str = ""
    guide_markdown: str = ""
    record_count: int = 0
    batch_ids: List[str] = Field(default_factory=list)
    source_record_ids: List[str] = Field(default_factory=list)
    math_warnings: List[str] = Field(default_factory=list)


def build_stage_b_prompt(
    equipment: str,
    failure_mode: str,
    total_unique: int,
    evidence_packages: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """System + user prompt for one Stage B synthesis (brief §7 verbatim)."""
    rendered = "\n\n".join(
        json.dumps(package, ensure_ascii=False)
        for package in evidence_packages
    )
    user = (
        "Generate the final operational troubleshooting guide for:\n"
        "\n"
        f"Equipment:\n{equipment}\n"
        "\n"
        f"Failure Mode:\n{failure_mode}\n"
        "\n"
        f"Total unique historical records:\n{total_unique}\n"
        "\n"
        "The following evidence packages collectively represent ALL historical records for this Equipment + Failure Mode.\n"
        "\n"
        "They may have been produced by multiple Stage A batches because of token or record-count limits.\n"
        "\n"
        "Treat them as ONE complete historical knowledge set.\n"
        "\n"
        "Do not preserve batch boundaries in the final answer.\n"
        "\n"
        "--- HISTORICAL EVIDENCE PACKAGES ---\n"
        "\n"
        f"{rendered}\n"
        "\n"
        "--- END HISTORICAL EVIDENCE PACKAGES ---\n"
        "\n"
        "Synthesize all supplied evidence packages according to the system instructions.\n"
        "\n"
        "Return only the final Persian operational troubleshooting guide."
    )
    return STAGE_B_SYSTEM_PROMPT, user


_STAGE_B_ID_PATTERN = re.compile(r"[A-Za-z0-9_]+-LLMROW-\S+")


def _validate_stage_b_guide(
    markdown: str, scope_record_ids: List[str]
) -> List[str]:
    """Validate a Stage B synthesis without rewriting it.

    Returns a list of blocking problems (empty when valid): missing
    required sections, references to source IDs outside the scope, or
    mathematically inconsistent percentages. The guide text itself is
    never modified — invalid syntheses are rejected, not repaired.
    """
    problems: List[str] = []
    if not isinstance(markdown, str) or not markdown.strip():
        return ["empty_synthesis"]
    for marker in STAGE_B_REQUIRED_SECTIONS:
        if marker not in markdown:
            problems.append(f"missing_section: {marker[:24]}")
    scope = set(scope_record_ids)
    for match in _STAGE_B_ID_PATTERN.finditer(markdown):
        candidate = match.group(0).rstrip(".,;:!?\"')]}")
        if candidate not in scope:
            problems.append(f"unknown_record_reference: {candidate[:48]}")
            break
    problems.extend(_check_share_table_math(markdown))
    return problems


def _check_share_table_math(markdown: str) -> List[str]:
    """Check share-column tables sum to ~100 (never rewrites anything).

    Only markdown tables whose header names a share column (سهم) are
    assessed; bare numbers elsewhere (counts, pocket numbers, prose
    percentages) are not verifiable shares and are ignored.
    """
    problems: List[str] = []
    table_rows: List[List[str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells and all(set(cell) <= set("-: ") for cell in cells):
                continue  # separator row
            table_rows.append(cells)
        else:
            _flush_tables(table_rows, problems)
            table_rows = []
    _flush_tables(table_rows, problems)
    return problems


def _flush_tables(
    table_rows: List[List[str]], problems: List[str]
) -> None:
    if len(table_rows) < 2:
        table_rows.clear()
        return
    header = table_rows[0]
    share_idx = next(
        (pos for pos, cell in enumerate(header) if "سهم" in cell), None)
    rows = table_rows[1:]
    table_rows.clear()
    if share_idx is None:
        return
    values: List[float] = []
    for row in rows:
        if share_idx >= len(row):
            continue
        cell = row[share_idx].rstrip("%٪").strip()
        try:
            values.append(float(cell))
        except ValueError:
            continue
    if values and not 97.0 <= sum(values) <= 103.0:
        problems.append(
            f"math_inconsistency: share column sums to {sum(values):.1f}"
        )


async def _existing_stage_b_scopes(build_id: str) -> set:
    """(equipment, failure_mode) scopes already synthesized for a build."""
    rows = await repo_query(
        f"SELECT equipment, failure_mode FROM {TABLE_STAGE_B_GUIDE} "
        "WHERE build_id = $bid",
        {"bid": ensure_record_id(build_id)},
    )
    return {(str(row.get("equipment") or ""), str(row.get("failure_mode") or ""))
            for row in rows or []}


async def list_stage_b_guides(build_id: str) -> List[Dict[str, Any]]:
    """Persisted Stage B syntheses for a build (Guide primary output)."""
    rows = await repo_query(
        f"SELECT * FROM {TABLE_STAGE_B_GUIDE} WHERE build_id = $bid",
        {"bid": ensure_record_id(build_id)},
    )
    guides: List[Dict[str, Any]] = []
    for row in rows or []:
        guides.append({
            "synthesis_id": str(row.get("id")) if row.get("id") else None,
            "build_id": str(row.get("build_id")) if row.get("build_id") else None,
            "equipment": str(row.get("equipment") or ""),
            "failure_mode": str(row.get("failure_mode") or ""),
            "guide_markdown": str(row.get("guide_markdown") or ""),
            "record_count": row.get("record_count"),
            "batch_ids": [str(item) for item in row.get("batch_ids") or []],
            "source_record_ids": [str(item) for item in row.get("source_record_ids") or []],
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
            "math_warnings": [],
        })
    return guides


async def save_stage_b_guide(
    build_id: str,
    equipment: str,
    failure_mode: str,
    guide_markdown: str,
    record_count: int,
    batch_ids: List[str],
    source_record_ids: List[str],
    model: Optional[str],
    stage_b_budget: int,
) -> Dict[str, Any]:
    """Persist one Stage B synthesis (never rewrites LLM content)."""
    synthesis = StageBSynthesis(
        equipment=equipment, failure_mode=failure_mode,
        guide_markdown=guide_markdown, record_count=record_count,
        batch_ids=list(batch_ids),
        source_record_ids=list(source_record_ids),
    )
    payload: Dict[str, Any] = {
        "build_id": ensure_record_id(build_id),
        "equipment": synthesis.equipment,
        "failure_mode": synthesis.failure_mode,
        "guide_markdown": synthesis.guide_markdown,
        "record_count": synthesis.record_count,
        "batch_ids": synthesis.batch_ids,
        "source_record_ids": synthesis.source_record_ids,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "stage_b_budget": stage_b_budget,
        "created": "time::now()",
    }
    fields = ", ".join(f"{key}: $val_{key}" for key in payload if key != "created")
    params = {f"val_{key}": value for key, value in payload.items() if key != "created"}
    try:
        rows = await repo_query(
            f"CREATE {TABLE_STAGE_B_GUIDE} CONTENT {{{fields}, "
            f"created: time::now()}} RETURN AFTER",
            params,
        )
    except Exception as e:
        message = str(e)
        if "unique" in message.lower() or "duplicate" in message.lower():
            logger.debug(f"Stage B guide for {equipment}/{failure_mode} already stored")
            return {"duplicate": True}
        raise
    if not rows:
        raise RuntimeError("Failed to persist Stage B guide")
    return rows[0]


async def run_stage_b_for_build(
    build_id: str, model_id: Optional[str]
) -> List[str]:
    """Synthesize final guides for every fully-successful scope (once each).

    Groups persisted Stage A batch rows by (equipment, failure_mode);
    groups with any failed batch are skipped with a warning (a retry that
    completes them re-runs this step); groups already synthesized are
    skipped (idempotent resume). Returns warnings for the build record.
    """
    from api.llm_generation import LLMKnowledgeGenerator

    warnings: List[str] = []
    budgets = resolve_generation_budgets()
    rows = await repo_query(
        f"SELECT * FROM {TABLE_RECORD} WHERE build_id = $bid",
        {"bid": ensure_record_id(build_id)},
    )
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    order: List[Any] = []
    for row in rows or []:
        if not row.get("batch_record_ids"):
            continue
        key = (str(row.get("equipment") or ""),
               str(row.get("failure_mode") or ""))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    if not groups:
        return warnings
    done = await _existing_stage_b_scopes(build_id)
    generator = LLMKnowledgeGenerator(model_id)
    for equipment, failure_mode in order:
        key = (equipment, failure_mode)
        if key in done:
            continue
        members = sorted(groups[key],
                         key=lambda r: (r.get("batch_index") or 0))
        failed = [m for m in members
                  if m.get("record_error") or not m.get("stage_a_evidence")]
        if failed:
            warnings.append(
                f"stage_b_skipped_failed_batches:{equipment}:{failure_mode}")
            continue
        unique_ids: List[str] = []
        envelopes: List[Dict[str, Any]] = []
        for member in members:
            for rid in member.get("batch_record_ids") or []:
                if rid not in unique_ids:
                    unique_ids.append(rid)
            envelopes.append({
                "batch_id": str(member.get("source_record_id")),
                "source_record_ids": list(member.get("batch_record_ids") or []),
                "evidence": member.get("stage_a_evidence") or {},
            })
        system, user = build_stage_b_prompt(
            equipment, failure_mode, len(unique_ids), envelopes)
        try:
            markdown = await generator.generate_from_messages(
                system, user, max_tokens=budgets["stage_b"], structured=None,
            )
        except (ValueError, ConfigurationError):
            raise
        except Exception as e:
            warnings.append(
                f"stage_b_provider_error:{equipment}:{failure_mode}: {e}"[:200])
            continue
        problems = _validate_stage_b_guide(markdown, unique_ids)
        if problems:
            warnings.append(
                f"stage_b_invalid:{equipment}:{failure_mode}: "
                f"{'; '.join(problems)}"[:200])
            continue
        await save_stage_b_guide(
            build_id, equipment, failure_mode, markdown, len(unique_ids),
            [str(m.get("source_record_id")) for m in members], unique_ids,
            model_id, budgets["stage_b"],
        )
    return warnings


async def run_scope_insights_for_build(
    scopes: List[Dict[str, Any]],
    scope_records: Dict[str, List[Dict[str, Any]]],
    build_id: str,
    model_id: Optional[str],
    generate_fn: Any,
) -> Tuple[int, int, List[str]]:
    """Generate one direct insight per scope; persist each as-is.

    ``scopes`` are :func:`plan_scope_insights` plans; ``scope_records``
    maps each scope ID to its resolved six-field member records. Scopes
    already guided (unique index on build + equipment + failure mode)
    are skipped for idempotent resume. Returns
    ``(ok_count, failed_count, warnings)`` — every scope ends counted,
    so a build processed here can always reach a terminal state.
    """
    warnings: List[str] = []
    budgets = resolve_generation_budgets()
    done = await _existing_stage_b_scopes(build_id)
    ok_count = 0
    failed_count = 0
    for scope in scopes:
        equipment = str(scope.get("equipment") or "")
        failure_mode = str(scope.get("failure_mode") or "")
        scope_id = str(scope.get("scope_id") or "")
        key = (equipment, failure_mode)
        if key in done:
            continue
        members = scope_records.get(scope_id) or []
        if not members:
            warnings.append(f"empty_scope:{scope_id}")
            continue
        system, user = build_insight_prompt(
            equipment, failure_mode,
            [{"source_record_id": m["source_record_id"], "fields": m["fields"]}
             for m in members],
        )
        try:
            raw = await generate_fn(
                system, user, scope_id, model_id, budgets["stage_b"])
        except (ValueError, ConfigurationError):
            raise
        except Exception as e:
            warnings.append(
                f"scope_provider_error:{equipment}:{failure_mode}: {e}"[:200])
            failed_count += 1
            continue
        valid, problems, guide_warnings = validate_insight_markdown(raw)
        for item in guide_warnings:
            warnings.append(f"scope_guide_warning:{equipment}:{failure_mode}: "
                            f"{item}"[:200])
        if not valid:
            warnings.append(
                f"scope_invalid:{equipment}:{failure_mode}: "
                f"{'; '.join(problems)}"[:200])
            failed_count += 1
            continue
        try:
            await save_stage_b_guide(
                build_id, equipment, failure_mode, raw, len(members),
                [scope_id],
                [str(m["source_record_id"]) for m in members],
                model_id, budgets["stage_b"],
            )
        except Exception as e:
            message = str(e)
            if "unique" in message.lower() or "duplicate" in message.lower():
                logger.debug(f"Insight scope {scope_id} already stored")
            else:
                warnings.append(
                    f"scope_persist_error:{equipment}:{failure_mode}: "
                    f"{e}"[:200])
                failed_count += 1
                continue
        ok_count += 1
        done.add(key)
    return ok_count, failed_count, warnings


async def existing_source_record_ids(build_id: str) -> set:
    """Source records already persisted for a build (worker resume seam)."""
    rows = await repo_query(
        f"SELECT VALUE source_record_id FROM {TABLE_RECORD} WHERE build_id = $bid "
        "AND record_error = NONE AND stage_a_evidence != NONE",
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
    report_ids: List[str],
    model_id: Optional[str] = None,
    *,
    submit_command: bool = True,
) -> Dict[str, Any]:
    """Validate reports, dedupe against an active equivalent, submit work.

    Raises ``BuildInProgressError`` (router maps to 409 carrying the
    live build) while an equivalent build is active; ``NotFoundError``
    for unknown reports; ``InvalidInputError`` for an empty set.
    Reports, mining knowledge, and embeddings are never touched here —
    only a new build row plus a worker command are created.

    When ``submit_command`` is False no worker command is submitted:
    the caller executes the build inline itself (the analysis worker
    runs generation inside its own job so exactly one executor exists).
    The build stays ``queued`` (no ``command_id``) until the inline
    execution marks it running; the active-build guard still treats it
    as in-flight, so a concurrent manual submission reuses it (409)
    instead of duplicating it.
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
    # Fail fast (M14 §7): verify the generation path returns valid
    # output BEFORE creating build rows or submitting commands. A
    # failing preflight raises ConfigurationError (→ HTTP 422) with
    # actionable diagnostics instead of producing dozens of predictable
    # per-record failures.
    from api.llm_generation import preflight_llm_generation

    await preflight_llm_generation(model_id)
    build = await create_build(resolved, manifest, model_id)
    if not submit_command:
        logger.info(
            f"Created LLM knowledge build {build['id']} "
            "(inline execution; no worker command submitted)"
        )
        return build
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
    matches exactly are returned, and final guides are relevance
    filtered to syntheses covering at least one of this source's
    records (Stage B scopes are Equipment + Failure Mode and may span
    reports within the build; per-record provenance stays exact).
    Empty states are explicit (``no_records_for_source``), and a deleted
    backing report keeps its stable identity with ``source_deleted`` —
    never remapped to another same-named file. Provenance (§17) rides on every response; the UI
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
    member_ids: set = set()
    for row in records:
        member_ids.update(str(rid) for rid in row.get("batch_record_ids") or [])
        if row.get("source_record_id"):
            member_ids.add(str(row["source_record_id"]))
    records = aggregate_failure_mode_records(records)
    guides_all = await list_stage_b_guides(build_id)
    if member_ids:
        final_guides = [
            guide for guide in guides_all
            if set(guide.get("source_record_ids") or []) & member_ids
        ]
    elif not source_deleted:
        # Record-less build (direct insight flow): scope guides by this
        # report's analysis-key prefix — record IDs are deterministic
        # f"{analysis_key}-LLMROW-{sheet}-{excel_row}".
        analysis_key = str(report_internal.get("analysis_key") or "")
        prefix = f"{analysis_key}-LLMROW-" if analysis_key else ""
        final_guides = [
            guide for guide in guides_all
            if prefix and any(str(rid).startswith(prefix)
                              for rid in guide.get("source_record_ids") or [])
        ]
    else:
        final_guides = []
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
            "final_guides": [],
            "warnings": ["source_deleted"],
        }
    if not records and not final_guides:
        return {
            "knowledge_source": KNOWLEDGE_SOURCE_LLM,
            "build_id": str(build["id"]),
            "model": build.get("model"),
            "prompt_version": build.get("prompt_version"),
            "source_report_id": source_report_id,
            "source_filename": report_filename,
            "source_deleted": False,
            "records": [],
            "final_guides": [],
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
        "final_guides": final_guides,
        "warnings": [],
    }


# --- failure-mode aggregation (M19: one knowledge entry per FM) ---------------


AGGREGATION_LIST_FIELDS = (
    "findings",
    "candidate_causes",
    "diagnostic_steps",
    "corrective_actions",
    "verification_steps",
    "post_repair_events",
)


def _is_batch_row(row: Dict[str, Any]) -> bool:
    # Legacy extraction batch rows only: Stage A evidence rows carry the
    # same batch keys but are represented via final_guides, never merged
    # into the old item-list entries.
    return bool(row.get("batch_record_ids")) and row.get("stage_a_evidence") is None


def _fm_aggregate_id(batch_id: str, equipment: str, failure_mode: str) -> str:
    import hashlib

    analysis_key = str(batch_id).split("-LLMBATCH-")[0]
    digest = hashlib.sha1(
        f"{equipment}\x00{failure_mode}".encode("utf-8")).hexdigest()[:8]
    return f"{analysis_key}-LLMFM-{digest}"


def aggregate_failure_mode_records(
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Combine batch rows into one knowledge entry per failure mode (pure).

    Batch rows sharing ``(build_id, source_report_id, equipment,
    failure_mode)`` merge into a single entry shaped like a record row:
    item lists concatenate in ``batch_index`` order with exact
    ``(field, text, basis, source_quote)`` duplicates merged (their
    ``support_ids`` united), ``symptom`` is the most frequent non-null
    value (ties → lowest batch index), and member errors join into
    ``record_error``. Rows without batch metadata (legacy per-record
    builds) pass through unchanged, in place.
    """
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    order: List[Any] = []
    for row in rows:
        if not _is_batch_row(row):
            continue
        key = (
            str(row.get("build_id")),
            str(row.get("source_report_id")),
            str(row.get("equipment") or ""),
            str(row.get("failure_mode") or ""),
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    entries: Dict[Any, Dict[str, Any]] = {}
    for key, members in groups.items():
        members = sorted(members, key=lambda r: (r.get("batch_index") or 0))
        first = members[0]
        seen: Dict[Any, Dict[str, Any]] = {}
        merged: Dict[str, List[Dict[str, Any]]] = {
            field: [] for field in AGGREGATION_LIST_FIELDS
        }
        for member in members:
            for field in AGGREGATION_LIST_FIELDS:
                for item in member.get(field) or []:
                    item = item or {}
                    dedupe = (
                        field,
                        str(item.get("text") or ""),
                        str(item.get("basis") or ""),
                        str(item.get("source_quote") or ""),
                    )
                    if dedupe in seen:
                        united = seen[dedupe].setdefault("support_ids", [])
                        for sid in item.get("support_ids") or []:
                            if sid not in united:
                                united.append(sid)
                        continue
                    copy = dict(item)
                    copy["support_ids"] = list(item.get("support_ids") or [])
                    seen[dedupe] = copy
                    merged[field].append(copy)
        symptoms: Dict[str, int] = {}
        for member in members:
            symptom = member.get("symptom")
            if isinstance(symptom, str) and symptom.strip():
                symptoms[symptom] = symptoms.get(symptom, 0) + 1
        best_symptom: Optional[str] = None
        if symptoms:
            top = max(symptoms.values())
            for member in members:
                symptom = member.get("symptom")
                if symptom in symptoms and symptoms[symptom] == top:
                    best_symptom = symptom
                    break
        errors = [
            str(m.get("record_error"))
            for m in members if m.get("record_error")
        ]
        batch_ids = [str(m.get("source_record_id")) for m in members]
        member_ids: List[str] = []
        for member in members:
            for rid in member.get("batch_record_ids") or []:
                if rid not in member_ids:
                    member_ids.append(rid)
        entries[key] = {
            "id": first.get("id"),
            "build_id": first.get("build_id"),
            "source_report_id": first.get("source_report_id"),
            "source_record_id": _fm_aggregate_id(
                str(first.get("source_record_id")),
                str(first.get("equipment") or ""),
                str(first.get("failure_mode") or ""),
            ),
            "source_text": "",
            "symptom": best_symptom,
            **merged,
            "record_error": "; ".join(errors)[:500] if errors else None,
            "created": first.get("created"),
            "batch_index": None,
            "equipment": first.get("equipment"),
            "failure_mode": first.get("failure_mode"),
            "batch_ids": batch_ids,
            "batch_record_ids": member_ids,
            "est_input_tokens": sum(
                int(m.get("est_input_tokens") or 0) for m in members
            ),
            "batch_config": first.get("batch_config") or {},
            "oversized": any(bool(m.get("oversized")) for m in members),
        }

    combined: List[Dict[str, Any]] = []
    emitted = set()
    for row in rows:
        if not _is_batch_row(row):
            combined.append(row)
            continue
        key = (
            str(row.get("build_id")),
            str(row.get("source_report_id")),
            str(row.get("equipment") or ""),
            str(row.get("failure_mode") or ""),
        )
        if key not in emitted:
            emitted.add(key)
            combined.append(entries[key])
    return combined


class BuildInProgressError(Exception):
    """An equivalent LLM build is active; carries the live build ID."""

    def __init__(self, build_id: str, message: str):
        super().__init__(message)
        self.build_id = build_id
