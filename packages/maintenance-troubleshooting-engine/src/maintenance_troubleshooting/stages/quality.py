"""Stage 3 — DataQualityAnalyzer: validation, duplicates, valid subset."""

from __future__ import annotations

from maintenance_troubleshooting.quality import (
    DuplicateDetector,
    IssueSeverity,
    RecordValidator,
)
from maintenance_troubleshooting.stages.base import PipelineContext


class DataQualityAnalyzer:
    """Assemble the quality report and the minable (valid) record subset."""

    name = "data-quality"

    def run(self, context: PipelineContext) -> PipelineContext:
        """Validate all records; only error-free rows feed mining stages."""
        validator = RecordValidator(
            min_repair_length=context.config.text_mining.min_repair_length
        )
        report = validator.validate_all(context.records)
        report.duplicates.extend(
            DuplicateDetector().find_duplicates(context.records)
        )
        if report.duplicates:
            context.warnings.append(
                f"{len(report.duplicates)} duplicate record-ID groups found"
            )
        error_ids = {
            issue.record_id
            for issue in report.issues
            if issue.severity is IssueSeverity.ERROR
        }
        context.quality_report = report
        context.valid_records = [
            record for record in context.records if record.record_id not in error_ids
        ]
        return context
