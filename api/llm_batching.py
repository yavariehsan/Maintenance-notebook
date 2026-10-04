"""Deterministic, token-budgeted batch planner for LLM generation (M19).

Equipment → Failure Mode → one or more LLM batches. Batching is an
execution constraint only: the semantic analysis unit stays Equipment,
and records from different Failure Modes never share a request.

Grouping key: ``(equipment, normalized failure mode)`` where the failure
mode is normalized with the engine's dependency-free ``TextNormalizer``
(imported installed-or-vendored, never touching the mining database).
Blank failure modes share the ``""`` group (no FM claim ⇒ no cross-FM
contamination); see ``failure_mode_key``.

Token figures are ESTIMATES over the complete batch prompt text using the
repo tokenizer (``o200k_base``). The configured provider bills ~1.36x the
local estimate (measured 2026-09-30 on ``oc/space-bunny-free``); the
budget is denominated in local-estimate units and the ratio is recorded
in every batch's config — never silently converted, never claimed exact.
"""

from __future__ import annotations

import hashlib
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from open_notebook.utils.token_utils import token_count

#: Hard cap on records per batch (spec: cap, not target).
BATCH_MAX_RECORDS_DEFAULT = 12

#: Primary packing constraint, in local-estimate token units over the
#: FULL batch prompt (system + serialized records + schema footer).
#: ≈8k provider in-tokens at the measured 1.36x ratio.
BATCH_MAX_TOKENS_DEFAULT = 6000

#: Estimator identity, recorded on every batch (auditability).
TOKEN_ESTIMATOR_ID = "o200k_base-local-estimate"

#: Measured provider/local ratio (M18, 2026-09-30). Recorded, not applied.
PROVIDER_TOKEN_RATIO_NOTE = (
    "provider-bills-~1.36x-local-on-oc/space-bunny-free-2026-09-30"
)

#: Workbook headers carrying the partition keys.
FAILURE_MODE_HEADER = "حالت خرابی"
EQUIPMENT_HEADER = "کد فرایندی"


def _resolve_int(env_name: str, explicit: Optional[int], default: int) -> int:
    if explicit is not None:
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


def resolve_batch_config(
    max_records: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Effective batch config: explicit > env > defaults (auditable)."""
    records = _resolve_int("LLM_BATCH_MAX_RECORDS", max_records,
                           BATCH_MAX_RECORDS_DEFAULT)
    tokens = _resolve_int("LLM_BATCH_MAX_TOKENS", max_tokens,
                          BATCH_MAX_TOKENS_DEFAULT)
    return {
        "max_records": records,
        "max_tokens": tokens,
        "estimator": TOKEN_ESTIMATOR_ID,
        "provider_ratio_note": PROVIDER_TOKEN_RATIO_NOTE,
        "normalizer": _normalizer_identity(),
    }


def _load_normalizer() -> Callable[[Any], str]:
    """Engine TextNormalizer (installed or vendored) or inline fallback."""
    try:
        from maintenance_troubleshooting.text import TextNormalizer

        normalizer = TextNormalizer()
        return normalizer.normalize
    except ImportError:
        pass
    try:
        candidate = (
            Path(__file__).resolve().parent.parent
            / "packages"
            / "maintenance-troubleshooting-engine"
            / "src"
        )
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            from maintenance_troubleshooting.text import TextNormalizer

            normalizer = TextNormalizer()
            return normalizer.normalize
    except ImportError:
        pass

    def _fallback(text: Any) -> str:
        value = "" if text is None else str(text)
        value = unicodedata.normalize("NFKC", value)
        return " ".join(value.split())

    return _fallback


_normalize = _load_normalizer()


def _normalizer_identity() -> str:
    module = getattr(_normalize, "__module__", "") or ""
    if "maintenance_troubleshooting" in module:
        return "engine-TextNormalizer"
    return "inline-fallback-NFKC"


def failure_mode_key(raw: Any) -> str:
    """Normalized FM group key; blank/None → ``""`` (shared no-claim group)."""
    if raw is None:
        return ""
    return _normalize(str(raw))


def equipment_key(raw: Any) -> str:
    """Equipment group key; blank/None → ``""`` (whole-file fallback)."""
    if raw is None:
        return ""
    return str(raw).strip()


def batch_id_for(analysis_key: str, equipment: str, fm_key: str,
                 index: int) -> str:
    """Deterministic batch ID: key + equipment/FM hash + per-group index.

    Equipment is folded into the digest: the same failure mode on two
    machines must never share an ID (a shared ID would make resume skip
    the second machine's batch silently).
    """
    digest = hashlib.sha1(
        f"{equipment}\x00{fm_key}".encode("utf-8")).hexdigest()[:8]
    return f"{analysis_key}-LLMBATCH-{digest}-{index:03d}"


def estimate_batch_tokens(system: str, user: str) -> int:
    """Local token estimate over the COMPLETE batch prompt text."""
    return token_count(f"{system}\n\n{user}")


def plan_batches(
    records: List[Dict[str, Any]],
    system: str,
    user_prefix_fn: Callable[[List[Dict[str, Any]]], str],
    user_suffix: str,
    max_records: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Partition records into deterministic batches (pure).

    Groups by ``(equipment, failure_mode)`` in first-seen order, packs
    greedily within each group (count cap first, token budget second). A
    single record exceeding the budget alone forms its own ``oversized``
    batch — never dropped, never mixed. Input order within a group is
    preserved (caller sorts by ``(analysis_key, sheet, excel_row)``).
    """
    config = resolve_batch_config(max_records, max_tokens)
    cap = config["max_records"]
    budget = config["max_tokens"]

    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for record in records:
        key = (record.get("equipment") or "", record.get("failure_mode") or "")
        groups.setdefault(key, []).append(record)

    plans: List[Dict[str, Any]] = []
    for (equipment, fm_key), members in groups.items():
        analysis_key = ""
        if members:
            first_id = str(members[0].get("source_record_id") or "")
            analysis_key = first_id.split("-LLMROW-")[0] or "nokey"
        index = 0
        current: List[Dict[str, Any]] = []

        def _flush() -> None:
            nonlocal index
            if not current:
                return
            user = user_prefix_fn(current) + user_suffix
            est = estimate_batch_tokens(system, user)
            ids = [str(r["source_record_id"]) for r in current]
            plans.append({
                "batch_id": batch_id_for(analysis_key, equipment, fm_key,
                                         index),
                "equipment": equipment,
                "failure_mode": fm_key,
                "index": index,
                "record_count": len(current),
                "source_record_ids": ids,
                "est_input_tokens": est,
                "oversized": len(current) == 1 and est > budget,
                "config": dict(config),
            })
            index += 1
            current.clear()

        for record in members:
            if len(current) >= cap:
                _flush()
            trial = current + [record]
            user = user_prefix_fn(trial) + user_suffix
            if current and estimate_batch_tokens(system, user) > budget:
                _flush()
                trial = [record]
            current = trial
        _flush()
    return plans
