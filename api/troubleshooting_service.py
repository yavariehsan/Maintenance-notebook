"""Thin host adapter over the standalone troubleshooting engine.

Read-only runtime boundary (Phase B): this module resolves the configured
Troubleshooting Database, opens it through the engine's
``TroubleshootingRepository`` in read-only mode, and converts results to
plain host dicts. It performs no mining, no clustering, no similarity
computation, no Excel parsing, and no LLM calls — all expensive work
happens offline in Phase A batch generation.

Raw maintenance database (Excel workbook) vs Troubleshooting Database
(precomputed SQLite): the runtime only ever needs the second artifact.
The workbook path is never read here.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from loguru import logger

from open_notebook.config import DATA_FOLDER
from open_notebook.exceptions import (
    ConfigurationError,
    InvalidInputError,
    NotFoundError,
    OpenNotebookError,
)

# Explicit database file override. Otherwise the database resolves under
# the shared application data root (OPEN_NOTEBOOK_DATA_DIR convention).
TROUBLESHOOTING_DB_PATH_ENV_VAR = "TROUBLESHOOTING_DB_PATH"
TROUBLESHOOTING_DB_SUBDIR = "troubleshooting"
TROUBLESHOOTING_DB_FILENAME = "maintenance_troubleshooting.db"

_UNAVAILABLE_MESSAGE = (
    "Troubleshooting database unavailable. Generate it with the offline "
    "batch pipeline (maintenance-troubleshooting analyze) and point "
    "TROUBLESHOOTING_DB_PATH at the resulting SQLite file."
)


def _load_package() -> tuple[Any, Any, ImportError | None]:
    """Import the engine's public runtime API (installed or vendored).

    Prefers a properly installed ``maintenance_troubleshooting`` package;
    falls back to the vendored checkout layout
    (``packages/maintenance-troubleshooting-engine/src``) so development
    checkouts and the Docker image (which copies the whole repository)
    work without extra packaging steps. Returns
    ``(repository_class, schema_version, import_error)``.
    """
    try:
        from maintenance_troubleshooting import (
            TROUBLESHOOTING_SCHEMA_VERSION,
            TroubleshootingRepository,
        )

        return TroubleshootingRepository, TROUBLESHOOTING_SCHEMA_VERSION, None
    except ImportError as first_error:
        candidate = (
            Path(__file__).resolve().parent.parent
            / "packages"
            / "maintenance-troubleshooting-engine"
            / "src"
        )
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            try:
                from maintenance_troubleshooting import (
                    TROUBLESHOOTING_SCHEMA_VERSION,
                    TroubleshootingRepository,
                )

                return TroubleshootingRepository, TROUBLESHOOTING_SCHEMA_VERSION, None
            except ImportError as second_error:
                return None, None, second_error
        return None, None, first_error


TroubleshootingRepository, TROUBLESHOOTING_SCHEMA_VERSION, _PACKAGE_IMPORT_ERROR = (
    _load_package()
)
PACKAGE_AVAILABLE = TroubleshootingRepository is not None


def resolve_database_path() -> Path:
    """Resolve the configured Troubleshooting Database path.

    Explicit ``TROUBLESHOOTING_DB_PATH`` wins; otherwise the database
    lives under the shared application data root
    (``<DATA_FOLDER>/troubleshooting/maintenance_troubleshooting.db``),
    which follows ``OPEN_NOTEBOOK_DATA_DIR`` when set. Absolute paths are
    recommended for the explicit override.
    """
    explicit = os.environ.get(TROUBLESHOOTING_DB_PATH_ENV_VAR, "").strip()
    if explicit:
        return Path(explicit)
    return (
        Path(DATA_FOLDER)
        / TROUBLESHOOTING_DB_SUBDIR
        / TROUBLESHOOTING_DB_FILENAME
    )


def _require_package() -> Any:
    """Return the repository class or raise a host configuration error."""
    if not PACKAGE_AVAILABLE or TroubleshootingRepository is None:
        logger.error(
            "Troubleshooting engine package unavailable: "
            f"{_PACKAGE_IMPORT_ERROR}"
        )
        raise ConfigurationError(
            "Troubleshooting engine package is not installed. "
            "Install maintenance-troubleshooting-engine to enable "
            "troubleshooting reads."
        )
    return TroubleshootingRepository


def _open_repository() -> Any:
    """Open the configured database read-only (never creates, never writes).

    Filesystem paths stay in server logs; API consumers only ever see the
    generic unavailable message.
    """
    repository_class = _require_package()
    path = resolve_database_path()
    if not path.exists():
        logger.warning(f"Troubleshooting database missing: {path}")
        raise ConfigurationError(_UNAVAILABLE_MESSAGE)
    try:
        return repository_class(path, read_only=True)
    except FileNotFoundError:
        logger.warning(f"Troubleshooting database missing: {path}")
        raise ConfigurationError(_UNAVAILABLE_MESSAGE)
    except sqlite3.Error as e:
        logger.error(f"Troubleshooting database unreadable ({path}): {e}")
        raise ConfigurationError(_UNAVAILABLE_MESSAGE)


def get_status() -> dict[str, Any]:
    """Fast health report: configured/exists/readable/compatible/available.

    Never raises for an unhealthy database — the status payload carries
    the state so the rest of the host keeps working. States:
    ``available`` | ``missing`` | ``unreadable`` | ``incompatible`` |
    ``unavailable`` (engine package itself not installed).
    """
    path = resolve_database_path()
    if not PACKAGE_AVAILABLE:
        return {
            "state": "unavailable",
            "schema_version": None,
            "expected_schema_version": TROUBLESHOOTING_SCHEMA_VERSION,
            "equipment_count": None,
            "message": "Troubleshooting engine package is not installed.",
        }
    if not path.exists():
        return {
            "state": "missing",
            "schema_version": None,
            "expected_schema_version": TROUBLESHOOTING_SCHEMA_VERSION,
            "equipment_count": None,
            "message": _UNAVAILABLE_MESSAGE,
        }
    try:
        with _open_repository() as repository:
            metadata = repository.metadata()
    except ConfigurationError:
        # _open_repository already logged the path; keep the body generic.
        # A file that vanished between the exists() check and the open is
        # still "missing", not "unreadable".
        state = "missing" if not path.exists() else "unreadable"
        return {
            "state": state,
            "schema_version": None,
            "expected_schema_version": TROUBLESHOOTING_SCHEMA_VERSION,
            "equipment_count": None,
            "message": _UNAVAILABLE_MESSAGE,
        }
    except sqlite3.Error as e:
        logger.error(f"Troubleshooting database unreadable: {e}")
        return {
            "state": "unreadable",
            "schema_version": None,
            "expected_schema_version": TROUBLESHOOTING_SCHEMA_VERSION,
            "equipment_count": None,
            "message": _UNAVAILABLE_MESSAGE,
        }
    schema_version = metadata.get("schema_version")
    if schema_version != TROUBLESHOOTING_SCHEMA_VERSION:
        logger.error(
            "Troubleshooting database schema mismatch: "
            f"got {schema_version!r}, expected "
            f"{TROUBLESHOOTING_SCHEMA_VERSION!r}"
        )
        return {
            "state": "incompatible",
            "schema_version": schema_version,
            "expected_schema_version": TROUBLESHOOTING_SCHEMA_VERSION,
            "equipment_count": None,
            "message": (
                "Troubleshooting database schema is incompatible with this "
                "application version. Regenerate it with the offline batch "
                "pipeline."
            ),
        }
    try:
        with _open_repository() as repository:
            equipment_count = len(repository.list_equipment())
    except (ConfigurationError, sqlite3.Error) as e:
        logger.error(f"Troubleshooting database health query failed: {e}")
        return {
            "state": "unreadable",
            "schema_version": schema_version,
            "expected_schema_version": TROUBLESHOOTING_SCHEMA_VERSION,
            "equipment_count": None,
            "message": _UNAVAILABLE_MESSAGE,
        }
    return {
        "state": "available",
        "schema_version": schema_version,
        "expected_schema_version": TROUBLESHOOTING_SCHEMA_VERSION,
        "equipment_count": equipment_count,
        "message": "Troubleshooting database available.",
    }


def _read(operation: str, func: Any) -> Any:
    """Run a repository read, mapping storage errors to host errors."""
    try:
        return func()
    except (NotFoundError, InvalidInputError, ConfigurationError):
        raise
    except sqlite3.Error as e:
        logger.error(f"Troubleshooting database read failed ({operation}): {e}")
        raise ConfigurationError(_UNAVAILABLE_MESSAGE)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        logger.error(f"Malformed troubleshooting data ({operation}): {e}")
        raise OpenNotebookError(
            "Troubleshooting data is malformed; regenerate the database "
            "with the offline batch pipeline."
        )


def _require_equipment_code(code: str) -> str:
    cleaned = (code or "").strip()
    if not cleaned:
        raise InvalidInputError("Equipment code is required.")
    return cleaned


def list_equipment() -> list[dict[str, Any]]:
    """All equipment with record and failure-mode counts."""

    def _query() -> list[dict[str, Any]]:
        with _open_repository() as repository:
            return [asdict(item) for item in repository.list_equipment()]

    return _read("list_equipment", _query)


def get_equipment(code: str) -> dict[str, Any]:
    """One equipment by code, or 404."""

    def _query() -> dict[str, Any]:
        with _open_repository() as repository:
            item = repository.get_equipment(_require_equipment_code(code))
            if item is None:
                raise NotFoundError(f"Unknown equipment: {code.strip()}.")
            return asdict(item)

    return _read("get_equipment", _query)


def list_failure_modes(code: str) -> list[dict[str, Any]]:
    """Failure modes of one equipment (404 for unknown equipment)."""

    def _query() -> list[dict[str, Any]]:
        with _open_repository() as repository:
            cleaned = _require_equipment_code(code)
            if repository.get_equipment(cleaned) is None:
                raise NotFoundError(f"Unknown equipment: {cleaned}.")
            return [asdict(item) for item in repository.list_failure_modes(cleaned)]

    return _read("list_failure_modes", _query)


def _parse_id_list(raw: Any) -> list[str]:
    """Parse a JSON-encoded ID list stored by the batch writer."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise OpenNotebookError(
            "Troubleshooting data is malformed; regenerate the database "
            "with the offline batch pipeline."
        ) from e
    if not isinstance(parsed, list):
        raise OpenNotebookError(
            "Troubleshooting data is malformed; regenerate the database "
            "with the offline batch pipeline."
        )
    return [str(item) for item in parsed]


