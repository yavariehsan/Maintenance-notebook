"""Optional batch-enrichment boundary.

An enrichment provider receives explicit bounded inputs and returns
structured data. It never writes to SQLite: suggestions flow through
validation into knowledge synthesis, which owns the output database.
The default provider is a no-op; the core works without any LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class EnrichmentRecordRef:
    """Bounded per-record input for an enrichment provider."""

    record_id: str
    equipment_code: str
    symptom: str = ""
    repair: str = ""
    cause: str = ""
    mechanism: str = ""
    failure_mode_recorded: str = ""


@dataclass(frozen=True)
class EnrichmentInput:
    """One bounded enrichment request: a single (equipment, mode) scope."""

    equipment_code: str
    failure_mode_label: str
    records: tuple[EnrichmentRecordRef, ...] = ()
    technical_context: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SuggestedCause:
    """A provider-suggested candidate cause (must cite record IDs)."""

    cause_label: str
    kind: str
    basis_record_ids: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class SuggestedAction:
    """A provider-suggested repair action (must cite record IDs)."""

    action_text: str
    role: str = ""
    basis_record_ids: tuple[str, ...] = ()


@dataclass
class EnrichmentResult:
    """Structured provider output (validated before synthesis uses it)."""

    provider: str = "none"
    model: str | None = None
    canonical_label_suggestion: str | None = None
    suggested_causes: list[SuggestedCause] = field(default_factory=list)
    suggested_actions: list[SuggestedAction] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class KnowledgeEnrichmentProvider(Protocol):
    """Enrich one scope; return structured, validatable suggestions."""

    @property
    def name(self) -> str: ...

    def enrich(self, batch: EnrichmentInput) -> EnrichmentResult: ...


def validate_enrichment(
    result: EnrichmentResult, known_record_ids: set[str]
) -> tuple[EnrichmentResult, list[str]]:
    """Drop suggestions that cite unknown records or are blank.

    Returns the validated result plus human-readable warnings. Unknown
    record IDs and blank labels are the two rejection rules; everything
    accepted stays traceable to its basis records.
    """
    warnings: list[str] = []
    causes: list[SuggestedCause] = []
    for suggestion in result.suggested_causes:
        unknown = [rid for rid in suggestion.basis_record_ids if rid not in known_record_ids]
        if unknown:
            warnings.append(
                f"dropped suggested cause '{suggestion.cause_label}': "
                f"unknown record IDs {sorted(unknown)}"
            )
            continue
        if not suggestion.cause_label.strip():
            warnings.append("dropped suggested cause with blank label")
            continue
        causes.append(suggestion)
    actions: list[SuggestedAction] = []
    for action_suggestion in result.suggested_actions:
        unknown = [rid for rid in action_suggestion.basis_record_ids if rid not in known_record_ids]
        if unknown:
            warnings.append(
                f"dropped suggested action '{action_suggestion.action_text}': "
                f"unknown record IDs {sorted(unknown)}"
            )
            continue
        if not action_suggestion.action_text.strip():
            warnings.append("dropped suggested action with blank text")
            continue
        actions.append(action_suggestion)
    label = (result.canonical_label_suggestion or "").strip() or None
    validated = EnrichmentResult(
        provider=result.provider,
        model=result.model,
        canonical_label_suggestion=label,
        suggested_causes=causes,
        suggested_actions=actions,
        notes=list(result.notes),
    )
    return validated, warnings
