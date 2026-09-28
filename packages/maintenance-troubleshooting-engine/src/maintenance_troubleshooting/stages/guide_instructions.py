"""Guide-facing instruction synthesis (M11C-6R2 Part B).

Deterministic, evidence-grounded transformation of an explicit historical
technical action into a limited technical instruction. No LLM, no
generative rewriting, no invented components/parameters/mechanisms.

Approved rule (single narrow shape): a sentence whose primary taxonomy
category is REPLACE, that also carries an explicit ADJUST match and a
test-and-handover marker, and that states the replacement could *not* be
completed (closed negation set around ``انجام``), yields exactly::

    در صورت عدم <replacement-phrase>، <component> بررسی و در صورت لزوم <verb> گردد.

Slots are filled verbatim from the sentence's own tokens:

- ``<replacement-phrase>``: the REPLACE keyword (``تعویض``) plus the
  immediately following component token(s), stopping before completion,
  conjunction or handover markers;
- ``<component>``: the token immediately preceding the ADJUST keyword;
- ``<verb>``: the matched ADJUST keyword itself (``تنظیم``).

Anything outside this shape returns ``None``: affirmed replacements,
missing adjustment, missing test/handover context, missing negation, or
unresolvable slots. In particular the rule never invents a replacement
(``تعویض`` must be present as a token), never invents a component, and
never adds an independent action — ``بررسی`` / ``در صورت لزوم`` are the
only coupled elaborations, and only inside this approved template.
"""

from __future__ import annotations

# Tokens that end the replacement-phrase scan: completion verbs, the
# conditional conjunction, handover/test markers and outcome markers.
_STOP_TOKENS = frozenset(
    {
        "انجام",
        "شد",
        "شده",
        "شود",
        "گردید",
        "گردد",
        "می",
        "میشود",
        "میشد",
        "نشد",
        "نمیشد",
        "که",
        "و",
        "تست",
        "تحویل",
        "آزمایش",
        "مشکل",
        "برطرف",
    }
)

# Closed negation set for "could not be completed" (token-level; the
# shared tokenizer already splits ZWNJ so ``نمی‌شد`` ≡ ``نمی شد``).
_NEGATION_SINGLETONS = frozenset({"نمیشد", "نشد"})
_NEGATION_BIGRAMS = frozenset(
    {
        ("نمی", "شد"),
        ("نمی", "شود"),
        ("نمی", "گردد"),
        ("نمی", "گردید"),
    }
)

#: The REPLACE keyword this rule is scoped to (single approved shape).
_REPLACE_KEYWORD = "تعویض"

#: ADJUST keywords eligible as the instruction verb (first match wins).
_ADJUST_KEYWORDS = ("تنظیم", "رگلاژ")

#: Required test-and-handover marker (substring on the normalized sentence).
_TEST_HANDOVER_SUBSTRING = "تست و تحویل"

_INSTRUCTION_TEMPLATE = "در صورت عدم {replacement}، {component} بررسی و در صورت لزوم {verb} گردد."


def _has_completion_negation(tokens: list[str]) -> bool:
    """Whether the token stream states the work could not be completed."""
    if "انجام" not in tokens:
        return False
    if any(token in _NEGATION_SINGLETONS for token in tokens):
        return True
    return any(
        (tokens[i], tokens[i + 1]) in _NEGATION_BIGRAMS
        for i in range(len(tokens) - 1)
    )


def _replacement_phrase(tokens: list[str]) -> str | None:
    """``تعویض`` + following component token(s); ``None`` when absent."""
    try:
        index = tokens.index(_REPLACE_KEYWORD)
    except ValueError:
        return None
    parts = [_REPLACE_KEYWORD]
    for token in tokens[index + 1 :]:
        if token in _STOP_TOKENS:
            break
        parts.append(token)
        # One component token is the approved shape; more would need
        # expert review, so stop after the first addition.
        break
    return " ".join(parts)


def _adjust_slot(tokens: list[str]) -> tuple[str, str] | None:
    """``(component, verb)`` around the first ADJUST keyword, else ``None``."""
    for position, token in enumerate(tokens):
        if token in _ADJUST_KEYWORDS:
            if position == 0:
                return None
            component = tokens[position - 1]
            if component in _STOP_TOKENS or component in _ADJUST_KEYWORDS:
                return None
            return component, token
    return None


def synthesize_guide_instruction(
    normalized_sentence: str,
    tokens: list[str],
    primary_is_replace: bool,
    has_adjust: bool,
) -> str | None:
    """Guide-facing instruction for one mined sentence, or ``None``.

    All four preconditions must hold: REPLACE primary, explicit ADJUST
    match, test-and-handover marker, and completion negation. Slots come
    verbatim from ``tokens``; any failure returns ``None``.
    """
    if not primary_is_replace or not has_adjust:
        return None
    if _TEST_HANDOVER_SUBSTRING not in normalized_sentence:
        return None
    if not _has_completion_negation(tokens):
        return None
    replacement = _replacement_phrase(tokens)
    slot = _adjust_slot(tokens)
    if replacement is None or slot is None:
        return None
    component, verb = slot
    return _INSTRUCTION_TEMPLATE.format(
        replacement=replacement, component=component, verb=verb
    )
