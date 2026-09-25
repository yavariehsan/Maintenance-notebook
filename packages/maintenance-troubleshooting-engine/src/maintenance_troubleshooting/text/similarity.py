"""Lexical text similarity baselines (documented, dependency-free).

These are *lexical* measures for candidate retrieval plumbing — not
semantic claims. Semantic matching arrives later behind
``EmbeddingProvider`` with its own evaluation.
"""

from __future__ import annotations

from typing import Protocol

from maintenance_troubleshooting.text.tokenization import Tokenizer


class TextSimilarity(Protocol):
    """Compare two normalized texts, returning a weight in [0, 1]."""

    @property
    def name(self) -> str: ...

    def similarity(self, first: str, second: str) -> float: ...


class TokenSetSimilarity:
    """Jaccard similarity over token sets (order-insensitive baseline).

    With ``document_frequencies`` + ``total_documents``, uses IDF-weighted
    Jaccard so generic words shared across many wordings (خرابی، مشکل،
    error, …) contribute little, while specific shared terms dominate.
    Without frequencies it is plain Jaccard (backward compatible).
    """

    def __init__(
        self,
        tokenizer: Tokenizer,
        document_frequencies: dict[str, int] | None = None,
        total_documents: int = 0,
    ) -> None:
        self.tokenizer = tokenizer
        self.document_frequencies = document_frequencies
        self.total_documents = total_documents

    @property
    def name(self) -> str:
        """Measure name (records whether IDF weighting is active)."""
        return (
            "token-set-idf-jaccard"
            if self.document_frequencies is not None
            else "token-set-jaccard"
        )

    def _weight(self, token: str) -> float:
        """Smoothed IDF weight (1.0 when no frequency table is configured)."""
        if self.document_frequencies is None:
            return 1.0
        import math

        df = self.document_frequencies.get(token, 0)
        return math.log((self.total_documents + 1) / (df + 1)) + 1.0

    def similarity(self, first: str, second: str) -> float:
        """(Weighted) Jaccard index; ``1.0`` when both sides are empty."""
        left = set(self.tokenizer.tokenize(first))
        right = set(self.tokenizer.tokenize(second))
        if not left and not right:
            return 1.0
        if not left or not right:
            return 0.0
        if self.document_frequencies is None:
            return len(left & right) / len(left | right)
        shared = sum(self._weight(token) for token in left & right)
        total = sum(self._weight(token) for token in left | right)
        return shared / total if total > 0 else 0.0


class CharacterNGramSimilarity:
    """Jaccard similarity over character n-grams (typo-tolerant baseline)."""

    def __init__(self, n: int = 3) -> None:
        if n < 1:
            raise ValueError("n must be >= 1")
        self.n = n

    @property
    def name(self) -> str:
        return f"char-{self.n}gram-jaccard"

    def _ngrams(self, text: str) -> set[str]:
        compact = text.replace(" ", "")
        if len(compact) < self.n:
            return {compact} if compact else set()
        return {compact[i : i + self.n] for i in range(len(compact) - self.n + 1)}

    def similarity(self, first: str, second: str) -> float:
        """Jaccard index of the two n-gram sets; ``1.0`` when both empty."""
        left = self._ngrams(first)
        right = self._ngrams(second)
        if not left and not right:
            return 1.0
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)
