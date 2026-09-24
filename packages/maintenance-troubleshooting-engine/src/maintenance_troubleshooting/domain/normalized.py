"""Normalized record views (derived; originals stay on the record)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NormalizedRecord:
    """Normalized text copies for one canonical record.

    Every field derives from the verbatim source text via the configured
    normalizer. Matching and clustering read these; display and provenance
    always read the original ``MaintenanceRecord`` fields.
    """

    record_id: str
    equipment_code: str
    normalized_symptom: str = ""
    normalized_failure_mode: str = ""
    normalized_mechanism: str = ""
    normalized_cause: str = ""
    normalized_repair: str = ""
