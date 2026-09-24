"""Engine configuration: self-contained, no host settings, no env vars.

Every section has explicit defaults; provider-specific blocks are optional
(``None`` = disabled). ``from_dict``/``to_dict`` round-trip through plain
JSON-compatible dicts so configurations can be versioned alongside outputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

from maintenance_troubleshooting.text.normalization import TextNormalizationOptions


@dataclass
class InputConfig:
    """Workbook reading options."""

    sheet_name: str | None = None
    header_row: int = 1


@dataclass
class NormalizationConfig:
    """Free-text normalization switches (identifiers are never normalized)."""

    fold_arabic_chars: bool = True
    remove_diacritics: bool = True
    remove_tatweel: bool = True
    fold_digits: bool = True
    collapse_whitespace: bool = True

    def to_options(self) -> TextNormalizationOptions:
        """Convert to the normalizer's options type."""
        return TextNormalizationOptions(
            fold_arabic_chars=self.fold_arabic_chars,
            remove_diacritics=self.remove_diacritics,
            remove_tatweel=self.remove_tatweel,
            fold_digits=self.fold_digits,
            collapse_whitespace=self.collapse_whitespace,
        )


@dataclass
class SimilarityConfig:
    """Technical/text similarity stage options (ranking is a later milestone)."""

    text_similarity: str = "token-set-jaccard"
    char_ngram_n: int = 3


@dataclass
class TextMiningConfig:
    """Text-mining stage options (extraction lives in later milestones)."""

    min_repair_length: int = 10
    aliases: dict[str, str] = field(default_factory=dict)


@dataclass
class EmbeddingConfig:
    """Optional embedding provider reference (disabled by default)."""

    provider: str | None = None
    model: str | None = None
    dimensions: int | None = None


@dataclass
class ScoringConfig:
    """Cause-scoring stage options (algorithm is a later milestone)."""

    probability_method: str = "proportional"


@dataclass
class OutputConfig:
    """Knowledge-base output options."""

    include_raw_records: bool = False
    indent: int = 2


@dataclass
class EngineConfig:
    """Root configuration: every section, no host leakage."""

    input: InputConfig = field(default_factory=InputConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    similarity: SimilarityConfig = field(default_factory=SimilarityConfig)
    text_mining: TextMiningConfig = field(default_factory=TextMiningConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    @classmethod
    def default(cls) -> EngineConfig:
        """Default configuration (no model names, URLs, or host paths)."""
        return cls()

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible view of the configuration."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EngineConfig:
        """Rebuild from :meth:`to_dict` output (unknown keys rejected)."""
        known = {
            "input": InputConfig,
            "normalization": NormalizationConfig,
            "similarity": SimilarityConfig,
            "text_mining": TextMiningConfig,
            "embedding": EmbeddingConfig,
            "scoring": ScoringConfig,
            "output": OutputConfig,
        }
        unknown = set(payload) - set(known)
        if unknown:
            raise ValueError(f"unknown configuration sections: {sorted(unknown)}")
        kwargs: dict[str, Any] = {}
        for section, factory in known.items():
            params = payload.get(section, {}) or {}
            allowed = {f.name for f in fields(factory)}
            unexpected = set(params) - allowed
            if unexpected:
                raise ValueError(
                    f"unknown keys in section '{section}': {sorted(unexpected)}"
                )
            kwargs[section] = factory(**{k: v for k, v in params.items() if k in allowed})
        return cls(**kwargs)
