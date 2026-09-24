"""Persian-aware text normalization for free-text fields.

Normalization is for *search/matching* copies only: originals are always
retained on the record. It must never be applied to identifiers
(equipment codes, request numbers) — see ``inputs.preserve_identifier``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Arabic presentation forms mapped to their Persian counterparts.
_ARABIC_TO_PERSIAN = {
    "\u064a": "\u06cc",  # ي → ی
    "\u0643": "\u06a9",  # ك → ک
    "\u0629": "\u0647",  # ة → ه
}

_DIACRITICS = re.compile("[\u064b-\u0652\u0670]")
_TATWEEL = "\u0640"
_WHITESPACE_RUN = re.compile(r"\s+")

_PERSIAN_DIGITS = {chr(0x06F0 + i): str(i) for i in range(10)}
_ARABIC_DIGITS = {chr(0x0660 + i): str(i) for i in range(10)}


@dataclass(frozen=True)
class TextNormalizationOptions:
    """Knobs for the normalizer; part of ``EngineConfig`` downstream."""

    fold_arabic_chars: bool = True
    remove_diacritics: bool = True
    remove_tatweel: bool = True
    fold_digits: bool = True
    collapse_whitespace: bool = True


class TextNormalizer:
    """Deterministic, dependency-free normalizer for mixed Persian text."""

    def __init__(self, options: TextNormalizationOptions | None = None) -> None:
        self.options = options or TextNormalizationOptions()

    def normalize(self, text: str | None) -> str:
        """Normalize free text; blank/None input yields ``""``."""
        if text is None:
            return ""
        value = str(text)
        if self.options.fold_arabic_chars:
            value = "".join(_ARABIC_TO_PERSIAN.get(ch, ch) for ch in value)
        if self.options.remove_diacritics:
            value = _DIACRITICS.sub("", value)
        if self.options.remove_tatweel:
            value = value.replace(_TATWEEL, "")
        if self.options.fold_digits:
            value = "".join(
                _PERSIAN_DIGITS.get(ch, _ARABIC_DIGITS.get(ch, ch)) for ch in value
            )
        # Compatibility decomposition catches remaining oddities
        # (e.g. presentation forms) without touching Persian letters.
        value = unicodedata.normalize("NFKC", value)
        if self.options.collapse_whitespace:
            value = _WHITESPACE_RUN.sub(" ", value).strip()
        else:
            value = value.strip()
        return value
