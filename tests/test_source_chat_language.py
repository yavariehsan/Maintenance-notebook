"""Answer-language rule in the source-chat system prompt.

Regression test: Persian questions were observed receiving Arabic answers.
The application had no explicit answer-language instruction, so the model
was free to pick a language (weak small models often fall back to Arabic
for Arabic-script prompts). The system prompt must instruct the model to
answer in the user's question language without hard-coding any language
for all users.
"""

from ai_prompter import Prompter


def _rendered_system_prompt():
    return Prompter(prompt_template="source_chat/system").render(
        data={
            "source": {"id": "source:abc", "title": "Test", "topics": []},
            "insights": [],
            "context": "Some context.",
            "context_indicators": {"sources": [], "insights": [], "notes": []},
        }
    )


def test_system_prompt_answers_in_user_question_language():
    prompt = _rendered_system_prompt()
    assert "same language as the user's question" in prompt


def test_system_prompt_names_persian_and_english_without_hardcoding():
    prompt = _rendered_system_prompt()
    assert "Persian" in prompt
    assert "English" in prompt
    # Must not force one language on every user.
    assert "always answer in Persian" not in prompt
    assert "always answer in English" not in prompt


def test_system_prompt_forbids_arabic_fallback_and_protects_identifiers():
    prompt = _rendered_system_prompt()
    assert "Do not switch to Arabic" in prompt
    assert "do not translate source identifiers or citation IDs" in prompt


def test_system_prompt_contains_no_arabic_answer_instruction():
    prompt = _rendered_system_prompt().lower()
    assert "answer in arabic" not in prompt
    assert "respond in arabic" not in prompt
