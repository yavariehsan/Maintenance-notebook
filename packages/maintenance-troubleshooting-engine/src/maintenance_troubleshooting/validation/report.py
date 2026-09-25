"""Reusable validation reporting: machine-readable JSON + human Markdown.

A report combines a fresh in-memory analysis, the generated database
(read via the repository), the equipment split, and an optional held-out
evaluation. No reporting dependencies beyond the standard library.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maintenance_troubleshooting.pipeline import AnalysisResult
from maintenance_troubleshooting.runtime import TroubleshootingRepository
from maintenance_troubleshooting.validation.evaluate import EvaluationReport
from maintenance_troubleshooting.validation.split import EquipmentSplit, check_leakage
from maintenance_troubleshooting.version import __version__ as ENGINE_VERSION

#: Cause labels treated as generic/placeholder-ish for the suspicious-cases
#: section (reported, never deleted from the knowledge base).
GENERIC_CAUSE_MARKERS = (
    "ایرادی وجود نداشت",
    "مشخص نشد",
    "مشاهده نشد",
    "unknown",
    "نامشخص",
)


@dataclass
class ValidationReport:
    """Everything a reviewer needs to judge one validation run."""

    engine_version: str = ENGINE_VERSION
    workbook: str = ""
    database: str = ""
    dataset: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    equipment: list[dict[str, Any]] = field(default_factory=list)
    failure_modes: list[dict[str, Any]] = field(default_factory=list)
    causes: list[dict[str, Any]] = field(default_factory=list)
    repair_actions: list[dict[str, Any]] = field(default_factory=list)
    guides: list[dict[str, Any]] = field(default_factory=list)
    split: dict[str, Any] = field(default_factory=dict)
    leakage: list[str] = field(default_factory=list)
    evaluation: dict[str, Any] = field(default_factory=dict)
    suspicious: dict[str, Any] = field(default_factory=dict)
    support_audit: dict[str, Any] = field(default_factory=dict)
    determinism: dict[str, Any] = field(default_factory=dict)
    timing_seconds: float = 0.0
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable view."""
        return {
            "engine_version": self.engine_version,
            "workbook": self.workbook,
            "database": self.database,
            "dataset": self.dataset,
            "quality": self.quality,
            "equipment": self.equipment,
            "failure_modes": self.failure_modes,
            "causes": self.causes,
            "repair_actions": self.repair_actions,
            "guides": self.guides,
            "split": self.split,
            "leakage": self.leakage,
            "evaluation": self.evaluation,
            "suspicious": self.suspicious,
            "support_audit": self.support_audit,
            "determinism": self.determinism,
            "timing_seconds": self.timing_seconds,
            "limitations": self.limitations,
        }

    def to_json(self) -> str:
        """Serialize (Persian preserved, not ASCII-escaped)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)

    def to_markdown(self) -> str:
        """Human-inspectable summary of the validation run."""
        lines = [
            "# Troubleshooting validation report",
            "",
            f"- engine: {self.engine_version}",
            f"- workbook: {self.workbook}",
            f"- database: {self.database}",
            f"- timing: {self.timing_seconds:.1f}s",
            "",
            "## Dataset",
            "",
        ]
        for key, value in self.dataset.items():
            lines.append(f"- {key}: {value}")
        lines += ["", "## Quality", ""]
        for key, value in self.quality.items():
            lines.append(f"- {key}: {value}")
        lines += ["", "## Split & leakage", ""]
        lines.append(f"- split: {self.split}")
        lines.append(f"- leakage (must be empty): {self.leakage or 'none'}")
        if self.evaluation:
            lines += ["", "## Held-out evaluation (proxy labels, not ground truth)", ""]
            for key, value in self.evaluation.items():
                if key != "examples":
                    lines.append(f"- {key}: {value}")
        lines += ["", "## Suspicious / ambiguous cases", ""]
        for key, value in self.suspicious.items():
            lines.append(f"- {key}: {value}")
        lines += ["", "## Support self-audit", ""]
        for key, value in self.support_audit.items():
            lines.append(f"- {key}: {value}")
        lines += ["", "## Determinism", ""]
        for key, value in self.determinism.items():
            lines.append(f"- {key}: {value}")
        lines += ["", "## Limitations", ""]
        for limitation in self.limitations:
            lines.append(f"- {limitation}")
        lines.append("")
        return "\n".join(lines)

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        """Write ``validation-report.json`` + ``validation-report.md``."""
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        json_path = target / "validation-report.json"
        md_path = target / "validation-report.md"
        json_path.write_text(self.to_json(), encoding="utf-8")
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": md_path}


def build_report(
    result: AnalysisResult,
    database_path: str | Path,
    split: EquipmentSplit | None = None,
    evaluation: EvaluationReport | None = None,
    timing_seconds: float = 0.0,
    max_cause_rows: int = 50,
) -> ValidationReport:
    """Assemble a validation report from analysis + database + split."""
    report = ValidationReport(
        workbook=result.input_report.path if result.input_report else "",
        database=str(database_path),
        timing_seconds=timing_seconds,
    )
    quality = result.quality_report
    report.dataset = {
        "total_records": quality.total_records,
        "valid_records": quality.valid_records,
        "problematic_records": quality.total_records - quality.valid_records,
        "fallback_record_ids": (
            result.input_report.fallback_ids if result.input_report else 0
        ),
        "unique_equipment": len(result.equipment),
        "unique_failure_modes": len(result.failure_modes),
        "guides_generated": len(result.guides),
    }
    report.quality = {
        "summary": quality.summary(),
        "issues": len(quality.issues),
        "errors": len(quality.errors()),
        "duplicate_groups": len(quality.duplicates),
    }
    for item in result.equipment:
        mode_count = sum(
            1 for guide in result.guides if guide.equipment_code == item.equipment_code
        )
        report.equipment.append(
            {
                "code": item.equipment_code,
                "name": item.name,
                "records": item.record_count,
                "failure_modes": mode_count,
                "t1": item.technical_tree.t1,
                "t2": item.technical_tree.t2,
                "t3": item.technical_tree.t3,
                "manufacturer": item.manufacturer,
                "model": item.model,
            }
        )
    for mode in result.failure_modes:
        report.failure_modes.append(
            {
                "id": mode.key,
                "label": mode.canonical_label,
                "normalized": mode.normalized_label,
                "aliases": mode.aliases,
                "records": len(mode.record_ids),
                "status": mode.status,
            }
        )
    with TroubleshootingRepository(database_path) as repository:
        for guide in result.guides:
            stored = repository.get_troubleshooting_guide(
                guide.equipment_code, guide.failure_mode.key
            )
            causes = stored.causes if stored else []
            report.guides.append(
                {
                    "equipment": guide.equipment_code,
                    "failure_mode": guide.failure_mode.key,
                    "label": guide.failure_mode.label,
                    "causes": len(causes),
                    "top_cause": causes[0].label if causes else None,
                    "top_support": causes[0].support_percent if causes else None,
                    "insufficient_repair_evidence": not any(c.actions for c in causes),
                }
            )
            for cause in causes[: max(1, max_cause_rows // max(1, len(result.guides)))]:
                report.causes.append(
                    {
                        "equipment": guide.equipment_code,
                        "mode": guide.failure_mode.key,
                        "cause": cause.label,
                        "kinds": cause.kinds,
                        "support_percent": cause.support_percent,
                        "probability": cause.probability,
                        "evidence_count": cause.evidence_count,
                        "weighted_evidence": round(cause.weighted_evidence, 4),
                        "denominator": round(cause.denominator, 4),
                        "method": cause.calculation_method,
                        "records": [row["record_id"] for row in cause.evidence],
                    }
                )
        # Repair-action roll-up straight from the database.
        import sqlite3

        connection = sqlite3.connect(str(database_path))
        try:
            report.repair_actions = [
                {
                    "category": row[0],
                    "role": row[1],
                    "count": row[2],
                }
                for row in connection.execute(
                    "SELECT category, role, COUNT(*) FROM repair_actions "
                    "GROUP BY 1, 2 ORDER BY 3 DESC"
                ).fetchall()
            ]
            # Support self-audit: recompute every percentage from evidence.
            mismatches = connection.execute(
                """SELECT COUNT(*) FROM candidate_causes
                   WHERE ABS(support_percent - 100.0 * weighted_evidence
                         / NULLIF(denominator, 0)) > 1e-9
                     AND denominator > 0"""
            ).fetchone()[0]
            checked = connection.execute(
                "SELECT COUNT(*) FROM candidate_causes WHERE denominator > 0"
            ).fetchone()[0]
            report.support_audit = {
                "causes_checked": checked,
                "mismatches": mismatches,
                "formula": "100 * weighted_evidence / denominator",
            }
        finally:
            connection.close()

    if split is not None:
        report.split = split.to_dict()
        report.split["train_equipment"] = len(split.train_codes)
        report.split["test_equipment"] = len(split.test_codes)
        report.leakage = check_leakage(split)
    if evaluation is not None:
        report.evaluation = {
            "summary": evaluation.summary(),
            "total": evaluation.total,
            "equipment_matched": evaluation.equipment_matched,
            "mode_matched": evaluation.mode_matched,
            "cause_hits": evaluation.cause_hits,
            "limitations": evaluation.limitations,
        }

    generic = sorted(
        {
            entry["cause"]
            for entry in report.causes
            if any(marker in entry["cause"] for marker in GENERIC_CAUSE_MARKERS)
        }
    )
    report.suspicious = {
        "generic_causes": generic,
        "fallback_record_ids": (
            [p.record_id for p in result.input_report.row_problems if p.record_id]
            if result.input_report
            else []
        ),
        "unclassified_modes": [
            {"id": m.key, "label": m.canonical_label}
            for m in result.failure_modes
            if m.status == "unclassified"
        ][:20],
        "insufficient_repair_guides": [
            f"{g['equipment']}/{g['failure_mode']}"
            for g in report.guides
            if g["insufficient_repair_evidence"]
        ][:20],
    }
    report.limitations = [
        "Percentages are evidence shares, not calibrated probabilities.",
        "Causes absent from history cannot be suggested.",
        "Lexical clustering groups wording, not deep semantics.",
        "Single-record guides have low confidence by construction.",
        "Held-out associations use recorded causes as proxies, not truth.",
    ]
    return report
