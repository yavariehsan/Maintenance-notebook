from typing import List, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from api import troubleshooting_service as troubleshooting
from open_notebook.exceptions import OpenNotebookError

router = APIRouter()


class TroubleshootingStatus(BaseModel):
    """Runtime health of the Troubleshooting Database (never fails)."""

    state: str = Field(
        ...,
        description="available | missing | unreadable | incompatible | unavailable",
    )
    schema_version: Optional[str] = Field(
        None, description="Schema version recorded in the database, if readable"
    )
    expected_schema_version: Optional[str] = Field(
        None, description="Schema version this application understands"
    )
    equipment_count: Optional[int] = Field(
        None, description="Equipment rows, when the database is available"
    )
    message: str = Field(..., description="Human-readable status, no filesystem paths")


class EquipmentItem(BaseModel):
    """One equipment with record and failure-mode counts."""

    code: str = Field(..., description="Stable equipment code")
    name: Optional[str] = Field(None, description="Equipment display name")
    manufacturer: Optional[str] = Field(None, description="Manufacturer (t4)")
    model: Optional[str] = Field(None, description="Model (t5)")
    record_count: int = Field(..., description="Historical records for this equipment")
    failure_mode_count: int = Field(..., description="Attested failure modes")


class FailureModeItem(BaseModel):
    """One canonical failure mode of an equipment."""

    id: str = Field(..., description="Canonical failure-mode ID")
    label: str = Field(..., description="Canonical label")
    record_count: int = Field(..., description="Records in this mode")
    cause_count: int = Field(..., description="Candidate causes in this mode")


class CauseActionItem(BaseModel):
    """A repair action linked to a candidate cause."""

    id: Optional[str] = Field(None, description="Action ID")
    category: Optional[str] = Field(None, description="Action taxonomy category")
    role: Optional[str] = Field(
        None, description="diagnostic | corrective | verification | observed_issue"
    )
    action_text: Optional[str] = Field(None, description="Original repair sentence")
    source_record_ids: List[str] = Field(
        default_factory=list, description="Supporting record IDs"
    )
    frequency: Optional[int] = Field(None, description="Supporting record count")


class CauseEvidenceItem(BaseModel):
    """One evidence row with source traceability."""

    id: Optional[str] = Field(None, description="Evidence ID")
    record_id: Optional[str] = Field(None, description="Source record ID")
    equipment_code: Optional[str] = Field(
        None, description="Equipment the evidence came from"
    )
    relevance_basis: Optional[str] = Field(
        None, description="Why this record counts as evidence"
    )
    relevance_detail: Optional[str] = Field(
        None, description="Evidence path, e.g. same_model+same_failure_mode"
    )
    weight: Optional[float] = Field(None, description="Technical similarity weight")
    symptom_text: Optional[str] = Field(None, description="Recorded symptom excerpt")
    repair_description: Optional[str] = Field(None, description="Recorded repair excerpt")


class CauseItem(BaseModel):
    """A candidate cause with precomputed support values (never recomputed)."""

    id: str = Field(..., description="Cause ID")
    label: str = Field(..., description="Cause label")
    kinds: List[str] = Field(
        default_factory=list,
        description="explicitly_recorded | technical_mechanism | historically_inferred",
    )
    support_percent: Optional[float] = Field(
        None, description="Share of weighted scope evidence (not a probability)"
    )
    evidence_count: int = Field(..., description="Supporting record count")
    weighted_evidence: float = Field(..., description="Sum of supporting weights")
    denominator: float = Field(..., description="Sum of usable scope weights")
    calculation_method: str = Field(..., description="How support was calculated")
    similarity_score: Optional[float] = Field(
        None, description="Peak technical similarity among supporting evidence"
    )
    similarity_basis: Optional[str] = Field(
        None, description="Evidence path of the peak-similarity record"
    )
    confidence: Optional[float] = Field(None, description="Evidence-count confidence")
    probability: Optional[float] = Field(
        None, description="Normalized share of evidence weight across causes"
    )
    rank: int = Field(..., description="Evidence-strength rank within the guide")
    actions: List[CauseActionItem] = Field(default_factory=list)
    evidence: List[CauseEvidenceItem] = Field(default_factory=list)


class SectionItem(BaseModel):
    """One pre-rendered guide section."""

    section: Optional[str] = Field(
        None, description="symptom | cause | safety | method"
    )
    title: Optional[str] = Field(None, description="Section title")
    position: Optional[int] = Field(None, description="Display order")
    body: Optional[str] = Field(None, description="Pre-rendered section body")


