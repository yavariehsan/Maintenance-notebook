"""Excel input adapter: reader, column mapping, record IDs."""

from maintenance_troubleshooting.inputs.excel import (
    DATE_FIELDS,
    DEFAULT_COLUMN_ALIASES,
    DEFAULT_PLACEHOLDERS,
    REQUIRED_FIELDS,
    ColumnMapping,
    ExcelMaintenanceReader,
    InputReport,
    ReadResult,
    ResolvedMapping,
    RowProblem,
    SchemaReport,
    preserve_identifier,
)
from maintenance_troubleshooting.inputs.record_ids import (
    PrefixNumberRecordId,
    RecordIdStrategy,
)

__all__ = [
    "DEFAULT_COLUMN_ALIASES",
    "DEFAULT_PLACEHOLDERS",
    "DATE_FIELDS",
    "REQUIRED_FIELDS",
    "ColumnMapping",
    "ExcelMaintenanceReader",
    "InputReport",
    "PrefixNumberRecordId",
    "ReadResult",
    "RecordIdStrategy",
    "ResolvedMapping",
    "RowProblem",
    "SchemaReport",
    "preserve_identifier",
]
