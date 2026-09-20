from typing import List

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from api.models import (
    AssetCreate,
    AssetDeleteResponse,
    AssetResponse,
    AssetUpdate,
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
    "manufacturer, model, serial_number, created, updated"
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
        created=str(row.get("created", "")),
        updated=str(row.get("updated", "")),
    )


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
        new_asset = Asset(
            name=asset.name,
            description=asset.description,
            asset_type=asset.asset_type,
            status=asset.status,
            location=asset.location,
            manufacturer=asset.manufacturer,
            model=asset.model,
            serial_number=asset.serial_number,
        )
        await new_asset.save()

        return AssetResponse(
            id=new_asset.id or "",
            name=new_asset.name,
            description=new_asset.description or "",
            asset_type=new_asset.asset_type,
            status=new_asset.status or "active",
            location=new_asset.location,
            manufacturer=new_asset.manufacturer,
            model=new_asset.model,
            serial_number=new_asset.serial_number,
            created=str(new_asset.created),
            updated=str(new_asset.updated),
        )
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


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(asset_id: str):
    """Get a single asset by id."""
    try:
        asset = await Asset.get(asset_id)
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
            created=str(asset.created),
            updated=str(asset.updated),
        )
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
        for field in (
            "name",
            "description",
            "asset_type",
            "status",
            "location",
            "manufacturer",
            "model",
            "serial_number",
        ):
            value = getattr(asset_update, field)
            if value is not None:
                setattr(asset, field, value)

        await asset.save()

        result = await repo_query(
            f"SELECT {_ASSET_FIELDS} FROM $asset_id",
            {"asset_id": ensure_record_id(asset_id)},
        )
        if result:
            return _to_response(result[0])

        # Fallback if query fails
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
            created=str(asset.created),
            updated=str(asset.updated),
        )
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
