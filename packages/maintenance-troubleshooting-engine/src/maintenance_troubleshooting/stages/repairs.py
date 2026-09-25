"""Stage 9 — RepairActionMiner: repair text → structured actions.

Sentences are split on line/punctuation boundaries, classified into the
action taxonomy by keyword sets (Persian + English), and given a heuristic
role (diagnostic / corrective / verification / observed_issue). Actions
exist only if a historical sentence produced them — sparse records yield
no actions, and guides say so explicitly instead of inventing steps.
"""

from __future__ import annotations

import re
from collections import Counter

from maintenance_troubleshooting.domain.repairs import (
    ActionCategory,
    ActionRole,
    RepairAction,
)
from maintenance_troubleshooting.stages.base import PipelineContext
from maintenance_troubleshooting.text import TextNormalizer

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
    lowered = sentence.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return ActionCategory.OBSERVED_ISSUE


class RepairActionMiner:
    """Mine structured actions per (equipment, failure mode) scope."""

    name = "repair-actions"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Collect, classify, and dedupe actions within each scope."""
        normalizer = TextNormalizer(context.config.normalization.to_options())
        by_id = {record.record_id: record for record in context.valid_records}
        # (scope_equipment, scope_mode, normalized_sentence) -> record IDs
        groups: dict[tuple[str, str, str], list[str]] = {}
        exemplars: dict[tuple[str, str, str], str] = {}
        roles: dict[tuple[str, str, str], list[ActionRole]] = {}
        categories: dict[tuple[str, str, str], ActionCategory] = {}
        for item in context.evidence:
            record_id = item.record_id
            raw_repair = (by_id[record_id].repair_description or "").strip()
            if not raw_repair:
                continue  # sparse record: no actions, never invented
            seen_corrective = False
            for original in split_sentences(raw_repair):
                sentence = normalizer.normalize(original)
                if not sentence:
                    continue
                # Dedupe key is case-folded (same action, different casing);
                # the exemplar keeps the first-seen original wording.
                fold_key = sentence.casefold()
                category = classify_sentence(sentence)
                if category in (ActionCategory.TEST, ActionCategory.MEASURE) and seen_corrective:
                    role = ActionRole.VERIFICATION
                elif category in _DIAGNOSTIC_CATEGORIES:
                    role = ActionRole.DIAGNOSTIC
                elif category is ActionCategory.OBSERVED_ISSUE:
                    role = ActionRole.OBSERVED_ISSUE
                else:
                    role = ActionRole.CORRECTIVE
                    seen_corrective = True
                key = (item.scope_equipment, item.scope_failure_mode, fold_key)
                if record_id not in groups.setdefault(key, []):
                    groups[key].append(record_id)
                exemplars.setdefault(key, original)
                roles.setdefault(key, []).append(role)
                categories.setdefault(key, category)

        actions: list[RepairAction] = []
        ordered = sorted(
            groups, key=lambda key: (-len(groups[key]), exemplars[key])
        )
        counters: dict[tuple[str, str], int] = {}
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
            actions.append(
                RepairAction(
                    action_id=f"act-{equipment_code}-{mode_id}-{number:03d}",
                    category=categories[key],
                    role=role,
                    action_text=exemplars[key],
                    normalized_text=normalizer.normalize(exemplars[key]),
                    source_record_ids=record_ids,
                    frequency=len(record_ids),
                    equipment_code=equipment_code,
                    failure_mode_id=mode_id,
                )
            )
        context.repair_actions = actions
        return context
