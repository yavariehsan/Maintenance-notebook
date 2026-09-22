from typing import List

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from loguru import logger

from api.asset_service import (
    fetch_existing_code_keys,
    import_equipment_rows,
    normalize_equipment_code,
    parse_equipment_workbook,
    reject_existing_codes,
)
from api.models import (
    AssetCreate,
    AssetDeleteResponse,
    AssetResponse,
    AssetUpdate,
    EquipmentImportIssueModel,
    EquipmentImportResponse,
    EquipmentImportRowModel,
)
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.asset import Asset
from open_notebook.exceptions import (
    InvalidInputError,
    NotFoundError,
    OpenNotebookError,
)

router = APIRouter()

_ASSET_FIELDS = (
    "id, name, description, asset_type, status, location, "
    "manufacturer, model, serial_number, code, factory, zone_description, "
    "site_description, plant_description, main_class, sub_class, "
    "created, updated"
)

_EQUIPMENT_UPDATE_FIELDS = (
    "name",
    "description",
    "asset_type",
    "status",
    "location",
    "manufacturer",
    "model",
    "serial_number",
    "code",
    "factory",
    "zone_description",
    "site_description",
    "plant_description",
    "main_class",
    "sub_class",
)


def _to_response(row: dict) -> AssetResponse:
    return AssetResponse(
        id=str(row.get("id", "")),
        name=row.get("name", ""),
        description=row.get("description", ""),
        asset_type=row.get("asset_type"),
        status=row.get("status", "active"),
        location=row.get("location"),
        manufacturer=row.get("manufacturer"),
        model=row.get("model"),
        serial_number=row.get("serial_number"),
        code=row.get("code"),
        factory=row.get("factory"),
        zone_description=row.get("zone_description"),
        site_description=row.get("site_description"),
        plant_description=row.get("plant_description"),
        main_class=row.get("main_class"),
        sub_class=row.get("sub_class"),
        created=str(row.get("created", "")),
        updated=str(row.get("updated", "")),
    )


def _from_create(asset: Asset) -> AssetResponse:
    return AssetResponse(
        id=asset.id or "",
        name=asset.name,
        description=asset.description or "",
        asset_type=asset.asset_type,
        status=asset.status or "active",
        location=asset.location,
        manufacturer=asset.manufacturer,
        model=asset.model,
        serial_number=asset.serial_number,
        code=asset.code,
        factory=asset.factory,
        zone_description=asset.zone_description,
        site_description=asset.site_description,
        plant_description=asset.plant_description,
        main_class=asset.main_class,
        sub_class=asset.sub_class,
        created=str(asset.created),
        updated=str(asset.updated),
    )


async def _ensure_code_unique(code: str | None, exclude_id: str | None = None) -> str | None:
    """Normalize a supplied equipment code and reject duplicates.

    Returns the trimmed code (or None when not supplied). Existing records
    are never silently duplicated: a matching code raises InvalidInputError
    (-> 400) naming the conflict.
    """
    normalized = normalize_equipment_code(code)
    if not normalized:
        return None
    rows = await repo_query(
        "SELECT id FROM asset WHERE string::uppercase(code OR '') == $code LIMIT 1",
        {"code": normalized.upper()},
    )
    if rows and (exclude_id is None or str(rows[0].get("id")) != exclude_id):
        raise InvalidInputError(
            f"Equipment code '{normalized}' already exists. "
            "Codes must be unique; edit the existing record instead."
        )
    return normalized


@router.get("/assets", response_model=List[AssetResponse])
async def get_assets(
    order_by: str = Query("updated desc", description="Order by field and direction"),
):
    """Get all assets with optional ordering."""
    try:
        # Validate order_by against allowlist to prevent SurrealQL injection
        allowed_fields = {"name", "status", "created", "updated"}
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
            f"SELECT {_ASSET_FIELDS} FROM asset ORDER BY {validated_order_by}"
        )
        return [_to_response(row) for row in result]
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error fetching assets: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching assets: {str(e)}"
        )


