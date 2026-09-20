from typing import ClassVar, Optional

from pydantic import field_validator

from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import InvalidInputError


class Asset(ObjectModel):
    """First-class Maintenance Agent equipment record.

    Note: ``open_notebook.domain.notebook.Asset`` is an unrelated embedded
    file/url value object on Source; this class is the table-backed
    ``asset`` entity (migration 26). The name is kept because Asset is the
    canonical product concept.
    """

    table_name: ClassVar[str] = "asset"
    name: str
    description: Optional[str] = ""
    asset_type: Optional[str] = None
    status: Optional[str] = "active"
    location: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v.strip():
            raise InvalidInputError("Asset name cannot be empty")
        return v

    @field_validator("status")
    @classmethod
    def status_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise InvalidInputError("Asset status cannot be blank")
        return v
