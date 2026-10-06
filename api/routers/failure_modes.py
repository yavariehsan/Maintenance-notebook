from typing import List

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from loguru import logger

from api.failure_mode_service import (
    fetch_existing_mode_keys,
    import_failure_mode_rows,
    normalize_failure_mode_code,
    parse_failure_mode_workbook,
    reject_existing_modes,
)
from api.models import (
    FailureModeCreate,
    FailureModeDeleteResponse,
    FailureModeImportIssueModel,
    FailureModeImportResponse,
    FailureModeImportRowModel,
    FailureModeResponse,
    FailureModeUpdate,
)
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.failure_mode import FailureMode
from open_notebook.exceptions import (
    InvalidInputError,
    NotFoundError,
    OpenNotebookError,
)

router = APIRouter()

_FAILURE_MODE_FIELDS = (
    "id, code, label, description, status, created, updated"
)


def _to_response(row: dict) -> FailureModeResponse:
    return FailureModeResponse(
        id=str(row.get("id", "")),
        code=row.get("code", ""),
        label=row.get("label", ""),
        description=row.get("description", ""),
        status=row.get("status", "active"),
        created=str(row.get("created")),
        updated=str(row.get("updated")),
    )


def _from_create(mode: FailureMode) -> FailureModeResponse:
    return FailureModeResponse(
        id=str(mode.id),
        code=mode.code,
        label=mode.label,
        description=mode.description or "",
        status=mode.status or "active",
        created=str(mode.created),
        updated=str(mode.updated),
    )


async def _ensure_pair_unique(
    code: str | None, label: str | None, exclude_id: str | None = None
) -> tuple[str | None, str | None]:
    """Normalize a (code, label) pair and reject duplicates.

    Returns the trimmed pair (None entries stay None when not supplied).
    Existing records are never silently duplicated: a matching pair raises
    InvalidInputError (-> 400) naming the conflict.
    """
    normalized_code = normalize_failure_mode_code(code) if code is not None else None
    normalized_label = label.strip() if label is not None else None
    if not normalized_code and not normalized_label:
        return None, None
    if normalized_code and normalized_label:
        rows = await repo_query(
            "SELECT id FROM failure_mode "
            "WHERE string::uppercase(code OR '') == $code "
            "AND string::uppercase(label OR '') == $label LIMIT 1",
            {"code": normalized_code.upper(), "label": normalized_label.upper()},
        )
        if rows and (
            exclude_id is None or str(rows[0].get("id")) != exclude_id
        ):
            raise InvalidInputError(
                f"Failure mode '{normalized_label}' for equipment code "
                f"'{normalized_code}' already exists. "
                "Edit the existing record instead."
            )
    return normalized_code or None, normalized_label or None


@router.get("/failure-modes", response_model=List[FailureModeResponse])
async def get_failure_modes(
    order_by: str = Query("updated desc", description="Order by field and direction"),
):
    """Get all failure-mode records with optional ordering."""
    try:
        # Validate order_by against allowlist to prevent SurrealQL injection
        allowed_fields = {"code", "label", "status", "created", "updated"}
        allowed_directions = {"asc", "desc"}

        parts = order_by.strip().lower().split()
        if len(parts) == 1:
            if parts[0] not in allowed_fields:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid order_by field: '{order_by}'. Allowed fields: {', '.join(sorted(allowed_fields))}",
                )
            validated_order_by = parts[0]
        elif len(parts) == 2:
            if parts[0] not in allowed_fields or parts[1] not in allowed_directions:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid order_by: '{order_by}'. Allowed fields: {', '.join(sorted(allowed_fields))}. Allowed directions: asc, desc",
                )
            validated_order_by = f"{parts[0]} {parts[1]}"
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid order_by format: '{order_by}'. Expected 'field' or 'field direction'",
            )

        result = await repo_query(
            f"SELECT {_FAILURE_MODE_FIELDS} FROM failure_mode ORDER BY {validated_order_by}"
        )
        return [_to_response(row) for row in result]
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error fetching failure modes: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching failure modes: {str(e)}"
        )


@router.post("/failure-modes", response_model=FailureModeResponse)
async def create_failure_mode(mode: FailureModeCreate):
    """Create a new failure-mode record."""
    try:
        code, label = await _ensure_pair_unique(mode.code, mode.label)
        new_mode = FailureMode(
            code=code or "",
            label=label or "",
            description=mode.description,
            status=mode.status,
        )
        await new_mode.save()

        return _from_create(new_mode)
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error creating failure mode: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating failure mode: {str(e)}"
        )


