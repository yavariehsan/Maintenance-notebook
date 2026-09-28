"""Stage 9 — RepairActionMiner: repair text → structured actions.

Sentences are split on line/punctuation boundaries, classified into the
action taxonomy by token-aware keyword sets (Persian + English), and given
a heuristic role (diagnostic / corrective / verification / observed_issue).
Actions exist only if a historical sentence produced them — sparse records
yield no actions, and guides say so explicitly instead of inventing steps.

Admission (M11C D1): sentences shorter than
``TextMiningConfig.min_repair_length`` are rejected unless they
confidently name a known component/parameter (own-equipment tree tokens,
official aliases, or manufacturer-scoped induced terms, token-aware).

History/verification semantics (M11C D2/D4/D5, M11C-6R2 final): a closed set of
standalone closure phrases yields no RepairAction (history is kept on
the record); the canonical test-and-handover sentence yields a
TechnicalVerification plus a handover PostRepairEvent, bare ``تست شد``
yields a TechnicalVerification, and mixed technical+test/outcome
sentences additionally yield TechnicalVerification and PostRepairEvent
objects pointing at the same source sentence.
Matching is token-aware: keywords must occur as whole tokens (ASCII-only
inflections ed/d/s/es/ing allowed), so ``قطعه`` never matches ``قطع``.
"""

from __future__ import annotations

import re
from collections import Counter

from maintenance_troubleshooting.domain.repairs import (
    ActionCategory,
    ActionRole,
    HandoverEventType,
    PostRepairEvent,
    RepairAction,
    TechnicalVerification,
    VerificationEventType,
)
from maintenance_troubleshooting.stages.base import PipelineContext
from maintenance_troubleshooting.stages.guide_instructions import (
    synthesize_guide_instruction,
)
from maintenance_troubleshooting.text import SimpleTokenizer, TextNormalizer

_SENTENCE_SPLIT = re.compile(r"[\n]+|[.!?؟;]+")

# Priority order: corrective-leaning categories first so e.g. "repaired
# connector" classifies as REPAIR rather than CONNECT. Matching is
# substring on the lowercased normalized sentence (documented heuristic).
_CATEGORY_KEYWORDS: tuple[tuple[ActionCategory, tuple[str, ...]], ...] = (
    (ActionCategory.REPLACE, ("تعویض", "جایگزین", "replace", "renew")),
    (ActionCategory.REPAIR, ("تعمیر", "repair", "اصلاح", "بازسازی", "fix", "rework")),
    (ActionCategory.BYPASS, ("bypass", "بای پس", "بایپس", "میانبر")),
    (
        ActionCategory.PARAMETER_CHANGE,
        ("تغییر پارامتر", "parameter change", "پارامتر عوض"),
    ),
    (ActionCategory.CALIBRATE, ("کالیبر", "calibrat")),
    (ActionCategory.ALIGN, ("تراز", "هم محور", "هممحور", "align")),
    (ActionCategory.ADJUST, ("تنظیم", "adjust", "رگلاژ", "regulate")),
    (ActionCategory.TIGHTEN, ("سفت", "محکم", "tighten", "torque", "آچار")),
    (ActionCategory.CONNECT, ("اتصال", "وصل", "سیم کشی", "سیمکشی", "connect", "wiring", "wire")),
    (ActionCategory.DISCONNECT, ("قطع", "جدا", "disconnect")),
    (ActionCategory.LUBRICATE, ("روغن", "گریس", "lubricat", "grease", "oil")),
    (ActionCategory.CLEAN, ("تمیز", "نظافت", "clean", "شستشو", "wash")),
    (ActionCategory.MEASURE, ("اندازه", "measure", "مولتی", "کولیس", "meter", "گیج")),
    (ActionCategory.TEST, ("تست", "آزمایش", "test", "trial")),
    (ActionCategory.RESET, ("ریست", "reset")),
    (ActionCategory.CONFIGURE, ("configure", "program", "برنامه", "نرم افزار")),
    (ActionCategory.RESTORE, ("بازگردان", "restore", "احیا", "برگردان")),
    (ActionCategory.CHECK, ("چک", "کنترل", "بررسی", "check")),
    (ActionCategory.INSPECT, ("بازدید", "مشاهده", "بازبینی", "inspect", "visual")),
)