def _convert_action(action: dict[str, Any]) -> dict[str, Any]:
    """Action row → API shape (drops matching internals like *_json)."""
    return {
        "id": action.get("id"),
        "category": action.get("category"),
        "role": action.get("role"),
        "action_text": action.get("action_text"),
        "source_record_ids": _parse_id_list(action.get("source_record_ids_json")),
        "frequency": action.get("frequency"),
        "guide_instruction": action.get("guide_instruction"),
    }


def _convert_evidence(item: dict[str, Any]) -> dict[str, Any]:
    """Evidence row → API shape (keeps full source traceability)."""
    return {
        "id": item.get("id"),
        "record_id": item.get("record_id"),
        "equipment_code": item.get("equipment_code"),
        "relevance_basis": item.get("relevance_basis"),
        "relevance_detail": item.get("relevance_detail"),
        "weight": item.get("weight"),
        "symptom_text": item.get("symptom_text"),
        "repair_description": item.get("repair_description"),
    }


def _convert_cause(cause: Any) -> dict[str, Any]:
    """CauseView → API shape with precomputed values passed through."""
    return {
        "id": cause.id,
        "label": cause.label,
        "kinds": list(cause.kinds),
        "support_percent": cause.support_percent,
        "evidence_count": cause.evidence_count,
        "weighted_evidence": cause.weighted_evidence,
        "denominator": cause.denominator,
        "calculation_method": cause.calculation_method,
        "similarity_score": cause.similarity_score,
        "similarity_basis": cause.similarity_basis,
        "confidence": cause.confidence,
        "probability": cause.probability,
        "rank": cause.rank,
        "actions": [_convert_action(action) for action in cause.actions],
        "evidence": [_convert_evidence(item) for item in cause.evidence],
    }


