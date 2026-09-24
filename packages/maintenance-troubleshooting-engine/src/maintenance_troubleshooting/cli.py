"""Command-line boundary: inspect / validate / analyze / export / inspect-output.

The CLI belongs to the package: a future UI calls the Python API or these
commands and never needs to know the internal pipeline layout.
"""

from __future__ import annotations

import argparse
import sys

from maintenance_troubleshooting.config import EngineConfig
from maintenance_troubleshooting.inputs import ColumnMapping, ExcelMaintenanceReader
from maintenance_troubleshooting.inputs.record_ids import PrefixNumberRecordId
from maintenance_troubleshooting.pipeline import analyze_workbook
from maintenance_troubleshooting.quality import DuplicateDetector, RecordValidator
from maintenance_troubleshooting.runtime import TroubleshootingRepository
from maintenance_troubleshooting.version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser (separated for testability)."""
    parser = argparse.ArgumentParser(
        prog="maintenance-troubleshooting",
        description="Mine maintenance history and build troubleshooting guides.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="Summarize workbook sheets and headers.")
    inspect.add_argument("workbook", help="Path to the .xlsx workbook.")
    inspect.add_argument("--sheet", default=None, help="Sheet name (default: active).")

    validate = sub.add_parser("validate", help="Validate schema and data quality.")
    validate.add_argument("workbook", help="Path to the .xlsx workbook.")
    validate.add_argument("--sheet", default=None, help="Sheet name (default: active).")

    analyze = sub.add_parser(
        "analyze", help="Run the batch pipeline into a knowledge database."
    )
    analyze.add_argument("workbook", help="Path to the .xlsx workbook.")
    analyze.add_argument("--sheet", default=None, help="Sheet name (default: active).")
    analyze.add_argument(
        "-o",
        "--output",
        default="maintenance_troubleshooting.db",
        help="Output SQLite path (written atomically).",
    )
    analyze.add_argument(
        "--enrichment",
        choices=["none"],
        default="none",
        help="Batch enrichment provider (default works without any LLM).",
    )

    export = sub.add_parser("export", help="Analyze and write the knowledge base JSON.")
    export.add_argument("workbook", help="Path to the .xlsx workbook.")
    export.add_argument("--sheet", default=None, help="Sheet name (default: active).")
    export.add_argument("-o", "--output", required=True, help="Output JSON path.")

    show = sub.add_parser("inspect-output", help="Inspect a knowledge database.")
    show.add_argument("database", help="Path to the .db file.")
    show.add_argument("--equipment", default=None, help="Show one equipment's guides.")
    show.add_argument("--failure-mode", default=None, help="Filter to one failure mode.")
    return parser


def _reader(sheet: str | None) -> ExcelMaintenanceReader:
    return ExcelMaintenanceReader(
        record_id_strategy=PrefixNumberRecordId(), sheet_name=sheet
    )


def cmd_inspect(workbook: str, sheet: str | None) -> int:
    """Print sheets, headers, and row counts."""
    reader = _reader(sheet)
    result = reader.read(workbook, ColumnMapping.default())
    report = result.report
    print(f"sheet: {report.sheet}")
    print(f"headers ({len(report.headers)}):")
    for header in report.headers:
        print(f"  - {header}")
    print(f"rows: {report.total_rows} total, {report.empty_rows} empty")
    if report.schema.missing_optional:
        print(f"missing optional columns: {len(report.schema.missing_optional)}")
    return 0


def cmd_validate(workbook: str, sheet: str | None) -> int:
    """Validate schema + data quality; exit 1 on error-level findings."""
    reader = _reader(sheet)
    try:
        result = reader.read(workbook, ColumnMapping.default())
    except ValueError as exc:
        print(f"schema error: {exc}")
        return 1
    quality = RecordValidator().validate_all(result.records)
    quality.duplicates.extend(DuplicateDetector().find_duplicates(result.records))
    print(quality.summary())
    for issue in quality.issues:
        print(f"[{issue.severity.value}] {issue.record_id} {issue.field}: {issue.message}")
    for problem in result.report.row_problems:
        print(f"[info] row {problem.row_number}: {problem.reason}")
    failed = bool(quality.errors())
    return 1 if failed else 0


def cmd_analyze(workbook: str, sheet: str | None, output: str, enrichment: str) -> int:
    """Run the batch pipeline into a SQLite knowledge database."""
    if enrichment != "none":  # pragma: no cover - argparse choices guard this
        print(f"unknown enrichment provider: {enrichment}")
        return 2
    config = EngineConfig.default()
    if sheet is not None:
        config.input.sheet_name = sheet
    result = analyze_workbook(workbook, configuration=config, output_path=output)
    print(f"records: {len(result.records)}")
    print(f"equipment: {len(result.equipment)}")
    print(f"failure modes: {len(result.failure_modes)}")
    print(f"guides: {len(result.guides)}")
    print(result.quality_report.summary())
    for warning in result.warnings:
        print(f"warning: {warning}")
    print(f"wrote {output}")
    return 0


def cmd_export(workbook: str, sheet: str | None, output: str) -> int:
    """Analyze and write the knowledge-base JSON artifact."""
    config = EngineConfig.default()
    if sheet is not None:
        config.input.sheet_name = sheet
    result = analyze_workbook(workbook, configuration=config)
    if result.knowledge_base is None:  # pragma: no cover - defensive
        print("analysis produced no knowledge base")
        return 1
    target = result.knowledge_base.save(output)
    print(f"wrote {target} ({result.knowledge_base.record_count} source records)")
    return 0


def cmd_inspect_output(
    database: str, equipment: str | None, failure_mode: str | None
) -> int:
    """Inspect a generated knowledge database (reads only, no mining)."""
    try:
        repository = TroubleshootingRepository(database)
    except Exception as exc:
        print(f"cannot open database: {exc}")
        return 1
    with repository:
        meta = repository.metadata()
        print(
            f"engine {meta.get('engine_version', '?')} / "
            f"schema {meta.get('schema_version', '?')}"
        )
        items = repository.list_equipment()
        if equipment is not None:
            items = [item for item in items if item.code == equipment]
            if not items:
                print(f"unknown equipment: {equipment}")
                return 1
        print(f"equipment: {len(items)}")
        for item in items:
            print(f"  {item.code} ({item.record_count} records)")
            modes = repository.list_failure_modes(item.code)
            if failure_mode is not None:
                modes = [m for m in modes if failure_mode in (m.id, m.label)]
            for mode in modes:
                print(f"    {mode.id}: {mode.label} ({mode.record_count} records)")
                guide = repository.get_troubleshooting_guide(item.code, mode.id)
                if guide is None:
                    continue
                for cause in guide.causes:
                    support = (
                        f"{cause.support_percent:.1f}%"
                        if cause.support_percent is not None
                        else "n/a"
                    )
                    print(
                        f"      - {cause.label} [{support}, "
                        f"{cause.evidence_count} records, "
                        f"{len(cause.actions)} actions]"
                    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (``maintenance-troubleshooting`` console script)."""
    try:
        # Persian output on platforms whose console defaults elsewhere.
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    if args.command == "inspect":
        return cmd_inspect(args.workbook, args.sheet)
    if args.command == "validate":
        return cmd_validate(args.workbook, args.sheet)
    if args.command == "analyze":
        return cmd_analyze(args.workbook, args.sheet, args.output, args.enrichment)
    if args.command == "export":
        return cmd_export(args.workbook, args.sheet, args.output)
    if args.command == "inspect-output":
        return cmd_inspect_output(args.database, args.equipment, args.failure_mode)
    build_parser().error(f"unknown command: {args.command}")
    return 2  # pragma: no cover - argparse exits first


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
