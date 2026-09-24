"""Stage 1 — RecordParser: workbook → canonical records (InputAdapter)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from maintenance_troubleshooting.inputs import ExcelMaintenanceReader
from maintenance_troubleshooting.inputs.record_ids import PrefixNumberRecordId
from maintenance_troubleshooting.stages.base import PipelineContext


class RecordParser:
    """Parse and validate the workbook; build canonical records."""

    name = "record-parser"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Read the workbook; never silently discard rows."""
        path = Path(context.input_path)
        context.input_hash = _sha256(path)
        reader = ExcelMaintenanceReader(
            record_id_strategy=PrefixNumberRecordId(),
            sheet_name=context.config.input.sheet_name,
            header_row=context.config.input.header_row,
        )
        result = reader.read(path, context.column_mapping)
        context.records = result.records
        context.input_report = result.report
        for problem in result.report.row_problems:
            context.warnings.append(f"row {problem.row_number}: {problem.reason}")
        return context


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
