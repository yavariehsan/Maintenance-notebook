"""Excel input adapter: configurable Persian column mapping + reader.

Design points:

- Canonical fields accept header aliases (Persian defaults + caller
  additions); unknown headers are preserved, never dropped.
- Equipment codes are identifiers: numeric Excel cells are coerced to
  exact strings (``210.0`` → ``"210"``), never reformatted.
- Empty rows are counted and skipped; unbuildable rows are reported in
  ``InputReport.skipped_rows`` with reasons — never silently lost.
- ``openpyxl`` is imported lazily so the failure mode is a clear message,
  not an import-time crash of unrelated modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from maintenance_troubleshooting.domain.equipment import TechnicalTree
from maintenance_troubleshooting.domain.records import MaintenanceRecord
from maintenance_troubleshooting.inputs.record_ids import (
    PrefixNumberRecordId,
    RecordIdStrategy,
)

#: Cell texts that mean "missing" (matched case-insensitively when stripped).
DEFAULT_PLACEHOLDERS: tuple[str, ...] = (
    "-",
    "–",
    "—",
    "نامشخص",
    "unknown",
    "n/a",
    "؟",
    "?",
)

#: Canonical field → accepted header names (Persian defaults first).
DEFAULT_COLUMN_ALIASES: dict[str, list[str]] = {
    # Equipment identity is کد فرایندی (stable process code). تجهیز is the
    # display name; it doubles as a legacy fallback for the code so sheets
    # that only carry تجهیز still resolve (resolution order matters: code
    # claims a header before the name does).
    "equipment_code": ["کد فرایندی", "کد تجهیز", "کد دستگاه", "تجهیز", "equipment_code"],
    "equipment_name": ["تجهیز", "نام تجهیز", "equipment_name"],
    "repair_unit_code": ["کد واحد تعمیراتی"],
    "process_name": ["فرایند"],
    "request_prefix": ["پیشوند درخواست"],
    "request_number": ["شماره درخواست"],
    "request_description": ["شرح درخواست"],
    "repair_description": ["شرح تعمیر"],
    "repair_start_year": ["سال شروع تعمیر"],
    "repair_start_month": ["ماه شروع تعمیر"],
    "repair_start_date": ["تاریخ شروع تعمیر"],
    "repair_start_time": ["زمان شروع تعمیر"],
    "test_start_year": ["سال شروع تست"],
    "test_start_month": ["ماه شروع تست"],
    "test_start_date": ["تاریخ شروع تست"],
    "test_start_time": ["زمان شروع تست"],
    "request_year": ["سال درخواست"],
    "request_month": ["ماه درخواست"],
    "request_date": ["تاریخ درخواست"],
    "request_time": ["ساعت درخواست"],
    "test_end_year": ["سال پایان تست"],
    "test_end_month": ["ماه پایان تست"],
    "test_end_date": ["تاریخ پایان تست"],
    "test_end_time": ["زمان پایان تست"],
    "expected_delivery_year": ["سال تحویل پیش بینی شده"],
    "expected_delivery_month": ["ماه تحویل پیش بینی شده"],
    "expected_delivery_date": ["تاریخ تحویل پیش بینی شده"],
    "expected_delivery_time": ["زمان تحویل پیش بینی شده"],
    "repair_end_year": ["سال پایان تعمیر"],
    "repair_end_month": ["ماه پایان تعمیر"],
    "repair_end_date": ["تاریخ پایان تعمیر"],
    "repair_end_time": ["زمان پایان تعمیر"],
    "failure_mechanism": ["مکانیزم خرابی"],
    "location_tree": ["درخت موقعیت"],
    "process_tree": ["درخت فرایند"],
    "technical_tree": ["درخت تکنیکال"],
    "t1": ["t1", "T1"],
    "t2": ["t2", "T2"],
    "t3": ["t3", "T3"],
    "t4": ["t4", "T4"],
    "t5": ["t5", "T5"],
    "t6": ["t6", "T6"],
    "t7": ["t7", "T7"],
    "t8": ["t8", "T8"],
    "t9": ["t9", "T9"],
    "t10": ["t10", "T10"],
    "t11": ["t11", "T11"],
    "predicted_duration": ["پیش بینی مدت انجام کار"],
    "eir_proposal": ["پیشنهاد بهبود جهت جلوگیری از بروز مجددخرابی (EIR)"],
    "report_quality": ["کیفیت گزارش"],
    "work_time": ["زمان انجام کار"],
    "repair_quality": ["کیفیت تعمیر"],
    "deletion_reason": ["دلیل حذف برگه"],
    "defect_cause": ["دلیل بروز عیب"],
    "referral_reason": ["دلیل ارجاع"],
    "safety_notes": ["خطرات بالقوه/ملاحظات ایمنی/"],
    "proposed_failure_mode": ["حالت خرابی پیشنهادی"],
    "issue_bank_recorded": ["ثبت در بانک مساله"],
    "defect_cause_detail": ["توضیحات دلیل بروز عیب"],
    "parameter_change_detail": ["توضیحات تغییر در پارامترهای سیستم"],
    "bypass_detail": ["توضیحات Bypass"],
    "parameter_change": ["تغییر در پارامترهای سیستم"],
    "eir_approved": ["آیا EIR پیشنهادی تکنسین مورد تایید است؟"],
    "bypass": ["Bypass"],
    "registered_by": ["کاربر ثبت کننده"],
    "delay_cause": ["علت تاخیر"],
    "total_man_hours": ["جمع نفر ساعت"],
    "request_type": ["نوع درخواست", "توع درخواست"],
    "stop_time": ["STOP TIME"],
    "stage": ["مرحله"],
    "failure_mode": ["حالت خرابی"],
    "referral": ["ارجاع"],
}

#: Fields required to build a usable record.
REQUIRED_FIELDS: tuple[str, ...] = ("equipment_code", "request_prefix", "request_number")

#: Fields collected into ``MaintenanceRecord.dates`` when present.
DATE_FIELDS: tuple[str, ...] = (
    "repair_start_year",
    "repair_start_month",
    "repair_start_date",
    "repair_start_time",
    "test_start_year",
    "test_start_month",
    "test_start_date",
    "test_start_time",
    "request_year",
    "request_month",
    "request_date",
    "request_time",
    "test_end_year",
    "test_end_month",
    "test_end_date",
    "test_end_time",
    "expected_delivery_year",
    "expected_delivery_month",
    "expected_delivery_date",
    "expected_delivery_time",
    "repair_end_year",
    "repair_end_month",
    "repair_end_date",
    "repair_end_time",
)


def preserve_identifier(value: Any) -> str | None:
    """Coerce an Excel cell to an exact identifier string.

    ``"B104"`` stays ``"B104"``; numeric ``210`` stays ``"210"`` (never
    ``"210.0"``); blank cells become ``None``. Identifiers are never
    text-normalized.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    text = str(value).strip()
    return text or None