@router.post("/assets", response_model=AssetResponse)
async def create_asset(asset: AssetCreate):
    """Create a new asset."""
    try:
        code = await _ensure_code_unique(asset.code)
        new_asset = Asset(
            name=asset.name,
            description=asset.description,
            asset_type=asset.asset_type,
            status=asset.status,
            location=asset.location,
            manufacturer=asset.manufacturer,
            model=asset.model,
            serial_number=asset.serial_number,
            code=code,
            factory=asset.factory,
            zone_description=asset.zone_description,
            site_description=asset.site_description,
            plant_description=asset.plant_description,
            main_class=asset.main_class,
            sub_class=asset.sub_class,
        )
        await new_asset.save()

        return _from_create(new_asset)
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error creating asset: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating asset: {str(e)}"
        )


@router.post("/assets/import", response_model=EquipmentImportResponse)
async def import_assets(
    file: UploadFile = File(..., description="Equipment .xlsx file"),
    dry_run: bool = Query(
        True,
        description="True: validate and preview only. False: persist valid rows.",
    ),
):
    """Bulk import equipment from an Excel workbook (two-step workflow).

    Step 1 (dry_run=true): parse + validate, return preview with per-row
    issues. Step 2 (dry_run=false, same file re-uploaded): re-validate
    against current database state, persist valid rows, report imported and
    skipped rows. Duplicate codes are rejected, never overwritten.
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
            result = parse_equipment_workbook(content)
        except InvalidInputError as e:
            raise HTTPException(status_code=400, detail=str(e))

        existing_keys = await fetch_existing_code_keys()
        reject_existing_codes(result, existing_keys)

        imported_count = 0
        write_issues: list = []
        if not dry_run:
            imported_count, write_issues = await import_equipment_rows(
                result.valid_rows
            )
            result.issues.extend(write_issues)

        return EquipmentImportResponse(
            total_rows=result.total_rows,
            valid_rows=[
                EquipmentImportRowModel(
                    row_number=row.row_number,
                    code=row.values.get("code") or "",
                    name=row.values.get("name") or "",
                )
                for row in result.valid_rows
            ],
            issues=[
                EquipmentImportIssueModel(
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
        logger.error(f"Error importing assets: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error importing assets: {str(e)}"
        )


@router.get("/assets/by-code/{code}", response_model=AssetResponse)
async def get_asset_by_code(code: str):
    """Get a single equipment record by its code (case-insensitive)."""
    try:
        normalized = normalize_equipment_code(code)
        if not normalized:
            raise HTTPException(status_code=400, detail="Equipment code is required")
        rows = await repo_query(
            f"SELECT {_ASSET_FIELDS} FROM asset "
            "WHERE string::uppercase(code OR '') == $code LIMIT 1",
            {"code": normalized.upper()},
        )
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"Equipment with code '{normalized}' was not found",
            )
        return _to_response(rows[0])
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error fetching asset by code {code}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching asset: {str(e)}"
        )


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(asset_id: str):
    """Get a single asset by id."""
    try:
        asset = await Asset.get(asset_id)
        return _from_create(asset)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Asset not found")
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error fetching asset {asset_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching asset: {str(e)}"
        )


@router.put("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(asset_id: str, asset_update: AssetUpdate):
    """Update an asset (only provided fields)."""
    try:
        asset = await Asset.get(asset_id)

        # Update only provided fields
        for field in _EQUIPMENT_UPDATE_FIELDS:
            value = getattr(asset_update, field)
            if value is not None:
                if field == "code":
                    value = await _ensure_code_unique(value, exclude_id=asset.id)
                    if value is None:
                        continue
                setattr(asset, field, value)

        await asset.save()

        result = await repo_query(
            f"SELECT {_ASSET_FIELDS} FROM $asset_id",
            {"asset_id": ensure_record_id(asset_id)},
        )
        if result:
            return _to_response(result[0])

        # Fallback if query fails
        return _from_create(asset)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Asset not found")
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error updating asset {asset_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error updating asset: {str(e)}"
        )


@router.delete("/assets/{asset_id}", response_model=AssetDeleteResponse)
async def delete_asset(asset_id: str):
    """Delete an asset. Assets have no dependents yet, so plain delete is safe."""
    try:
        asset = await Asset.get(asset_id)
        await asset.delete()
        return AssetDeleteResponse(message="Asset deleted successfully")
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Asset not found")
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error deleting asset {asset_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error deleting asset: {str(e)}"
        )