_MATCH_TOKENIZER = SimpleTokenizer()

#: ASCII inflection endings accepted after an exact keyword stem, checked
#: longest-first. Latin-only: Persian morphology is never stemmed, so an
#: inflected Persian form that is not an exact token simply does not match
#: (documented recall trade-off; prevents a new class of false positives).
_ASCII_INFLECTIONS = ("ing", "es", "ed", "d", "s")

#: Standalone closure/handover/outcome phrases (canonical spellings; matched
#: by normalized equality). Expert-approved HISTORY_ONLY set (M11C D2/D5,
#: final M11C-6R2 decision): these yield no RepairAction. ``تست و تحویل شد``
#: yields a TechnicalVerification plus a handover PostRepairEvent; bare
#: ``تست شد`` yields a TechnicalVerification (test); the rest yield a
#: PostRepairEvent by family. History is always kept on the record itself.
_HISTORY_ONLY_PHRASES = (
    "تحویل شد",
    "تحویل گردید",
    "تحویل گرفته شد",
    "تست شد",
    "تست و تحویل شد",
    "مشکل رفع شد",
    "برطرف گردید",
)

#: Exact test-and-handover sentence (normalized form).
_TEST_HANDOVER_PHRASE = "تست و تحویل شد"

#: Standalone `تست شد` (M11C-6R2 final): retained in history and emitted
#: as a TechnicalVerification (test) — never a recommended RepairAction.
_TEST_ONLY_PHRASE = "تست شد"

#: Substrings marking test+handover / outcome inside longer sentences.
_TEST_HANDOVER_SUBSTRING = "تست و تحویل"
_OUTCOME_MARKERS = ("برطرف شد", "برطرف گردید")


def _tokens(text: str) -> list[str]:
    """Tokenize already-normalized text for matching.

    ZWNJ (U+200C) is not a word character, so the tokenizer splits on it:
    ``می‌شود`` and ``می شود`` produce identical token streams, which is
    exactly the approved context-specific equivalence (no blanket rewrite
    of the stored text).
    """
    return _MATCH_TOKENIZER.tokenize(text)


def _token_matches(keyword: str, tokens: list[str]) -> bool:
    """Whether a keyword occurs as whole tokens (M11C D6).

    Single-token keywords match identical tokens, plus ASCII-inflected
    forms (``checked`` → ``check``). Persian keywords match identical
    tokens only: ``قطعه`` never matches ``قطع``. A single leading ``و``
    (the attached conjunction "and", e.g. ``وتعویض``) is stripped before
    matching — pure orthography, not stemming; a token that already is a
    keyword (e.g. ``وصل``) always matches exactly first.
    """
    for token in tokens:
        if token == keyword:
            return True
        stripped = token[1:] if token.startswith("و") and len(token) > 1 else token
        if stripped == keyword:
            return True
        if (
            keyword.isascii()
            and stripped.isascii()
            and stripped.startswith(keyword)
            and stripped[len(keyword):] in _ASCII_INFLECTIONS
        ):
            return True
    return False


def _phrase_matches(keyword_tokens: list[str], tokens: list[str]) -> bool:
    """Contiguous token-subsequence match for multi-word keywords."""
    width = len(keyword_tokens)
    if width == 1:
        return _token_matches(keyword_tokens[0], tokens)
    return any(
        tokens[start:start + width] == keyword_tokens
        for start in range(len(tokens) - width + 1)
    )