@router.post("/failure-modes/import", response_model=FailureModeImportResponse)
async def import_failure_modes(
    file: UploadFile = File(..., description="Failure-mode .xlsx file"),
    dry_run: bool = Query(
        True,
        description="True: validate and preview only. False: persist valid rows.",
    ),
):
    """Bulk import failure modes from an Excel workbook (two-step workflow).

    Step 1 (dry_run=true): parse + validate, return preview with per-row
    issues. Step 2 (dry_run=false, same file re-uploaded): re-validate
    against current database state, persist valid rows, report imported and
    skipped rows. Duplicate (code, label) pairs are rejected, never
    overwritten. Writes go to the ``failure_mode`` table only.
    """
    try:
        filename = (file.filename or "").lower()
        if not filename.endswith((".xlsx", ".xlsm")):
            raise HTTPException(
                status_code=400,
                detail="Please upload an Excel (.xlsx) file.",
            )
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        try:
            result = parse_failure_mode_workbook(content)
        except InvalidInputError as e:
            raise HTTPException(status_code=400, detail=str(e))

        existing_keys = await fetch_existing_mode_keys()
        reject_existing_modes(result, existing_keys)

        imported_count = 0
        write_issues: list = []
        if not dry_run:
            imported_count, write_issues = await import_failure_mode_rows(
                result.valid_rows
            )
            result.issues.extend(write_issues)

        return FailureModeImportResponse(
            total_rows=result.total_rows,
            valid_rows=[
                FailureModeImportRowModel(
                    row_number=row.row_number,
                    code=row.values.get("code") or "",
                    label=row.values.get("label") or "",
                )
                for row in result.valid_rows
            ],
            issues=[
                FailureModeImportIssueModel(
                    row_number=issue.row_number,
                    code=issue.code,
                    message=issue.message,
                )
                for issue in result.issues
            ],
            imported_count=imported_count,
        )
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error importing failure modes: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error importing failure modes: {str(e)}"
        )


@router.get("/failure-modes/{mode_id}", response_model=FailureModeResponse)
async def get_failure_mode(mode_id: str):
    """Get a single failure-mode record by id."""
    try:
        mode = await FailureMode.get(mode_id)
        return _from_create(mode)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Failure mode not found")
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error fetching failure mode {mode_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching failure mode: {str(e)}"
        )


@router.put("/failure-modes/{mode_id}", response_model=FailureModeResponse)
async def update_failure_mode(mode_id: str, mode_update: FailureModeUpdate):
    """Update a failure-mode record (only provided fields)."""
    try:
        mode = await FailureMode.get(mode_id)

        # Uniqueness is enforced on the effective (code, label) pair, so
        # resolve it once before assigning individual fields.
        if mode_update.code is not None or mode_update.label is not None:
            raw_code: str | None = (
                mode_update.code if mode_update.code is not None else mode.code
            )
            raw_label: str | None = (
                mode_update.label if mode_update.label is not None else mode.label
            )
            new_code, new_label = await _ensure_pair_unique(
                raw_code, raw_label, exclude_id=mode.id
            )
            if new_code is None or new_label is None:
                raise InvalidInputError(
                    "Failure mode code and label cannot be blank"
                )
            mode.code, mode.label = new_code, new_label

        # Update only provided fields
        for field in ("description", "status"):
            value = getattr(mode_update, field)
            if value is not None:
                setattr(mode, field, value)

        await mode.save()

        result = await repo_query(
            f"SELECT {_FAILURE_MODE_FIELDS} FROM $mode_id",
            {"mode_id": ensure_record_id(mode_id)},
        )
        if result:
            return _to_response(result[0])

        # Fallback if query fails
        return _from_create(mode)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Failure mode not found")
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error updating failure mode {mode_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error updating failure mode: {str(e)}"
        )


@router.delete("/failure-modes/{mode_id}", response_model=FailureModeDeleteResponse)
async def delete_failure_mode(mode_id: str):
    """Delete a failure-mode record."""
    try:
        mode = await FailureMode.get(mode_id)
        await mode.delete()
        return FailureModeDeleteResponse(message="Failure mode deleted successfully")
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Failure mode not found")
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error deleting failure mode {mode_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error deleting failure mode: {str(e)}"
        )
