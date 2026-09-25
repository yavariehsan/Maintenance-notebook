"""Stage 5 — FailureModeAnalyzer: mine canonical failure modes.

The literal ``حالت خرابی`` string is never the final mode. Normalized mode
texts are clustered with union-find over a combined lexical +
technical-context score; records without any mode text attach via symptom
similarity or become explicit ``unclassified`` singletons. Every record
keeps its original / normalized / canonical triple.

Two real-data guards keep generic wording from chaining distinct failures
together (see docs/algorithm-principles.md):

- technical context only boosts pairs that already share lexical
  substance (``min_lexical_for_tech_boost``);
- disjoint non-empty parenthetical category tags never merge (tagless
  wordings may still join any cluster).
"""

from __future__ import annotations

import re
from collections import Counter

from maintenance_troubleshooting.domain.failure import CanonicalFailureMode
from maintenance_troubleshooting.domain.records import MaintenanceRecord
from maintenance_troubleshooting.stages.base import PipelineContext
from maintenance_troubleshooting.text import (
    CharacterNGramSimilarity,
    SimpleTokenizer,
    TokenSetSimilarity,
)

_TAG_PATTERN = re.compile(r"\(([^()]*)\)")


def extract_tags(text: str) -> set[str]:
    """Parenthetical category tags, e.g. ``{"تعویض ابزار"}``.

    Workbook labels follow a ``Label (category)`` convention; tags are a
    separate, documented merge signal (never the label itself).
    """
    return {match.strip().lower() for match in _TAG_PATTERN.findall(text or "") if match.strip()}


class _UnionFind:
    """Deterministic union-find over record IDs."""

    def __init__(self, members: list[str]) -> None:
        self.parent = {member: member for member in members}

    def find(self, member: str) -> str:
        """Root of ``member`` with path compression."""
        root = member
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[member] != root:
            self.parent[member], member = root, self.parent[member]
        return root

    def union(self, first: str, second: str) -> None:
        """Merge the two sets (smaller root wins for determinism)."""
        root_first = self.find(first)
        root_second = self.find(second)
        if root_first == root_second:
            return
        winner, loser = sorted((root_first, root_second))
        self.parent[loser] = winner


