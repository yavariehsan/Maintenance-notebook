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
from functools import partial
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from api import llm_knowledge_service as llm_knowledge
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.utils.error_classifier import classify_error

#: Hard cap per record so one stuck provider call cannot wedge a build.
GENERATION_TIMEOUT_SECONDS = 300

#: Minimal fixed probe input for the build preflight (§7): small, REALISTIC
#: M12-shaped Persian maintenance content, and fast. Any schema-valid
#: extraction passes — including an all-empty one — because preflight
#: tests the *generation path*, not any particular record's content.
#: Deliberately NOT content-free: vacuous probe text elicits degenerate
#: model confabulation unrelated to path viability.
PREFLIGHT_SOURCE_TEXT = (
    "کد فرایندی: M3\n"
    "شرح درخواست: مشکل در تعویض ابزار (تعویض ابزار)\n"
    "شرح تعمیر: با nck مشکل حل شد\n"
    "حالت خرابی: مشکل در تعویض ابزار (تعویض ابزار)"
)
PREFLIGHT_RECORD_ID = "preflight"


def _supports_reasoning_flag(model: object) -> bool:
    """Whether per-invoke reasoning control is safe for this model.

    The ``reasoning`` flag is Ollama-specific (langchain_ollama
    ``ChatOllama``); other providers must never receive it. Import is
    lazy so environments without langchain_ollama keep working.
    """
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        return False
    return isinstance(model, ChatOllama)


def _invoke_model(model: Any, messages: Any, invoke_kwargs: Dict[str, Any]) -> Any:
    """Call ``model.invoke`` with optional provider-specific kwargs.

    Typed loosely on purpose: invoke signatures vary by provider
    (e.g. Ollama-only ``reasoning``), and the caller guarantees safety
    via :func:`_supports_reasoning_flag`.
    """
    return model.invoke(messages, **invoke_kwargs)


class LLMKnowledgeGenerator:
    """Structured-extraction generator over the configured chat model."""

    def __init__(self, model_id: Optional[str] = None):
        self._model_id = model_id

    @property
    def prompt_version(self) -> str:
        return llm_knowledge.PROMPT_VERSION

    async def generate(self, source_text: str, source_record_id: str) -> str:
        """Return the raw LLM response for one record (may raise).

        Hardened (M14) for thinking models: provider JSON mode is
        requested through the existing ``structured`` plumbing and
        reasoning is disabled per-invocation for Ollama chat models, so
        the token budget produces the final structured answer instead of
        an unbounded private reasoning trace. Temperature is fixed at 0:
        extraction is a deterministic task and sampling variance
        (esperanto's 1.0 default) measurably breaks schema compliance on
        small models (1/3 valid at 1.0 vs 3/3 byte-identical at 0).
        Non-Ollama providers are invoked exactly as before, at the
        deterministic temperature.
        """
        system, user = llm_knowledge.build_extraction_prompt(
            source_text, source_record_id
        )
        payload = f"{system}\n\n{user}"
        try:
            model = await provision_langchain_model(
                payload, self._model_id, "transformation",
                structured="json", temperature=0,
            )
        except Exception as e:
            exc_class, message = classify_error(e)
            raise exc_class(message) from e
        messages = [
            ("system", system),
            ("human", user),
        ]
        invoke_kwargs = (
            {"reasoning": False} if _supports_reasoning_flag(model) else {}
        )
        try:

            async def _invoke() -> str:
                invoke = partial(
                    _invoke_model, model, messages, invoke_kwargs
                )
                response = await asyncio.to_thread(invoke)
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


async def preflight_llm_generation(model_id: Optional[str] = None) -> None:
    """Fail-fast probe of the generation path (M14 §7).

    Runs one minimal M12-shaped generation through the real path and
    requires schema-valid output. Raises ``ConfigurationError`` with an
    actionable message when the provider/model cannot satisfy the
    contract — callers must fail BEFORE creating build rows or
    submitting commands, so one probe replaces dozens of predictable
    per-record failures. Any valid extraction passes (content is
    irrelevant; only path viability is tested).
    """
    from open_notebook.exceptions import ConfigurationError

    try:
        raw = await default_generate(
            PREFLIGHT_SOURCE_TEXT, PREFLIGHT_RECORD_ID, model_id
        )
    except ConfigurationError:
        raise
    except Exception as e:
        exc_class, message = classify_error(e)
        raise ConfigurationError(
            "LLM preflight failed: the provider/model did not return a "
            f"generation result ({message}). Check that the model is "
            "available and reachable before starting a build."
        ) from e
    extraction, errors = llm_knowledge.parse_llm_extraction(raw)
    if extraction is None:
        detail = "; ".join(errors) if errors else "unknown validation failure"
        raise ConfigurationError(
            "LLM preflight failed: the model response did not validate "
            f"against the knowledge schema ({detail}). The configured "
            "model may need reasoning disabled or JSON-mode support to "
            "return structured output."
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
