"""LLM provider abstraction for knowledge generation (two-stage guide).

``LLMKnowledgeGenerator`` turns a prebuilt prompt into the raw LLM
response text. It reuses the existing provider architecture
(``provision_langchain_model`` → configured language model, large-context
upgrade, ``ConfigurationError`` when unconfigured) and does nothing
else: no validation, no persistence, no UI, no database access. No
embeddings are involved.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Dict, Optional

from loguru import logger

from api import llm_knowledge_service as llm_knowledge
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.utils.error_classifier import classify_error

#: Hard cap per call so one stuck provider call cannot wedge a build.
GENERATION_TIMEOUT_SECONDS = 300


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

    async def generate_from_messages(
        self, system: str, user: str, max_tokens: Optional[int] = None,
        structured: Optional[str] = "json",
    ) -> str:
        """Return the raw LLM response for a prebuilt prompt (may raise).

        Shared generation path: identical provisioning, timeout, and
        error mapping — only the prompt differs. ``max_tokens`` ``None``
        preserves the provider default; an explicit value is forwarded
        through the existing config mechanism. ``structured`` selects the
        provider JSON lever (``"json"``) or plain text (``None``) for
        prose outputs such as the Stage B guide.
        """
        payload = f"{system}\n\n{user}"
        provision_kwargs: Dict[str, Any] = {
            "structured": structured, "temperature": 0,
        }
        if max_tokens is not None:
            provision_kwargs["max_tokens"] = max_tokens
        try:
            model = await provision_langchain_model(
                payload, self._model_id, "transformation",
                **provision_kwargs,
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


async def preflight_llm_generation(model_id: Optional[str] = None) -> None:
    """Fail-fast probe of the generation path (M14 §7).

    Runs one minimal Stage A-shaped generation through the real path and
    requires a structurally parseable evidence-shaped response. This is a
    provider-capability check (connectivity, model resolution, JSON mode,
    parsing) — it deliberately does NOT validate the sample against the
    full Stage A evidence semantics, so incidental malformed sample
    content never blocks build startup. Raises ``ConfigurationError``
    with an actionable message when the provider/model cannot satisfy
    the contract — callers must fail BEFORE creating build rows or
    submitting commands. Real Stage A outputs are still validated by
    ``parse_stage_a_evidence``.
    """
    from open_notebook.exceptions import ConfigurationError

    budgets = llm_knowledge.resolve_generation_budgets()
    system, user, member_ids = llm_knowledge.build_stage_a_preflight_prompt()
    try:
        raw = await LLMKnowledgeGenerator(model_id).generate_from_messages(
            system, user, max_tokens=budgets["stage_a"]
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
    ok, errors = llm_knowledge.parse_stage_a_preflight(raw)
    if not ok:
        detail = "; ".join(errors) if errors else "unknown validation failure"
        raise ConfigurationError(
            "LLM preflight failed: the provider/model did not return a "
            f"usable structured response ({detail}). Check that the model "
            "supports JSON mode and is reachable before starting a build."
        )


logger.debug("LLM knowledge generator module loaded")
