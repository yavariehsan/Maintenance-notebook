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
    """Jaccard similarity over token sets (order-insensitive baseline)."""

    def __init__(self, tokenizer: Tokenizer) -> None:
        self.tokenizer = tokenizer

    @property
    def name(self) -> str:
        return "token-set-jaccard"

    def similarity(self, first: str, second: str) -> float:
        """Jaccard index of the two token sets; ``1.0`` when both are empty."""
        left = set(self.tokenizer.tokenize(first))
        right = set(self.tokenizer.tokenize(second))
        if not left and not right:
            return 1.0
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)


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
