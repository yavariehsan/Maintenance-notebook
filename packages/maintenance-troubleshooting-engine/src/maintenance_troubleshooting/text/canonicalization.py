"""Canonicalization: map spelling variants/abbreviations to one form.

Alias maps are explicit configuration (technician language varies by site
and crew), never hard-coded site vocabulary. The normalizer runs first;
aliases are keyed by normalized tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from maintenance_troubleshooting.text.tokenization import Tokenizer


@dataclass
class AliasMap:
    """Normalized alias → canonical token mapping."""

    mapping: dict[str, str] = field(default_factory=dict)

    def with_alias(self, alias: str, canonical: str) -> AliasMap:
        """Return a copy with one additional alias."""
        updated = dict(self.mapping)
        updated[alias] = canonical
        return AliasMap(mapping=updated)

    def canonicalize_token(self, token: str) -> str:
        """Map a single token; unknown tokens pass through unchanged."""
        return self.mapping.get(token, token)


class TextCanonicalizer:
    """Apply an alias map over tokenized text."""

    def __init__(self, aliases: AliasMap | None, tokenizer: Tokenizer) -> None:
        self.aliases = aliases or AliasMap()
        self.tokenizer = tokenizer

    def canonicalize(self, text: str) -> list[str]:
        """Tokenize then map each token to its canonical form."""
        return [
            self.aliases.canonicalize_token(token)
            for token in self.tokenizer.tokenize(text)
        ]

    def canonicalize_text(self, text: str) -> str:
        """Canonical token sequence re-joined for downstream matching."""
        return " ".join(self.canonicalize(text))