def match_categories(sentence: str) -> list[ActionCategory]:
    """All matching taxonomy categories in priority order (M11C D3).

    The first entry preserves the historical primary classification;
    the rest are the sentence's secondary types. Empty means no keyword
    matched (observed issue).
    """
    tokens = _tokens(sentence.lower())
    matched: list[ActionCategory] = []
    for category, keywords in _CATEGORY_KEYWORDS:
        for keyword in keywords:
            keyword_tokens = _tokens(keyword.lower())
            if keyword_tokens and _phrase_matches(keyword_tokens, tokens):
                matched.append(category)
                break
    return matched


_DIAGNOSTIC_CATEGORIES = frozenset(
    {ActionCategory.INSPECT, ActionCategory.CHECK, ActionCategory.MEASURE, ActionCategory.TEST}
)

_ROLE_PRIORITY = (
    ActionRole.CORRECTIVE,
    ActionRole.VERIFICATION,
    ActionRole.DIAGNOSTIC,
    ActionRole.OBSERVED_ISSUE,
)


def split_sentences(text: str) -> list[str]:
    """Split a repair description into non-empty sentences (documented)."""
    return [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]


def classify_sentence(sentence: str) -> ActionCategory:
    """First matching taxonomy category (priority order), else observed."""
    matched = match_categories(sentence)
    return matched[0] if matched else ActionCategory.OBSERVED_ISSUE


def _vocabulary_tokens(
    context: PipelineContext, normalizer: TextNormalizer
) -> dict[str, set[str]]:
    """Candidate component/parameter tokens per record (M11C D1).

    Explicit precedence tiers (highest first), unioned per record:

    1. own-equipment tree tokens (``trees[code]``);
    2. official text-mining aliases (``alias_tokens``);
    3. manufacturer-scoped induced terms (``induced``): tokens seen ≥2
       times in same-manufacturer repair text that also occur in a
       same-manufacturer tree or the aliases — never arbitrary
       repeated words.

    Token-aware throughout; deterministic ordering. Admission checks
    tiers in this order (see ``_admission_tier``); the union result is
    identical but the tier trace shows *why* a short sentence passed.
    """
    tokenizer = SimpleTokenizer()

    def tree_tokens(values: list[str | None]) -> set[str]:
        tokens: set[str] = set()
        for value in values:
            if value:
                tokens.update(tokenizer.tokenize(normalizer.normalize(value)))
        return tokens

    trees: dict[str, set[str]] = {}
    manufacturers: dict[str, str] = {}
    for code in sorted(context.equipment):
        equipment = context.equipment[code]
        trees[code] = tree_tokens(list(equipment.technical_tree.levels()))
        manufacturers[code] = (equipment.manufacturer or "").strip()
    alias_tokens: set[str] = set()
    for key, value in sorted(context.config.text_mining.aliases.items()):
        alias_tokens.update(tokenizer.tokenize(normalizer.normalize(key)))
        alias_tokens.update(tokenizer.tokenize(normalizer.normalize(value)))

    # Manufacturer-scoped observation counts over repair sentences.
    observed: dict[str, Counter[str]] = {}
    for record in sorted(context.valid_records, key=lambda r: r.record_id):
        group = manufacturers.get(record.equipment_code, "")
        counts = observed.setdefault(group, Counter())
        repair = (record.repair_description or "").strip()
        if not repair:
            continue
        for original in split_sentences(repair):
            sentence = normalizer.normalize(original)
            if sentence:
                counts.update(tokenizer.tokenize(sentence))

    group_trees: dict[str, set[str]] = {}
    for code in sorted(context.equipment):
        group_trees.setdefault(manufacturers.get(code, ""), set()).update(trees[code])

    vocab: dict[str, set[str]] = {}
    for record in context.valid_records:
        group = manufacturers.get(record.equipment_code, "")
        induced = {
            token
            for token, count in observed.get(group, Counter()).items()
            if count >= 2 and token in group_trees.get(group, set())
        }
        vocab[record.record_id] = (
            trees.get(record.equipment_code, set()) | alias_tokens | induced
        )
    return vocab