def _guide_scope(code: str, mode_id: str) -> tuple[str, str]:
    cleaned_code = _require_equipment_code(code)
    cleaned_mode = (mode_id or "").strip()
    if not cleaned_mode:
        raise InvalidInputError("Failure mode ID is required.")
    return cleaned_code, cleaned_mode


def get_guide(code: str, mode_id: str) -> dict[str, Any]:
    """Assembled troubleshooting guide with causes, sections, safety notes."""

    def _query() -> dict[str, Any]:
        with _open_repository() as repository:
            cleaned_code, cleaned_mode = _guide_scope(code, mode_id)
            if repository.get_equipment(cleaned_code) is None:
                raise NotFoundError(f"Unknown equipment: {cleaned_code}.")
            guide = repository.get_troubleshooting_guide(cleaned_code, cleaned_mode)
            if guide is None:
                raise NotFoundError(
                    f"Unknown failure mode: {cleaned_mode} "
                    f"for equipment {cleaned_code}."
                )
            return {
                "equipment_code": guide.equipment_code,
                "failure_mode_id": guide.failure_mode_id,
                "failure_mode_label": guide.failure_mode_label,
                "symptom_summary": guide.symptom_summary,
                "causes": [_convert_cause(cause) for cause in guide.causes],
                "sections": [
                    {
                        "section": section.get("section"),
                        "title": section.get("title"),
                        "position": section.get("position"),
                        "body": section.get("body"),
                    }
                    for section in guide.sections
                ],
                "safety_notes": [
                    {
                        "note_text": note.get("note_text"),
                        "source_record_ids": _parse_id_list(
                            note.get("source_record_ids_json")
                        ),
                        "cause_ids": _parse_id_list(note.get("cause_ids_json")),
                    }
                    for note in guide.safety_notes
                ],
                "warnings": list(guide.warnings),
            }

    return _read("get_guide", _query)