def _is_placeholder(text: str, placeholders: tuple[str, ...]) -> bool:
    """Whether a stripped cell text is a missing-value placeholder."""
    lowered = text.strip().lower()
    return any(lowered == marker.lower() for marker in placeholders)


def _is_placeholder_value(value: Any, placeholders: tuple[str, ...]) -> bool:
    """Whether an Excel cell holds a missing-value placeholder string."""
    return isinstance(value, str) and bool(placeholders) and _is_placeholder(value, placeholders)


def _cell_text(value: Any, placeholders: tuple[str, ...] = ()) -> str | None:
    """Coerce a general cell to stripped text (dates → ISO format).

    Placeholder values (``"-"``, ``"نامشخص"``, …) become ``None`` so every
    downstream stage treats them as missing, never as real content.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text or _is_placeholder(text, placeholders):
        return None
    return text


@dataclass
class ColumnMapping:
    """Canonical field → accepted header aliases (configurable)."""

    aliases: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def default(cls) -> ColumnMapping:
        """Mapping with the known Persian workbook headers."""
        return cls(aliases={k: list(v) for k, v in DEFAULT_COLUMN_ALIASES.items()})

    def with_alias(self, canonical_field: str, header: str) -> ColumnMapping:
        """Return a copy accepting one more header for a canonical field."""
        updated = {k: list(v) for k, v in self.aliases.items()}
        updated.setdefault(canonical_field, [])
        if header not in updated[canonical_field]:
            updated[canonical_field].append(header)
        return ColumnMapping(aliases=updated)

    def resolve(self, headers: list[str]) -> ResolvedMapping:
        """Match workbook headers to canonical fields (first alias wins)."""
        normalized = {h.strip(): h for h in headers if h.strip()}
        field_to_header: dict[str, str] = {}
        used: set[str] = set()
        for canonical, options in self.aliases.items():
            for option in options:
                header = normalized.get(option.strip())
                if header is not None and header not in used:
                    field_to_header[canonical] = header
                    used.add(header)
                    break
        missing_required = [f for f in REQUIRED_FIELDS if f not in field_to_header]
        known = set(self.aliases)
        unmapped = [h for h in headers if h not in used]
        missing_optional = [f for f in known if f not in field_to_header and f not in REQUIRED_FIELDS]
        return ResolvedMapping(
            field_to_header=field_to_header,
            missing_required=missing_required,
            missing_optional=missing_optional,
            unmapped_headers=unmapped,
        )


@dataclass
class ResolvedMapping:
    """Result of matching headers to canonical fields."""

    field_to_header: dict[str, str]
    missing_required: list[str]
    missing_optional: list[str]
    unmapped_headers: list[str]


@dataclass
class SchemaReport:
    """Required/optional column coverage for a workbook sheet."""

    sheet: str
    headers: list[str]
    missing_required: list[str]
    missing_optional: list[str]
    unmapped_headers: list[str]

    @property
    def valid(self) -> bool:
        """Whether all required columns are present."""
        return not self.missing_required


@dataclass
class RowProblem:
    """A row that needed a deterministic fallback (reported, never silent)."""

    row_number: int
    reason: str
    record_id: str | None = None
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class InputReport:
    """What the reader saw: sheets, schema, row counts, skipped rows."""

    path: str
    sheet: str
    headers: list[str]
    schema: SchemaReport
    total_rows: int = 0
    empty_rows: int = 0
    records_built: int = 0
    fallback_ids: int = 0
    row_problems: list[RowProblem] = field(default_factory=list)


@dataclass
class ReadResult:
    """Canonical records plus the input report describing their origin."""

    records: list[MaintenanceRecord]
    report: InputReport


class ExcelMaintenanceReader:
    """Read a maintenance-history workbook into canonical records."""

    def __init__(
        self,
        record_id_strategy: RecordIdStrategy | None = None,
        sheet_name: str | None = None,
        header_row: int = 1,
        placeholders: tuple[str, ...] | None = None,
    ) -> None:
        self.record_id_strategy = record_id_strategy or PrefixNumberRecordId()
        self.sheet_name = sheet_name
        self.header_row = header_row
        self.placeholders = placeholders if placeholders is not None else DEFAULT_PLACEHOLDERS

    def read(
        self, path: str | Path, column_mapping: ColumnMapping | None = None
    ) -> ReadResult:
        """Read ``path`` (``.xlsx``) into records + report."""
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError(
                "Reading .xlsx workbooks requires the 'openpyxl' package. "
                "Install the maintenance-troubleshooting-engine dependencies."
            ) from exc

        mapping = column_mapping or ColumnMapping.default()
        workbook = openpyxl.load_workbook(filename=str(path), read_only=True, data_only=True)
        try:
            active = workbook[self.sheet_name] if self.sheet_name else workbook.active
            if active is None:
                raise ValueError(f"workbook '{path}' has no active sheet")
            sheet = active
            title = str(sheet.title)
            rows = list(sheet.iter_rows(values_only=True))
        finally:
            workbook.close()

        header_index = self.header_row - 1
        if len(rows) <= header_index:
            raise ValueError(f"sheet '{title}' has no header row {self.header_row}")
        headers = [str(cell).strip() if cell is not None else "" for cell in rows[header_index]]
        resolved = mapping.resolve(headers)
        schema = SchemaReport(
            sheet=title,
            headers=headers,
            missing_required=resolved.missing_required,
            missing_optional=resolved.missing_optional,
            unmapped_headers=resolved.unmapped_headers,
        )
        report = InputReport(path=str(path), sheet=title, headers=headers, schema=schema)
        if not schema.valid:
            raise ValueError(
                f"sheet '{title}' is missing required columns: "
                + ", ".join(schema.missing_required)
            )

        records: list[MaintenanceRecord] = []
        for offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
            report.total_rows += 1
            raw_cells = dict(zip(headers, row))
            # Placeholders ("-", "نامشخص", …) become missing for extraction,
            # while raw_cells keeps the originals for traceability.
            cells = {
                header: (
                    None
                    if _is_placeholder_value(value, self.placeholders)
                    else value
                )
                for header, value in raw_cells.items()
            }
            if all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
                report.empty_rows += 1
                continue
            record, problem = self._build_record(
                cells, resolved.field_to_header, offset, title, raw_cells
            )
            records.append(record)
            report.records_built += 1
            if problem is not None:
                if problem.record_id is not None:
                    report.fallback_ids += 1
                report.row_problems.append(problem)
        return ReadResult(records=records, report=report)

    def _fallback_record_id(self, sheet: str, row_number: int) -> str:
        """Deterministic fallback ID for rows without usable request IDs."""
        return f"ROW-{sheet}-{row_number}"

    def _build_record(
        self,
        cells: dict[str, Any],
        field_to_header: dict[str, str],
        row_number: int,
        sheet: str,
        raw_cells: dict[str, Any] | None = None,
    ) -> tuple[MaintenanceRecord, RowProblem | None]:
        """Build one canonical record, falling back deterministically.

        Rows are never discarded: a missing equipment code is kept blank
        (flagged ERROR by validation) and an unbuildable request ID gets a
        deterministic ``ROW-<sheet>-<row>`` fallback. Both are reported.
        """

        def get(canonical: str) -> Any:
            header = field_to_header.get(canonical)
            return cells.get(header) if header else None

        problem: RowProblem | None = None
        equipment_code = preserve_identifier(get("equipment_code")) or ""
        if not equipment_code:
            problem = RowProblem(
                row_number=row_number,
                reason="blank equipment code; record kept for traceability",
                values={k: v for k, v in cells.items() if v is not None},
            )
        prefix = _cell_text(get("request_prefix"))
        number = preserve_identifier(get("request_number"))
        try:
            record_id = self.record_id_strategy.build_id(prefix, number)
        except ValueError as exc:
            record_id = self._fallback_record_id(sheet, row_number)
            problem = RowProblem(
                row_number=row_number,
                reason=f"unbuildable request ID ({exc}); fallback ID assigned",
                record_id=record_id,
                values={k: v for k, v in cells.items() if v is not None},
            )

        tree_values = {
            name: _cell_text(get(name))
            for name in ("t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10", "t11")
        }
        dates = {
            name: text
            for name in DATE_FIELDS
            if (text := _cell_text(get(name))) is not None
        }
        raw = {header: (raw_cells or cells).get(header) for header in cells}
        mapped_headers = set(field_to_header.values())
        extra = {h: v for h, v in raw.items() if h not in mapped_headers and v is not None}

        return (
            MaintenanceRecord(
                record_id=record_id,
                equipment_code=equipment_code,
                equipment_name=_cell_text(get("equipment_name")),
            request_prefix=prefix,
            request_number=number,
            request_type=_cell_text(get("request_type")),
            stage=_cell_text(get("stage")),
            request_description=_cell_text(get("request_description")),
            repair_description=_cell_text(get("repair_description")),
            failure_mode_recorded=_cell_text(get("failure_mode")),
            proposed_failure_mode=_cell_text(get("proposed_failure_mode")),
            failure_mechanism_recorded=_cell_text(get("failure_mechanism")),
            cause_recorded=_cell_text(get("defect_cause")),
            cause_detail=_cell_text(get("defect_cause_detail")),
            referral=_cell_text(get("referral")),
            referral_reason=_cell_text(get("referral_reason")),
            technical_tree=TechnicalTree.from_mapping(tree_values),
            location_tree=_cell_text(get("location_tree")),
            process_tree=_cell_text(get("process_tree")),
            repair_unit_code=_cell_text(get("repair_unit_code")),
            process_name=_cell_text(get("process_name")),
            dates=dates,
            predicted_duration=_cell_text(get("predicted_duration")),
            eir_proposal=_cell_text(get("eir_proposal")),
            eir_approved=_cell_text(get("eir_approved")),
            report_quality=_cell_text(get("report_quality")),
            repair_quality=_cell_text(get("repair_quality")),
            work_time=_cell_text(get("work_time")),
            deletion_reason=_cell_text(get("deletion_reason")),
            safety_notes=_cell_text(get("safety_notes")),
            issue_bank_recorded=_cell_text(get("issue_bank_recorded")),
            parameter_change=_cell_text(get("parameter_change")),
            parameter_change_detail=_cell_text(get("parameter_change_detail")),
            bypass=_cell_text(get("bypass")),
            bypass_detail=_cell_text(get("bypass_detail")),
            registered_by=_cell_text(get("registered_by")),
            delay_cause=_cell_text(get("delay_cause")),
            total_man_hours=_cell_text(get("total_man_hours")),
            stop_time=_cell_text(get("stop_time")),
            raw=raw,
            extra=extra,
            ),
            problem,
        )
