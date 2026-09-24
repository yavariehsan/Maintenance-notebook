"""Versioned, UI-independent troubleshooting knowledge base."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maintenance_troubleshooting.domain.causes import DEFAULT_PROBABILITY_SEMANTICS
from maintenance_troubleshooting.domain.guides import TroubleshootingGuide


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TroubleshootingKnowledgeBase:
    """Container for generated guides plus provenance.

    Serialization is plain stdlib JSON (dataclasses → dicts); no schema
    library is required to read the artifact.
    """

    def __init__(
        self,
        engine_version: str,
        guides: list[TroubleshootingGuide] | None = None,
        source_path: str = "",
        record_count: int = 0,
        generated_at: str | None = None,
        probability_semantics: str = DEFAULT_PROBABILITY_SEMANTICS,
    ) -> None:
        self.engine_version = engine_version
        self.guides: list[TroubleshootingGuide] = list(guides or [])
        self.source_path = source_path
        self.record_count = record_count
        self.generated_at = generated_at or _utc_now_iso()
        self.probability_semantics = probability_semantics
        # Raw guide payloads as loaded from disk (typed rehydration of
        # nested enums is a later milestone; none are produced yet).
        self.raw_guides: list[dict[str, Any]] = []

    @classmethod
    def empty(cls, engine_version: str, source_path: str = "") -> TroubleshootingKnowledgeBase:
        """Knowledge base shell before the ranking milestone populates guides."""
        return cls(engine_version=engine_version, source_path=source_path)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable view of the knowledge base."""
        return {
            "engine_version": self.engine_version,
            "source_path": self.source_path,
            "record_count": self.record_count,
            "generated_at": self.generated_at,
            "probability_semantics": self.probability_semantics,
            "guides": [asdict(guide) for guide in self.guides],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string (``ensure_ascii=False`` for Persian)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, default=str)

    def save(self, path: str | Path) -> Path:
        """Write the JSON artifact to ``path`` (creates parent dirs)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> TroubleshootingKnowledgeBase:
        """Load an artifact written by :meth:`save` (guides as raw dicts).

        Guide dicts are returned as stored; typed rehydration of nested
        enums is a later milestone (the current milestone produces no
        guides yet).
        """
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        base = cls(
            engine_version=str(payload.get("engine_version", "")),
            source_path=str(payload.get("source_path", "")),
            record_count=int(payload.get("record_count", 0)),
            generated_at=str(payload.get("generated_at", "")),
            probability_semantics=str(
                payload.get("probability_semantics", DEFAULT_PROBABILITY_SEMANTICS)
            ),
        )
        base.raw_guides = payload.get("guides", [])
        return base
