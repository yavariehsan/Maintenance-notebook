"""Data-quality layer: validation, duplicates, and reports."""

from maintenance_troubleshooting.quality.duplicates import DuplicateDetector
from maintenance_troubleshooting.quality.models import (
    DataQualityReport,
    DuplicateGroup,
    FailureModeConsistencyCheck,
    IssueSeverity,
    MissingFieldAnalysis,
    RecordIssue,
    TextQualityAssessment,
)
from maintenance_troubleshooting.quality.validation import RecordValidator

__all__ = [
    "DataQualityReport",
    "DuplicateDetector",
    "DuplicateGroup",
    "FailureModeConsistencyCheck",
    "IssueSeverity",
    "MissingFieldAnalysis",
    "RecordIssue",
    "RecordValidator",
    "TextQualityAssessment",
]
