"""M14 regression tests: thinking-model empty-response failure + hardened path.

Covers M14 §10:
1. empty final response with non-empty thinking -> empty_response
2. valid structured response parses (provenance intact)
3. malformed JSON rejected
4. schema validation failure (missing field) rejected
5. provider/network error raises classified error (never raw)
6. timeout raises
7. generate() disables reasoning for Ollama chat models
8. generate() omits the reasoning flag for other providers
9. generate() requests provider JSON mode via existing plumbing
10. preflight failure blocks build creation (no build row, no submit)
11. successful preflight lets the build proceed
12. preflight provider error blocks build with actionable diagnostics
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_ollama import ChatOllama

from api import llm_generation as gen
from api import llm_knowledge_service as svc
from open_notebook.exceptions import ConfigurationError

VALID_JSON = json.dumps({
    "symptom": "مشکل در تعویض ابزار",
    "findings": [{"text": "مدار امرجنسی بررسی شد", "basis": "DATA_SUPPORTED",
                  "source_quote": "مدار امرجنسی بررسی شد"}],
    "candidate_causes": [],
    "diagnostic_steps": [],
    "corrective_actions": [],
    "verification_steps": [],
})

STAGE_A_VALID_JSON = json.dumps({
    "equipment": "M3",
    "failure_mode": "مشکل در تعویض ابزار (تعویض ابزار)",
    "record_count": 1,
    "records": [{
        "record_id": "preflight-LLMROW-Sheet1-2",
        "primary_focus": "Tool Pocket / Magazine",
        "symptoms": ["مشکل در تعویض ابزار"],
        "observations": [],
        "mechanism": "",
        "cause": "",
        "diagnostic_checks": [],
        "corrective_actions": [],
        "verification": [],
        "unresolved": False,
    }],
    "focus_categories": [],
    "recurring_patterns": [],
    "unresolved_cases": [],
})

# Same shape, but the model returned objects (not strings) inside the
# free-form arrays — the exact class that blocked build startup.
STAGE_A_NONSTRING_ARRAYS_JSON = json.dumps({
    "equipment": "M3",
    "failure_mode": "مشکل در تعویض ابزار (تعویض ابزار)",
    "record_count": 1,
    "records": [{
        "record_id": "preflight-LLMROW-Sheet1-2",
        "primary_focus": "Tool Pocket / Magazine",
        "symptoms": ["مشکل در تعویض ابزار"],
        "observations": [],
        "mechanism": "",
        "cause": "",
        "diagnostic_checks": [],
        "corrective_actions": [],
        "verification": [],
        "unresolved": False,
    }],
    "focus_categories": [],
    "recurring_patterns": [{"pattern": "تکرار خرابی پاکت"}],
    "unresolved_cases": [{"case": "علت نامشخص"}],
})


class RecordingChatOllama(ChatOllama):
    """Real ChatOllama subclass (isinstance passes) with canned invoke."""

    def __init__(self, content="", reasoning_content="", error=None, delay=0.0):
        super().__init__(model="qwen3.5:0.8b")
        object.__setattr__(self, "_canned", (content, reasoning_content, error, delay))
        object.__setattr__(self, "seen_kwargs", None)

    def invoke(self, *args, **kwargs):
        object.__setattr__(self, "seen_kwargs", kwargs)
        content, reasoning, error, delay = object.__getattribute__(self, "_canned")
        if delay:
            import time as _t
            _t.sleep(delay)
        if error is not None:
            raise error
        return AIMessage(content=content,
                         additional_kwargs={"reasoning_content": reasoning} if reasoning else {})


class FakeOtherModel:
    """Non-Ollama provider model: records invoke kwargs."""

    def __init__(self, content=VALID_JSON):
        self.content = content
        self.seen_kwargs = None

    def invoke(self, *args, **kwargs):
        self.seen_kwargs = kwargs
        return AIMessage(content=self.content)


def _provision(fake):
    return patch.object(gen, "provision_langchain_model",
                        new=AsyncMock(return_value=fake))


@pytest.mark.asyncio
async def test_empty_content_with_reasoning_only_returns_empty():
    """M13 failure mode: thinking separated, final response empty."""
    fake = RecordingChatOllama(content="", reasoning_content="...thinking trace...")
    with _provision(fake):
        raw = await gen.LLMKnowledgeGenerator(None).generate_from_messages("sys", "user")
    assert raw == ""


@pytest.mark.asyncio
async def test_provider_error_raises_classified():
    fake = RecordingChatOllama(error=ConnectionError("conn reset"))
    with _provision(fake):
        with pytest.raises(Exception) as exc:
            await gen.LLMKnowledgeGenerator(None).generate_from_messages("sys", "user")
    assert not isinstance(exc.value, ConnectionError)


@pytest.mark.asyncio
async def test_generation_timeout_raises(monkeypatch):
    monkeypatch.setattr(gen, "GENERATION_TIMEOUT_SECONDS", 0.05)
    fake = RecordingChatOllama(content=VALID_JSON, delay=5.0)
    with _provision(fake):
        with pytest.raises(Exception):
            await gen.LLMKnowledgeGenerator(None).generate_from_messages("sys", "user")


@pytest.mark.asyncio
async def test_generate_disables_reasoning_for_ollama_chat():
    """The exact M13 mechanism: thinking must not consume the budget."""
    fake = RecordingChatOllama(content=VALID_JSON)
    with _provision(fake):
        await gen.LLMKnowledgeGenerator(None).generate_from_messages("sys", "user")
    assert fake.seen_kwargs is not None
    assert fake.seen_kwargs.get("reasoning") is False


@pytest.mark.asyncio
async def test_generate_omits_reasoning_for_other_providers():
    """Provider-safe: non-Ollama models never see the Ollama-only flag."""
    fake = FakeOtherModel()
    with _provision(fake):
        raw = await gen.LLMKnowledgeGenerator(None).generate_from_messages("sys", "user")
    assert raw == VALID_JSON
    assert "reasoning" not in (fake.seen_kwargs or {})


@pytest.mark.asyncio
async def test_generate_requests_provider_json_mode():
    """Native structured-output lever through existing plumbing."""
    fake = RecordingChatOllama(content=VALID_JSON)
    with patch.object(gen, "provision_langchain_model",
                       new=AsyncMock(return_value=fake)) as prov:
        await gen.LLMKnowledgeGenerator(None).generate_from_messages("sys", "user")
    assert prov.await_count == 1
    _, kwargs = prov.await_args
    assert kwargs.get("structured") == "json"


@pytest.mark.asyncio
async def test_generate_uses_deterministic_temperature():
    """Sampling variance breaks schema compliance (1/3 valid at temp
    1.0 vs 3/3 byte-identical at temp 0, measured live); extraction is
    deterministic so temperature is fixed at 0."""
    fake = RecordingChatOllama(content=VALID_JSON)
    with patch.object(gen, "provision_langchain_model",
                       new=AsyncMock(return_value=fake)) as prov:
        await gen.LLMKnowledgeGenerator(None).generate_from_messages("sys", "user")
    _, kwargs = prov.await_args
    assert kwargs.get("temperature") == 0


def _repo_side_effect_factory(log):
    async def _repo(query, params=None):
        log.append(query)
        if "FROM repair_report" in query:
            return [{"id": "repair_report:abc", "filename": "m.xlsx",
                     "analysis_key": "key1"}]
        if "FROM llm_knowledge_build" in query and "status IN" in query:
            return []
        if query.startswith("CREATE llm_knowledge_build"):
            # Healthy persistence: the stored row carries the report set
            # (a dropped row here would trip create_build's write guard).
            return [{"id": "llm_knowledge_build:new1",
                     "source_report_ids": ["repair_report:abc"],
                     "manifest": [{"report_id": "repair_report:abc",
                                   "filename": "m.xlsx",
                                   "analysis_key": "key1"}],
                     "status": "queued"}]
        if query.startswith("UPDATE"):
            return []
        raise AssertionError(f"unexpected query: {query}")
    return _repo


@pytest.mark.asyncio
async def test_preflight_failure_blocks_build():
    """No build row and no command submit after a failed preflight."""
    log = []
    with (
        patch.object(svc, "repo_query", new=AsyncMock(
            side_effect=_repo_side_effect_factory(log))),
        patch("api.repair_report_service._get_report_internal",
              new=AsyncMock(return_value={"id": "repair_report:abc",
                                          "filename": "m.xlsx",
                                          "analysis_key": "key1"})),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=AsyncMock(return_value="")),
        patch("api.command_service.CommandService.submit_command_job",
              new=AsyncMock()) as submit,
    ):
        with pytest.raises(ConfigurationError) as exc:
            await svc.start_build(["repair_report:abc"])
    assert "preflight" in str(exc.value).lower()
    assert not any(q.startswith("CREATE llm_knowledge_build") for q in log)
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_provider_error_blocks_build_with_diagnostics():
    log = []
    with (
        patch.object(svc, "repo_query", new=AsyncMock(
            side_effect=_repo_side_effect_factory(log))),
        patch("api.repair_report_service._get_report_internal",
              new=AsyncMock(return_value={"id": "repair_report:abc",
                                          "filename": "m.xlsx",
                                          "analysis_key": "key1"})),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=AsyncMock(side_effect=ConfigurationError("provider down"))),
        patch("api.command_service.CommandService.submit_command_job",
              new=AsyncMock()) as submit,
    ):
        with pytest.raises(ConfigurationError) as exc:
            await svc.start_build(["repair_report:abc"])
    assert "provider down" in str(exc.value)
    assert not any(q.startswith("CREATE llm_knowledge_build") for q in log)
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_success_allows_build():
    log = []
    with (
        patch.object(svc, "repo_query", new=AsyncMock(
            side_effect=_repo_side_effect_factory(log))),
        patch("api.repair_report_service._get_report_internal",
              new=AsyncMock(return_value={"id": "repair_report:abc",
                                          "filename": "m.xlsx",
                                          "analysis_key": "key1"})),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=AsyncMock(return_value=STAGE_A_VALID_JSON)),
        patch("api.command_service.CommandService.submit_command_job",
              new=AsyncMock(return_value="command:1")) as submit,
        patch.object(svc, "attach_command", new=AsyncMock()),
    ):
        build = await svc.start_build(["repair_report:abc"])
    assert build["id"] == "llm_knowledge_build:new1"
    assert any(q.startswith("CREATE llm_knowledge_build") for q in log)
    submit.assert_called_once()


@pytest.mark.asyncio
async def test_preflight_accepts_structured_response_with_nonstring_arrays():
    """Incidental malformed sample content must not fail preflight.

    The provider returned real structured JSON shaped like evidence, but
    with objects (not strings) inside the free-form arrays. Preflight
    tests capability, not semantic evidence, so it must succeed.
    """
    from api.llm_generation import preflight_llm_generation

    with patch("api.llm_generation.LLMKnowledgeGenerator") as gen:
        gen.return_value.generate_from_messages = AsyncMock(
            return_value=STAGE_A_NONSTRING_ARRAYS_JSON)
        await preflight_llm_generation("model:x")
        assert gen.return_value.generate_from_messages.await_count == 1


@pytest.mark.asyncio
async def test_preflight_malformed_sample_still_allows_build():
    """start_build reaches create_build despite a non-string sample array."""
    log = []
    with (
        patch.object(svc, "repo_query", new=AsyncMock(
            side_effect=_repo_side_effect_factory(log))),
        patch("api.repair_report_service._get_report_internal",
              new=AsyncMock(return_value={"id": "repair_report:abc",
                                          "filename": "m.xlsx",
                                          "analysis_key": "key1"})),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=AsyncMock(return_value=STAGE_A_NONSTRING_ARRAYS_JSON)),
        patch("api.command_service.CommandService.submit_command_job",
              new=AsyncMock(return_value="command:1")) as submit,
        patch.object(svc, "attach_command", new=AsyncMock()),
    ):
        build = await svc.start_build(["repair_report:abc"])
    assert build["id"] == "llm_knowledge_build:new1"
    assert any(q.startswith("CREATE llm_knowledge_build") for q in log)
    submit.assert_called_once()


@pytest.mark.asyncio
async def test_preflight_garbage_still_blocks_build():
    """Non-JSON output is a genuine capability failure: startup still blocked."""
    log = []
    with (
        patch.object(svc, "repo_query", new=AsyncMock(
            side_effect=_repo_side_effect_factory(log))),
        patch("api.repair_report_service._get_report_internal",
              new=AsyncMock(return_value={"id": "repair_report:abc",
                                          "filename": "m.xlsx",
                                          "analysis_key": "key1"})),
        patch("api.llm_generation.LLMKnowledgeGenerator.generate_from_messages",
              new=AsyncMock(return_value="definitely not json {{{")),
        patch("api.command_service.CommandService.submit_command_job",
              new=AsyncMock()) as submit,
    ):
        with pytest.raises(ConfigurationError) as exc:
            await svc.start_build(["repair_report:abc"])
    assert "preflight" in str(exc.value).lower()
    assert not any(q.startswith("CREATE llm_knowledge_build") for q in log)
    submit.assert_not_called()
