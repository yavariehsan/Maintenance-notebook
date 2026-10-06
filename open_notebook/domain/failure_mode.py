from typing import ClassVar, Optional

from pydantic import field_validator

from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import InvalidInputError


class FailureMode(ObjectModel):
    """First-class equipment failure-mode record (Database B).

    Stored in the dedicated ``failure_mode`` table (migration 32),
    completely separate from the equipment-information ``asset`` table:
    every query in the failure-mode write/read path targets
    ``failure_mode`` only, so an import or manual record can never
    silently populate the equipment database (and vice versa).
    ``code`` is the equipment code linking the mode to its equipment
    by convention (same case-insensitive matching as asset codes);
    ``label`` is the mode name. The pair (code, label) is unique.
    """

    table_name: ClassVar[str] = "failure_mode"
    code: str
    label: str
    description: Optional[str] = ""
    status: Optional[str] = "active"

    @field_validator("code")
    @classmethod
    def code_must_not_be_blank(cls, v):
        if v is None or not str(v).strip():
            raise InvalidInputError("Failure mode code cannot be empty")
        return v

    @field_validator("label")
    @classmethod
    def label_must_not_be_blank(cls, v):
        if v is None or not str(v).strip():
            raise InvalidInputError("Failure mode label cannot be empty")
        return v

    @field_validator("status")
    @classmethod
    def status_must_not_be_blank(cls, v):
        if v is not None and not str(v).strip():
            raise InvalidInputError("Failure mode status cannot be blank")
        return v
