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
    # Equipment knowledge workflow (migration 27). `code` is the first-class
    # equipment identifier shared by manual registration and Excel import
    # (e.g. BR1); matching is case-insensitive on the trimmed value, enforced
    # in api/asset_service.py with a UNIQUE index backstop. Field mapping for
    # reused fields: name = Main Description, location = Main Function
    # Location, asset_type = Type Description, manufacturer = Manufacture.
    code: Optional[str] = None
    factory: Optional[str] = None
    zone_description: Optional[str] = None
    site_description: Optional[str] = None
    plant_description: Optional[str] = None
    main_class: Optional[str] = None
    sub_class: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v.strip():
            raise InvalidInputError("Asset name cannot be empty")
        return v

    @field_validator("code")
    @classmethod
    def code_must_not_be_blank(cls, v):
        # None = legacy pre-27 record without a code; a provided code must
        # carry a real identifier after trimming.
        if v is not None and not v.strip():
            raise InvalidInputError("Asset code cannot be blank")
        return v

    @field_validator("status")
    @classmethod
    def status_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise InvalidInputError("Asset status cannot be blank")
        return v
