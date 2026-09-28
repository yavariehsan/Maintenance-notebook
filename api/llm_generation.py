"""LLM provider abstraction for knowledge generation (M12 §10).

``LLMKnowledgeGenerator`` turns one record's source text into the raw
LLM response text. It reuses the existing provider architecture
(``provision_langchain_model`` → configured language model, large-context
upgrade, ``ConfigurationError`` when unconfigured) and does nothing
else: no validation (``llm_knowledge_service.parse_llm_extraction``),
no persistence, no UI, no database access. No embeddings are involved.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from api import llm_knowledge_service as llm_knowledge
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.utils.error_classifier import classify_error

#: Hard cap per record so one stuck provider call cannot wedge a build.
GENERATION_TIMEOUT_SECONDS = 300


class LLMKnowledgeGenerator:
    """Structured-extraction generator over the configured chat model."""

    def __init__(self, model_id: Optional[str] = None):
        self._model_id = model_id

    @property
    def prompt_version(self) -> str:
        return llm_knowledge.PROMPT_VERSION

    async def generate(self, source_text: str, source_record_id: str) -> str:
        """Return the raw LLM response for one record (may raise)."""
        system, user = llm_knowledge.build_extraction_prompt(
            source_text, source_record_id
        )
        payload = f"{system}\n\n{user}"
        try:
            model = await provision_langchain_model(
                payload, self._model_id, "transformation"
            )
        except Exception as e:
            exc_class, message = classify_error(e)
            raise exc_class(message) from e
        messages = [
            ("system", system),
            ("human", user),
        ]
        try:

            async def _invoke() -> str:
                response = await asyncio.to_thread(model.invoke, messages)
                content = getattr(response, "content", response)
                if isinstance(content, list):
                    content = "".join(
                        str(part.get("text", "") if isinstance(part, dict) else part)
                        for part in content
                    )
                return str(content or "")

            return await asyncio.wait_for(
                _invoke(), timeout=GENERATION_TIMEOUT_SECONDS
            )
        except Exception as e:
            exc_class, message = classify_error(e)
            raise exc_class(message) from e


async def default_generate(
    source_text: str, source_record_id: str, model_id: Optional[str] = None
) -> str:
    """Module-level entry point (worker default; replaceable in tests)."""
    return await LLMKnowledgeGenerator(model_id=model_id).generate(
        source_text, source_record_id
    )


def split_provenance(
    record: dict,
) -> Tuple[dict, dict]:
    """Split one stored record into historical vs inferred item groups.

    Pure presentation helper for the Guide UI (§18): DATA_SUPPORTED
    items (plus symptom when explicitly backed — symptom itself carries
    no per-item basis, so it stays with the historical header alongside
    the verbatim source text) vs LLM_INFERRED interpretation.
    """
    historical: Dict[str, Any] = {"symptom": record.get("symptom"), "items": []}
    inferred: Dict[str, Any] = {"items": []}
    for field in (
        "findings",
        "candidate_causes",
        "diagnostic_steps",
        "corrective_actions",
        "verification_steps",
        "post_repair_events",
    ):
        for item in record.get(field) or []:
            target = (
                historical
                if (item or {}).get("basis") == llm_knowledge.BASIS_SUPPORTED
                else inferred
            )
            target["items"].append({"field": field, **(item or {})})
    return historical, inferred


logger.debug("LLM knowledge generator module loaded")
