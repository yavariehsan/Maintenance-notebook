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
    """Technical/text similarity stage options.

    ``technical_weights`` maps technical-similarity category names to
    support weights in [0, 1] (analytical hierarchy, configurable and
    documented — not arbitrary percentages).
    """

    text_similarity: str = "token-set-jaccard"
    char_ngram_n: int = 3
    technical_weights: dict[str, float] = field(
        default_factory=lambda: {
            "exact_equipment": 1.0,
            "same_model": 0.8,
            "same_manufacturer_and_type": 0.6,
            "same_equipment_type": 0.45,
            "same_subclass": 0.30,
            "same_main_class": 0.15,
            "unrelated": 0.0,
            "indeterminate": 0.0,
        }
    )


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
    """Cause-scoring stage options (deterministic, documented methods)."""

    probability_method: str = "proportional"
    support_method: str = "similarity-weighted-share-v1"
    confidence_high_min_count: int = 5
    confidence_high_min_denominator: float = 4.0
    confidence_medium_min_count: int = 3
    confidence_medium_min_denominator: float = 2.0


@dataclass
class FailureMiningConfig:
    """Failure-mode clustering thresholds (lexical, deterministic)."""

    lexical_threshold: float = 0.55
    symptom_attach_threshold: float = 0.40
    lexical_weight: float = 0.7
    tech_context_weight: float = 0.3


@dataclass
class CauseMiningConfig:
    """Cause/repair mining options."""

    include_mechanism_causes: bool = True
    max_actions_per_cause: int = 8


@dataclass
class EnrichmentConfig:
    """Optional batch enrichment (default off; never required)."""

    provider: str = "none"
    model: str | None = None
    max_records_per_scope: int = 20


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
    failure_mining: FailureMiningConfig = field(default_factory=FailureMiningConfig)
    cause_mining: CauseMiningConfig = field(default_factory=CauseMiningConfig)
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)

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
            "failure_mining": FailureMiningConfig,
            "cause_mining": CauseMiningConfig,
            "enrichment": EnrichmentConfig,
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
