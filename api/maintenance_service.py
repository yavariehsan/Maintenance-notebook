"""Smart Maintenance Guide orchestration.

Answers equipment questions using ONLY the CMMS sources associated with the
selected equipment code:

1. Resolve the equipment record by code (404 when unknown).
2. List sources carrying that equipment code (empty -> ``no_sources``).
3. Retrieve chunks through the equipment-scoped migration-27 functions only —
   never the global/notebook search. The database enforces the scope, so
   asking about BR1 cannot return BR2 records even when both share the same
   maintenance vocabulary.
4. Synthesize with the existing Ask prompts (``ask/query_process`` +
   ``ask/final_answer``), which already require [document_id] citations and
   forbid fabricating sources. When the records hold no relevant information
   the prompt context is empty and the status is ``no_context`` instead of
   an invented answer.
"""

from typing import Any, Dict, List, Optional

from ai_prompter import Prompter
from loguru import logger

from api.asset_service import get_asset_by_code, normalize_equipment_code
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.database.repository import repo_query
from open_notebook.domain.maintenance import (
    maintenance_text_search,
    maintenance_vector_search,
)
from open_notebook.domain.maintenance import (
    normalize_equipment_code as normalize_scope_code,
)
from open_notebook.exceptions import (
    InvalidInputError,
    OpenNotebookError,
)
from open_notebook.graphs.ask import ASK_MAX_TOKENS
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content


async def list_equipment_sources(equipment_code: str) -> List[Dict[str, Any]]:
    """Sources associated with an equipment code (id + title, updated first)."""
    code = normalize_equipment_code(equipment_code)
    if not code:
        raise InvalidInputError("Equipment code must be provided")
    rows = await repo_query(
        # NOTE: `updated` must stay in the projection: SurrealDB rejects
        # ORDER BY on an idiom absent from a field-restricted SELECT.
        "SELECT id, title, updated FROM source "
        "WHERE string::uppercase(equipment_code OR '') == $code "
        "ORDER BY updated DESC",
        {"code": code.upper()},
    )
    return [{"id": str(row["id"]), "title": row.get("title")} for row in rows]


async def ask_equipment(
    question: str,
    equipment_code: str,
    answer_model: Optional[str] = None,
    final_answer_model: Optional[str] = None,
    max_results: int = 10,
) -> Dict[str, Any]:
    """Ask a question scoped to one equipment's CMMS sources.

    Returns a dict with ``equipment_code``, ``status`` (ok | no_sources |
    no_context), ``answer`` and ``sources`` (contributing CMMS reports).
    Failures (unknown equipment, retrieval outage, unconfigured AI models)
    raise typed exceptions mapped to HTTP statuses by the global handlers.
    """
    trimmed_question = (question or "").strip()
    if not trimmed_question:
        raise InvalidInputError("Question must not be empty")
    code = normalize_scope_code(equipment_code)

    asset = await get_asset_by_code(code)
    equipment_label = f"{asset.code or code} — {asset.name}"

    source_refs = await list_equipment_sources(code)
    if not source_refs:
        return {
            "equipment_code": asset.code or code,
            "status": "no_sources",
            "answer": "",
            "sources": [],
        }

    # Scoped retrieval only. Vector is primary; BM25 text search supplements
    # with title/full-text matches. A text-search failure must not mask the
    # vector results (or vice versa): merge whatever succeeded, and only
    # report no_context when both paths are empty.
    hits: List[Dict[str, Any]] = []
    vector_error: Optional[Exception] = None
    try:
        hits.extend(
            await maintenance_vector_search(
                trimmed_question, code, results=max_results
            )
        )
    except (InvalidInputError, OpenNotebookError):
        # Configuration/outage on the primary path: surface it instead of
        # answering from a degraded context.
        raise
    except Exception as e:  # pragma: no cover - defensive, mirrors text_search
        logger.error(f"Maintenance vector search failed: {str(e)}")
        vector_error = e
    try:
        for hit in await maintenance_text_search(
            trimmed_question, code, results=max_results
        ):
            if hit.get("parent_id") not in {
                h.get("parent_id") for h in hits
            } and hit.get("id") not in {h.get("id") for h in hits}:
                hits.append(hit)
    except Exception as e:
        logger.warning(f"Maintenance text search failed, using vector hits: {e}")
        if not hits and vector_error is not None:
            raise vector_error

    if not hits:
        return {
            "equipment_code": asset.code or code,
            "status": "no_context",
            "answer": "",
            "sources": source_refs,
        }

    instructions = (
        "Answer ONLY from the retrieved maintenance records for equipment "
        f"{equipment_label}. Each record belongs to this equipment. If the "
        "records do not contain enough information, say so explicitly instead "
        "of guessing."
    )
    payload: Dict[str, Any] = {
        "question": trimmed_question,
        "term": trimmed_question,
        "instructions": instructions,
        "results": hits,
        "ids": [h.get("id") for h in hits],
    }
    try:
        query_prompt = Prompter(prompt_template="ask/query_process").render(
            data=payload  # type: ignore[arg-type]
        )
        model = await provision_langchain_model(
            query_prompt, answer_model, "tools", max_tokens=ASK_MAX_TOKENS
        )
        ai_message = await model.ainvoke(query_prompt)
        partial = clean_thinking_content(extract_text_content(ai_message.content))
        if not partial.strip():
            return {
                "equipment_code": asset.code or code,
                "status": "no_context",
                "answer": "",
                "sources": source_refs,
            }

        final_prompt = Prompter(prompt_template="ask/final_answer").render(
            data={  # type: ignore[arg-type]
                "question": trimmed_question,
                "strategy": (
                    "Equipment-scoped maintenance lookup: retrieve only CMMS "
                    f"sources associated with equipment code {equipment_label}, "
                    "then answer strictly from those records."
                ),
                "answers": [partial],
            }
        )
        final_model = await provision_langchain_model(
            final_prompt, final_answer_model, "tools", max_tokens=ASK_MAX_TOKENS
        )
        final_message = await final_model.ainvoke(final_prompt)
        answer = clean_thinking_content(
            extract_text_content(final_message.content)
        )
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e

    contributing_ids = {
        str(h.get("parent_id") or h.get("id")) for h in hits if h.get("id")
    }
    contributing = [s for s in source_refs if s["id"] in contributing_ids]
    return {
        "equipment_code": asset.code or code,
        "status": "ok",
        "answer": answer,
        "sources": contributing or source_refs,
    }