class FailureModeAnalyzer:
    """Cluster normalized failure modes into canonical modes."""

    name = "failure-modes"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Mine modes; map every valid record to a canonical mode key."""
        mining = context.config.failure_mining
        tokenizer = SimpleTokenizer()
        # IDF weights over DISTINCT normalized mode wordings: generic words
        # shared across many wordings must not merge distinct failures.
        mode_texts = sorted(
            {
                context.normalized[record.record_id].normalized_failure_mode
                for record in context.valid_records
                if context.normalized[record.record_id].normalized_failure_mode
            }
        )
        frequencies: Counter[str] = Counter()
        for text in mode_texts:
            for token in set(tokenizer.tokenize(text)):
                frequencies[token] += 1
        token_similarity = TokenSetSimilarity(
            tokenizer,
            document_frequencies=dict(frequencies),
            total_documents=len(mode_texts),
        )
        # Symptom attach uses PLAIN Jaccard: the IDF table above is weighted
        # over mode wordings, a different population than symptom texts, so
        # applying it there would be dishonest weighting.
        symptom_similarity = TokenSetSimilarity(tokenizer)
        ngram_similarity = CharacterNGramSimilarity(
            n=context.config.similarity.char_ngram_n
        )
        by_id = {record.record_id: record for record in context.valid_records}
        ordered_ids = sorted(by_id)

        def tech_context(first_id: str, second_id: str) -> float:
            first = by_id[first_id].technical_tree.levels()[:3]
            second = by_id[second_id].technical_tree.levels()[:3]
            comparable = [
                a == b
                for a, b in zip(first, second)
                if a and b
            ]
            if not comparable:
                return 0.0
            return sum(1.0 for agree in comparable if agree) / len(comparable)

        def combined(
            first: str,
            second: str,
            first_text: str,
            second_text: str,
            first_raw: str,
            second_raw: str,
        ) -> float:
            lexical = max(
                token_similarity.similarity(first_text, second_text),
                ngram_similarity.similarity(first_text, second_text),
            )
            first_tags = extract_tags(first_raw)
            second_tags = extract_tags(second_raw)
            if first_tags and second_tags and not (first_tags & second_tags):
                return 0.0
            tech = (
                tech_context(first, second)
                if lexical >= mining.min_lexical_for_tech_boost
                else 0.0
            )
            return mining.lexical_weight * lexical + mining.tech_context_weight * tech

        with_mode = [
            rid
            for rid in ordered_ids
            if context.normalized[rid].normalized_failure_mode
        ]
        clusters: dict[str, list[str]] = {}

        def raw_mode_text(rid: str) -> str:
            record = by_id[rid]
            return (
                record.failure_mode_recorded or record.proposed_failure_mode or ""
            ).strip()

        if with_mode:
            union = _UnionFind(with_mode)
            for position, first in enumerate(with_mode):
                first_text = context.normalized[first].normalized_failure_mode
                first_raw = raw_mode_text(first)
                for second in with_mode[position + 1 :]:
                    second_text = context.normalized[second].normalized_failure_mode
                    if (
                        combined(
                            first,
                            second,
                            first_text,
                            second_text,
                            first_raw,
                            raw_mode_text(second),
                        )
                        >= mining.lexical_threshold
                    ):
                        union.union(first, second)
            for rid in with_mode:
                clusters.setdefault(union.find(rid), []).append(rid)

        def symptom_text(rid: str) -> str:
            return context.normalized[rid].normalized_symptom

        # Attach modeless records via symptom similarity, else singleton.
        attached: dict[str, str] = {}  # record_id -> cluster root
        for rid in ordered_ids:
            if rid in clusters or any(rid in members for members in clusters.values()):
                continue
            symptom = symptom_text(rid)
            best_root, best_score = "", 0.0
            for root, members in clusters.items():
                exemplar = context.normalized[members[0]].normalized_failure_mode
                score = symptom_similarity.similarity(symptom, exemplar)
                if score > best_score:
                    best_root, best_score = root, score
            if best_root and best_score >= mining.symptom_attach_threshold:
                attached[rid] = best_root
            else:
                clusters[f"singleton:{rid}"] = [rid]

        modes: dict[str, CanonicalFailureMode] = {}
        record_mode: dict[str, str] = {}
        root_to_key: dict[str, str] = {}
        labeled = sorted(
            clusters.items(), key=lambda item: self._cluster_label(item[1], by_id)
        )
        for index, (root, members) in enumerate(labeled, start=1):
            key = f"FM-{index:04d}"
            root_to_key[root] = key
            raws = sorted({raw_mode_text(rid) for rid in members if raw_mode_text(rid)})
            counts = Counter(raw_mode_text(rid) for rid in members if raw_mode_text(rid))
            if counts:
                top = max(counts.values())
                label = sorted(text for text, n in counts.items() if n == top)[0]
                status = (
                    "classified"
                    if not root.startswith("singleton:")
                    else "unclassified"
                )
            else:
                exemplar = symptom_text(members[0])[:60] or "unspecified"
                label = f"unspecified ({exemplar})"
                status = "unclassified"
            norm_counts = Counter(
                context.normalized[rid].normalized_failure_mode for rid in members
            )
            norm_top = max(norm_counts.values())
            normalized_label = sorted(
                text for text, n in norm_counts.items() if n == norm_top
            )[0]
            modes[key] = CanonicalFailureMode(
                key=key,
                canonical_label=label,
                normalized_label=normalized_label,
                aliases=raws,
                record_ids=sorted(members),
                status=status,
            )
            for rid in members:
                record_mode[rid] = key
        for rid, root in attached.items():
            key = root_to_key[root]
            record_mode[rid] = key
            mode = modes[key]
            mode.record_ids = sorted(set(mode.record_ids) | {rid})
        context.failure_modes = modes
        context.record_failure_mode = record_mode
        return context

    @staticmethod
    def _cluster_label(members: list[str], by_id: dict[str, MaintenanceRecord]) -> str:
        """Deterministic ordering label for key assignment (raw, smallest)."""
        raws = sorted(
            {
                (by_id[rid].failure_mode_recorded or by_id[rid].proposed_failure_mode or "").strip()
                for rid in members
            }
        )
        raws = [text for text in raws if text]
        return raws[0] if raws else f"~{sorted(members)[0]}"
