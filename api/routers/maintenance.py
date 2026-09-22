from typing import List

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from api.maintenance_service import ask_equipment, list_equipment_sources
from api.models import (
    MaintenanceAskRequest,
    MaintenanceAskResponse,
    MaintenanceSourceRef,
)
from open_notebook.exceptions import (
    InvalidInputError,
    NotFoundError,
    OpenNotebookError,
)

router = APIRouter()


@router.get("/maintenance/sources", response_model=List[MaintenanceSourceRef])
async def get_maintenance_sources(
    equipment_code: str = Query(..., description="Equipment code to list CMMS sources for"),
):
    """List CMMS sources associated with an equipment code."""
    try:
        refs = await list_equipment_sources(equipment_code)
        return [MaintenanceSourceRef(**ref) for ref in refs]
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error listing maintenance sources: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Error listing maintenance sources"
        )


@router.post("/maintenance/ask", response_model=MaintenanceAskResponse)
async def ask_maintenance(request: MaintenanceAskRequest):
    """Answer a question from one equipment's CMMS sources only.

    Retrieval is restricted at the database layer to sources carrying the
    requested equipment code. Returns status no_sources / no_context instead
    of an invented answer when the records cannot support one.
    """
    try:
        result = await ask_equipment(
            question=request.question,
            equipment_code=request.equipment_code,
            answer_model=request.answer_model,
            final_answer_model=request.final_answer_model,
            max_results=request.max_results,
        )
        return MaintenanceAskResponse(**result)
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error answering maintenance question: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Error answering maintenance question"
        )