class SafetyNoteItem(BaseModel):
    """A recorded safety note (never invented)."""

    note_text: Optional[str] = Field(None, description="Recorded safety note")
    source_record_ids: List[str] = Field(default_factory=list)
    cause_ids: List[str] = Field(default_factory=list)


class GuideItem(BaseModel):
    """Assembled troubleshooting guide for one equipment + failure mode."""

    equipment_code: str = Field(...)
    failure_mode_id: str = Field(...)
    failure_mode_label: str = Field(...)
    symptom_summary: str = Field(...)
    causes: List[CauseItem] = Field(
        default_factory=list, description="Ranked strongest-first"
    )
    sections: List[SectionItem] = Field(default_factory=list)
    safety_notes: List[SafetyNoteItem] = Field(default_factory=list)
    warnings: List[str] = Field(
        default_factory=list,
        description="e.g. insufficient_historical_repair_evidence",
    )


@router.get("/troubleshooting/status", response_model=TroubleshootingStatus)
def troubleshooting_status():
    """Health of the Troubleshooting Database (always 200, never raises)."""
    return TroubleshootingStatus(**troubleshooting.get_status())


@router.get("/troubleshooting/equipment", response_model=List[EquipmentItem])
def list_troubleshooting_equipment():
    """List equipment known to the Troubleshooting Database."""
    try:
        return [EquipmentItem(**item) for item in troubleshooting.list_equipment()]
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error listing troubleshooting equipment: {e}")
        raise HTTPException(
            status_code=500, detail="Error listing troubleshooting equipment"
        )


@router.get(
    "/troubleshooting/equipment/{equipment_code}", response_model=EquipmentItem
)
def get_troubleshooting_equipment(equipment_code: str):
    """One equipment by code (404 for unknown equipment)."""
    try:
        return EquipmentItem(**troubleshooting.get_equipment(equipment_code))
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error reading troubleshooting equipment: {e}")
        raise HTTPException(
            status_code=500, detail="Error reading troubleshooting equipment"
        )


@router.get(
    "/troubleshooting/equipment/{equipment_code}/failure-modes",
    response_model=List[FailureModeItem],
)
def list_troubleshooting_failure_modes(equipment_code: str):
    """Failure modes attested for one equipment."""
    try:
        return [
            FailureModeItem(**item)
            for item in troubleshooting.list_failure_modes(equipment_code)
        ]
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error listing troubleshooting failure modes: {e}")
        raise HTTPException(
            status_code=500, detail="Error listing troubleshooting failure modes"
        )


@router.get(
    "/troubleshooting/equipment/{equipment_code}/failure-modes/{failure_mode_id}",
    response_model=GuideItem,
)
def get_troubleshooting_guide(equipment_code: str, failure_mode_id: str):
    """Assembled troubleshooting guide (precomputed sections + tables)."""
    try:
        return GuideItem(**troubleshooting.get_guide(equipment_code, failure_mode_id))
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error reading troubleshooting guide: {e}")
        raise HTTPException(
            status_code=500, detail="Error reading troubleshooting guide"
        )


@router.get(
    "/troubleshooting/equipment/{equipment_code}/failure-modes/{failure_mode_id}/causes",
    response_model=List[CauseItem],
)
def list_troubleshooting_causes(equipment_code: str, failure_mode_id: str):
    """Ranked candidate causes with precomputed support values."""
    try:
        return [
            CauseItem(**item)
            for item in troubleshooting.list_causes(equipment_code, failure_mode_id)
        ]
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error listing troubleshooting causes: {e}")
        raise HTTPException(
            status_code=500, detail="Error listing troubleshooting causes"
        )


@router.get(
    "/troubleshooting/equipment/{equipment_code}/failure-modes/{failure_mode_id}/evidence",
    response_model=List[CauseEvidenceItem],
)
def list_troubleshooting_evidence(equipment_code: str, failure_mode_id: str):
    """Scope evidence rows with source record excerpts."""
    try:
        return [
            CauseEvidenceItem(**item)
            for item in troubleshooting.list_evidence(equipment_code, failure_mode_id)
        ]
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error listing troubleshooting evidence: {e}")
        raise HTTPException(
            status_code=500, detail="Error listing troubleshooting evidence"
        )