def list_causes(code: str, mode_id: str) -> list[dict[str, Any]]:
    """Ranked candidate causes with precomputed support values."""

    def _query() -> list[dict[str, Any]]:
        with _open_repository() as repository:
            cleaned_code, cleaned_mode = _guide_scope(code, mode_id)
            if repository.get_equipment(cleaned_code) is None:
                raise NotFoundError(f"Unknown equipment: {cleaned_code}.")
            causes = repository.list_candidate_causes(cleaned_code, cleaned_mode)
            if not causes and (
                repository.get_troubleshooting_guide(cleaned_code, cleaned_mode)
                is None
            ):
                raise NotFoundError(
                    f"Unknown failure mode: {cleaned_mode} "
                    f"for equipment {cleaned_code}."
                )
            return [_convert_cause(cause) for cause in causes]

    return _read("list_causes", _query)


def list_evidence(code: str, mode_id: str) -> list[dict[str, Any]]:
    """Scope evidence rows with source record excerpts."""

    def _query() -> list[dict[str, Any]]:
        with _open_repository() as repository:
            cleaned_code, cleaned_mode = _guide_scope(code, mode_id)
            if repository.get_equipment(cleaned_code) is None:
                raise NotFoundError(f"Unknown equipment: {cleaned_code}.")
            rows = repository.list_evidence(cleaned_code, cleaned_mode)
            if not rows and (
                repository.get_troubleshooting_guide(cleaned_code, cleaned_mode)
                is None
            ):
                raise NotFoundError(
                    f"Unknown failure mode: {cleaned_mode} "
                    f"for equipment {cleaned_code}."
                )
            return [_convert_evidence(dict(row)) for row in rows]

    return _read("list_evidence", _query)
