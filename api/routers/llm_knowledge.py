"""LLM troubleshooting-knowledge API (M12).

Thin routes over ``api/llm_knowledge_service.py``:

- create / list / inspect LLM Knowledge Builds from uploaded repair
  reports (stable record IDs, never filenames);
- list validated LLM knowledge records per build (optionally scoped to
  one source report);
- query the LLM Troubleshooting Guide for one build + one source
  report, with provenance and DATA_SUPPORTED vs LLM_INFERRED
  distinction on every item.

The deterministic text-mining endpoints (``/api/troubleshooting/*``
over the SQLite database) are untouched — the Guide UI selects which
store supplies the guide, never both.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from api import llm_knowledge_service as llm_knowledge
from open_notebook.exceptions import (
    ConfigurationError,
    InvalidInputError,
    NotFoundError,
)

router = APIRouter()


class LLMBuildManifestEntry(BaseModel):
    report_id: str
    filename: Optional[str] = None
    analysis_key: Optional[str] = None


class LLMBuildItem(BaseModel):
    """One LLM Knowledge Build over a report snapshot."""

    id: str
    source_report_ids: List[str] = Field(
        default_factory=list, description="Exact report set this build covers"
    )
    manifest: List[LLMBuildManifestEntry] = Field(default_factory=list)
    status: str = Field(
        ..., description="queued | running | completed | partial | failed | cancelled"
    )
    command_id: Optional[str] = Field(None, description="Worker job id")
    model: Optional[str] = Field(None, description="Language model ID used")
    prompt_version: Optional[str] = Field(None, description="Prompt contract version")
    error: Optional[str] = Field(None, description="Failure reason, if any")
    warnings: List[str] = Field(default_factory=list)
    record_count: Optional[int] = None
    failed_record_count: Optional[int] = None
    created: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class CreateLLMBuildRequest(BaseModel):
    report_ids: List[str] = Field(
        ..., description="Stable repair-report IDs to generate from"
    )
    model_id: Optional[str] = Field(
        None, description="Explicit language model ID (optional)"
    )


class StartLLMBuildResponse(BaseModel):
    build: LLMBuildItem
    message: str = Field(..., description="Human-readable acknowledgement")


class LLMItemResponse(BaseModel):
    text: Optional[str] = None
    basis: Optional[str] = Field(
        None, description="DATA_SUPPORTED | LLM_INFERRED"
    )
    source_quote: Optional[str] = None


class LLMRecordItem(BaseModel):
    """One validated extraction with full source traceability."""

    id: Optional[str] = None
    build_id: Optional[str] = None
    source_report_id: Optional[str] = None
    source_record_id: Optional[str] = None
    source_text: Optional[str] = Field(
        None, description="Verbatim source row text (never rewritten)"
    )
    symptom: Optional[str] = None
    findings: List[LLMItemResponse] = Field(default_factory=list)
    candidate_causes: List[LLMItemResponse] = Field(default_factory=list)
    diagnostic_steps: List[LLMItemResponse] = Field(default_factory=list)
    corrective_actions: List[LLMItemResponse] = Field(default_factory=list)
    verification_steps: List[LLMItemResponse] = Field(default_factory=list)
    post_repair_events: List[LLMItemResponse] = Field(default_factory=list)
    record_error: Optional[str] = Field(
        None, description="Traceable per-record failure, when invalid"
    )
    created: Optional[str] = None


class LLMGuideResponse(BaseModel):
    """LLM Troubleshooting Guide for one build + one source report."""

    knowledge_source: str = Field(..., description="Always 'LLM'")
    build_id: str
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    source_report_id: str
    source_filename: Optional[str] = None
    source_deleted: bool = Field(
        False, description="Backing report deleted; identity preserved, no remap"
    )
    records: List[LLMRecordItem] = Field(default_factory=list)
    warnings: List[str] = Field(
        default_factory=list, description="e.g. no_records_for_source"
    )


@router.post("/repair-reports/llm-builds", response_model=StartLLMBuildResponse)
async def create_llm_build(payload: CreateLLMBuildRequest):
    """Start an LLM Knowledge Build over selected repair reports.

    201 with the new build; 409 (with the live build ID) while an
    equivalent build over the same report set is active; 404 for
    unknown reports; 400 for an empty selection; 422 when no language
    model is configured. Mining knowledge, reports, and embeddings are
    never touched.
    """
    try:
        build = await llm_knowledge.start_build(payload.report_ids, payload.model_id)
    except llm_knowledge.BuildInProgressError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "build_id": e.build_id,
            },
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ConfigurationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting LLM knowledge build: {e}")
        raise HTTPException(
            status_code=500, detail="Error starting LLM knowledge build"
        )
    return StartLLMBuildResponse(
        build=LLMBuildItem(**build),
        message="LLM knowledge build started. The LLM guide updates when it completes.",
    )


@router.get("/repair-reports/llm-builds", response_model=List[LLMBuildItem])
async def list_llm_builds(limit: int = Query(20, ge=1, le=100)):
    """List LLM Knowledge Builds (newest first; all builds coexist)."""
    try:
        builds = await llm_knowledge.list_builds(limit=limit)
        return [LLMBuildItem(**build) for build in builds]
    except Exception as e:
        logger.error(f"Error listing LLM knowledge builds: {e}")
        raise HTTPException(
            status_code=500, detail="Error listing LLM knowledge builds"
        )


@router.get("/repair-reports/llm-builds/{build_id}", response_model=LLMBuildItem)
async def get_llm_build(build_id: str):
    """One LLM Knowledge Build with lifecycle status and counts."""
    try:
        return LLMBuildItem(**await llm_knowledge.get_build(build_id))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error reading LLM knowledge build: {e}")
        raise HTTPException(
            status_code=500, detail="Error reading LLM knowledge build"
        )


@router.get(
    "/repair-reports/llm-builds/{build_id}/records",
    response_model=List[LLMRecordItem],
)
async def list_llm_records(
    build_id: str, source_report_id: Optional[str] = Query(None)
):
    """Validated LLM records of a build, optionally scoped to one report.

    Scoping is by stable report ID — never mixed across sources.
    """
    try:
        await llm_knowledge.get_build(build_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        records = await llm_knowledge.list_records(build_id, source_report_id)
        return [LLMRecordItem(**record) for record in records]
    except Exception as e:
        logger.error(f"Error listing LLM knowledge records: {e}")
        raise HTTPException(
            status_code=500, detail="Error listing LLM knowledge records"
        )


@router.get("/troubleshooting/llm/guide", response_model=LLMGuideResponse)
async def get_llm_guide(
    build_id: str = Query(...),
    source_report_id: str = Query(...),
):
    """LLM Troubleshooting Guide for one build + one source report.

    Only knowledge belonging to the selected source is returned (never
    silently mixed); a source with no records yields an explicit empty
    state, and a deleted backing source keeps its identity with
    ``source_deleted`` instead of remapping.
    """
    try:
        guide = await llm_knowledge.assemble_llm_guide(build_id, source_report_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error reading LLM guide: {e}")
        raise HTTPException(status_code=500, detail="Error reading LLM guide")
    return LLMGuideResponse(**guide)
