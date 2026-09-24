"""Tokenization for mixed Persian/English maintenance text.

Tokens preserve model numbers, PLC/CNC terms, and axis/component names
(e.g. ``BR2``, ``X-AXIS``, ``ISO-VG68``); splitting is lexical only.
"""

from __future__ import annotations

import re
from typing import Protocol

_TOKEN_PATTERN = re.compile(r"[^\W_]+(?:[._\-/][^\W_]+)*", re.UNICODE)


class Tokenizer(Protocol):
    """Tokenize normalized text into comparable tokens."""

    def tokenize(self, text: str) -> list[str]: ...


class SimpleTokenizer:
    """Whitespace/punctuation splitter that keeps technical tokens whole."""

    def __init__(self, lowercase_latin: bool = True) -> None:
        self.lowercase_latin = lowercase_latin

    def tokenize(self, text: str) -> list[str]:
        """Split ``text`` into tokens; blank input yields ``[]``."""
        if not text:
            return []
        tokens = _TOKEN_PATTERN.findall(text)
        if self.lowercase_latin:
            tokens = [token.lower() if token.isascii() else token for token in tokens]
        return tokens