def _admission_tier(
    sentence_tokens: set[str],
    own_tree: set[str],
    alias_tokens: set[str],
    induced_tokens: set[str],
) -> str | None:
    """Which vocabulary tier admits a short sentence, if any (M11C D1).

    Pure traceability helper: checks tiers in precedence order
    (tree → alias → induced). Returns ``"tree"`` / ``"alias"`` /
    ``"induced"`` or ``None``. The miner admits on the union, so this
    never changes admission — it only explains it.
    """
    if sentence_tokens & own_tree:
        return "tree"
    if sentence_tokens & alias_tokens:
        return "alias"
    if sentence_tokens & induced_tokens:
        return "induced"
    return None


class RepairActionMiner:
    """Mine structured actions per (equipment, failure mode) scope."""

    name = "repair-actions"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Collect, classify, and dedupe actions within each scope."""
        normalizer = TextNormalizer(context.config.normalization.to_options())
        min_length = context.config.text_mining.min_repair_length
        history_only = frozenset(
            normalizer.normalize(phrase) for phrase in _HISTORY_ONLY_PHRASES
        )
        test_handover = normalizer.normalize(_TEST_HANDOVER_PHRASE)
        test_only = normalizer.normalize(_TEST_ONLY_PHRASE)
        vocab = _vocabulary_tokens(context, normalizer)
        by_id = {record.record_id: record for record in context.valid_records}
        # (scope_equipment, scope_mode, normalized_sentence) -> record IDs
        groups: dict[tuple[str, str, str], list[str]] = {}
        exemplars: dict[tuple[str, str, str], str] = {}
        roles: dict[tuple[str, str, str], list[ActionRole]] = {}
        categories: dict[tuple[str, str, str], ActionCategory] = {}
        secondaries: dict[tuple[str, str, str], list[ActionCategory]] = {}
        # Guide-facing synthesized instruction per sentence key (M11C-6R2
        # Part B): set once from the exemplar sentence; None when the
        # narrow approved shape does not hold.
        instructions: dict[tuple[str, str, str], str | None] = {}
        verifications: list[TechnicalVerification] = []
        events: list[PostRepairEvent] = []
        verification_counters: dict[tuple[str, str], int] = {}
        event_counters: dict[tuple[str, str], int] = {}
        # Mixed-sentence links resolved after action numbering below:
        # (kind, event_type, key, record_id, original).
        pending_links: list[tuple[str, str, tuple[str, str, str], str, str]] = []
        seen_mixed: set[tuple[tuple[str, str, str], str]] = set()
        for item in context.evidence:
            record_id = item.record_id
            raw_repair = (by_id[record_id].repair_description or "").strip()
            if not raw_repair:
                continue  # sparse record: no actions, never invented
            seen_corrective = False
            record_vocab = vocab.get(record_id, set())
            for original in split_sentences(raw_repair):
                sentence = normalizer.normalize(original)
                if not sentence:
                    continue
                key = (item.scope_equipment, item.scope_failure_mode, sentence.casefold())
                if sentence in history_only:
                    # M11C D2/D5: standalone closure/verification phrasing
                    # stays in history; never a recommended RepairAction.
                    # Checked before the length floor so short listed
                    # phrases are recorded, not silently dropped.
                    self._emit_standalone_history(
                        sentence, test_handover, test_only, key, record_id, original,
                        verifications, events,
                        verification_counters, event_counters,
                    )
                    continue
                sentence_tokens = set(_tokens(sentence.lower()))
                if len(sentence) < min_length and not (
                    sentence_tokens & record_vocab
                ):
                    # M11C D1: short fragment without an attributable
                    # component/parameter is not an action.
                    continue
                matched = match_categories(sentence)
                category = matched[0] if matched else ActionCategory.OBSERVED_ISSUE
                if category in (ActionCategory.TEST, ActionCategory.MEASURE) and seen_corrective:
                    role = ActionRole.VERIFICATION
                elif category in _DIAGNOSTIC_CATEGORIES:
                    role = ActionRole.DIAGNOSTIC
                elif category is ActionCategory.OBSERVED_ISSUE:
                    role = ActionRole.OBSERVED_ISSUE
                else:
                    role = ActionRole.CORRECTIVE
                    seen_corrective = True
                if record_id not in groups.setdefault(key, []):
                    groups[key].append(record_id)
                exemplars.setdefault(key, original)
                roles.setdefault(key, []).append(role)
                categories.setdefault(key, category)
                secondaries.setdefault(key, matched[1:])
                if key not in instructions:
                    # M11C-6R2 Part B: guide-facing instruction for the
                    # approved narrow shape only; anything else is None.
                    instructions[key] = synthesize_guide_instruction(
                        sentence,
                        _tokens(sentence.lower()),
                        primary_is_replace=(
                            category is ActionCategory.REPLACE
                        ),
                        has_adjust=(ActionCategory.ADJUST in matched),
                    )
                if (key, record_id) not in seen_mixed:
                    seen_mixed.add((key, record_id))
                    self._mark_mixed_semantics(
                        sentence, category, key, record_id, original, pending_links,
                    )

        actions: list[RepairAction] = []
        ordered = sorted(
            groups, key=lambda key: (-len(groups[key]), exemplars[key])
        )
        counters: dict[tuple[str, str], int] = {}
        action_ids: dict[tuple[str, str, str], str] = {}
        for equipment_code, mode_id, sentence in ordered:
            counters[(equipment_code, mode_id)] = counters.get((equipment_code, mode_id), 0) + 1
            number = counters[(equipment_code, mode_id)]
            key = (equipment_code, mode_id, sentence)
            role_counts = Counter(roles[key])
            top = max(role_counts.values())
            role = sorted(
                (r for r, n in role_counts.items() if n == top),
                key=lambda r: _ROLE_PRIORITY.index(r),
            )[0]
            record_ids = sorted(groups[key])
            action_id = f"act-{equipment_code}-{mode_id}-{number:03d}"
            action_ids[key] = action_id
            actions.append(
                RepairAction(
                    action_id=action_id,
                    category=categories[key],
                    role=role,
                    action_text=exemplars[key],
                    normalized_text=normalizer.normalize(exemplars[key]),
                    source_record_ids=record_ids,
                    frequency=len(record_ids),
                    equipment_code=equipment_code,
                    failure_mode_id=mode_id,
                    secondary_categories=secondaries.get(key, []),
                    guide_instruction=instructions.get(key),
                )
            )
        for kind, event_type, key, record_id, original in pending_links:
            equipment_code, mode_id, _ = key
            linked_action_id = action_ids.get(key)
            if kind == "verification":
                verification_counters[(equipment_code, mode_id)] = (
                    verification_counters.get((equipment_code, mode_id), 0) + 1
                )
                number = verification_counters[(equipment_code, mode_id)]
                verifications.append(
                    TechnicalVerification(
                        verification_id=f"ver-{equipment_code}-{mode_id}-{number:03d}",
                        record_id=record_id,
                        sentence=original,
                        event_type=VerificationEventType(event_type),
                        equipment_code=equipment_code,
                        failure_mode_id=mode_id,
                        repair_action_id=linked_action_id,
                    )
                )
            else:
                event_counters[(equipment_code, mode_id)] = (
                    event_counters.get((equipment_code, mode_id), 0) + 1
                )
                number = event_counters[(equipment_code, mode_id)]
                events.append(
                    PostRepairEvent(
                        event_id=f"evt-{equipment_code}-{mode_id}-{number:03d}",
                        record_id=record_id,
                        sentence=original,
                        event_type=HandoverEventType(event_type),
                        equipment_code=equipment_code,
                        failure_mode_id=mode_id,
                        repair_action_id=linked_action_id,
                    )
                )
        context.repair_actions = actions
        context.technical_verifications = verifications
        context.post_repair_events = events
        return context

    @staticmethod
    def _emit_standalone_history(
        sentence: str,
        test_handover: str,
        test_only: str,
        key: tuple[str, str, str],
        record_id: str,
        original: str,
        verifications: list[TechnicalVerification],
        events: list[PostRepairEvent],
        verification_counters: dict[tuple[str, str], int],
        event_counters: dict[tuple[str, str], int],
    ) -> None:
        """Standalone closure phrasing: history objects only, no RepairAction.

        The canonical test-and-handover sentence yields a verification and
        a handover event (M11C D4/D5); bare ``تست شد`` yields a test
        verification (M11C-6R2 final — history + verification, never a
        recommended action); every other listed phrase yields a
        handover/outcome event by family.
        """
        equipment_code, mode_id, _ = key
        if sentence == test_only:
            verification_counters[(equipment_code, mode_id)] = (
                verification_counters.get((equipment_code, mode_id), 0) + 1
            )
            number = verification_counters[(equipment_code, mode_id)]
            verifications.append(
                TechnicalVerification(
                    verification_id=f"ver-{equipment_code}-{mode_id}-{number:03d}",
                    record_id=record_id,
                    sentence=original,
                    event_type=VerificationEventType.TEST,
                    equipment_code=equipment_code,
                    failure_mode_id=mode_id,
                )
            )
            return
        if sentence == test_handover:
            verification_counters[(equipment_code, mode_id)] = (
                verification_counters.get((equipment_code, mode_id), 0) + 1
            )
            number = verification_counters[(equipment_code, mode_id)]
            verifications.append(
                TechnicalVerification(
                    verification_id=f"ver-{equipment_code}-{mode_id}-{number:03d}",
                    record_id=record_id,
                    sentence=original,
                    event_type=VerificationEventType.TEST,
                    equipment_code=equipment_code,
                    failure_mode_id=mode_id,
                )
            )
            event_counters[(equipment_code, mode_id)] = (
                event_counters.get((equipment_code, mode_id), 0) + 1
            )
            number = event_counters[(equipment_code, mode_id)]
            events.append(
                PostRepairEvent(
                    event_id=f"evt-{equipment_code}-{mode_id}-{number:03d}",
                    record_id=record_id,
                    sentence=original,
                    event_type=HandoverEventType.HANDOVER,
                    equipment_code=equipment_code,
                    failure_mode_id=mode_id,
                )
            )
            return
        event_type = (
            HandoverEventType.HANDOVER
            if "تحویل" in sentence
            else HandoverEventType.OUTCOME
        )
        event_counters[(equipment_code, mode_id)] = (
            event_counters.get((equipment_code, mode_id), 0) + 1
        )
        number = event_counters[(equipment_code, mode_id)]
        events.append(
            PostRepairEvent(
                event_id=f"evt-{equipment_code}-{mode_id}-{number:03d}",
                record_id=record_id,
                sentence=original,
                event_type=event_type,
                equipment_code=equipment_code,
                failure_mode_id=mode_id,
            )
        )

    @staticmethod
    def _mark_mixed_semantics(
        sentence: str,
        category: ActionCategory,
        key: tuple[str, str, str],
        record_id: str,
        original: str,
        pending_links: list[tuple[str, str, tuple[str, str, str], str, str]],
    ) -> None:
        """Record verification/event marks for a technical sentence.

        Fires only when the sentence carries an approved marker *and*
        yields a technical RepairAction (primary category other than
        observed_issue): “تست و تحویل” gives verification+event,
        approved outcome markers give verification. Markers alone, or
        markers on observed-only sentences, change nothing here.
        """
        if category is ActionCategory.OBSERVED_ISSUE:
            return
        if _TEST_HANDOVER_SUBSTRING in sentence:
            pending_links.append(("verification", "test", key, record_id, original))
            pending_links.append(("event", "handover", key, record_id, original))
        for marker in _OUTCOME_MARKERS:
            if marker in sentence:
                pending_links.append(("verification", "outcome", key, record_id, original))
                break
