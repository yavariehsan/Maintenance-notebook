"""Rich synthetic scenario for Milestone 2 end-to-end tests.

Invented equipment and records (no real customer data):

- ``B104`` — STARRAGHECKERT SX-051, several "Machine does not start"
  records with different historical causes;
- ``B105`` — same model (SX-051), supporting similarity transfer;
- ``M210`` — same manufacturer, different model (weaker similarity);
- ``H13`` — unrelated manufacturer parked at the SAME location/process
  as B104 (proves location/process never drive similarity).

Coverage: misleading recorded mode (R4), sparse repair text (R3),
incorrect operator classification, mixed Persian/English terms
(PLC, power supply, spindle, pressure switch, B Axis, connector).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

M2_HEADERS: list[str] = [
    "کد فرایندی",
    "تجهیز",
    "پیشوند درخواست",
    "شماره درخواست",
    "شرح درخواست",
    "شرح تعمیر",
    "حالت خرابی",
    "حالت خرابی پیشنهادی",
    "مکانیزم خرابی",
    "دلیل بروز عیب",
    "توضیحات دلیل بروز عیب",
    "t1",
    "t2",
    "t3",
    "t4",
    "t5",
    "درخت موقعیت",
    "درخت فرایند",
    "خطرات بالقوه/ملاحظات ایمنی/",
]

_B104_TREE = ["ماشین‌ابزار", "فرز", "فرز عمودی", "STARRAGHECKERT", "SX-051"]

M2_ROWS: list[list[Any]] = [
    # R1: start failure, power-supply cause, full repair chain + safety.
    [
        "B104", "فرز STARRAG SX-051", "B", "101",
        "دستگاه Machine does not start روشن نمی‌شود",
        "power supply بررسی شد. منبع تغذیه تعویض شد. تست روشن شدن انجام شد",
        "روشن نشدن دستگاه", "", "عدم بوت PLC", "خرابی منبع تغذیه", "",
        *_B104_TREE, "سالن ۱", "فرایند برش", "قبل از کار برق را قطع کنید",
    ],
    # R2: same symptom (spelling variant), wiring cause, English repair.
    [
        "B104", "فرز STARRAG SX-051", "B", "102",
        "دستگاه روشن نمی شود",
        "checked pressure switch. found loose wire in connector. "
        "repaired connector. tested machine",
        "دستگاه روشن نمی شود", "", "قطعی سیم‌کشی کنترل", "شل بودن سیم‌کشی", "",
        *_B104_TREE, "سالن ۱", "فرایند برش", "",
    ],
    # R3: sparse repair description (no actions may be invented).
    [
        "B104", "فرز STARRAG SX-051", "B", "103",
        "Machine does not start",
        "",
        "روشن نشدن", "", "خطای سیستم کنترل", "control-system fault", "",
        *_B104_TREE, "سالن ۱", "فرایند برش", "",
    ],
    # R4: misleading recorded mode (oil leak) with start-failure evidence.
    [
        "B104", "فرز STARRAG SX-051", "B", "104",
        "دستگاه روشن نمی‌شود",
        "منبع تغذیه تعویض شد",
        "نشت روغن", "", "عدم بوت PLC", "خرابی منبع تغذیه", "",
        *_B104_TREE, "سالن ۱", "فرایند برش", "",
    ],
    # R5: different failure mode (air leakage).
    [
        "B104", "فرز STARRAG SX-051", "B", "105",
        "نشتی هوا از مدار",
        "pressure switch بررسی شد. connector تعویض شد. نشتی هوا تست شد",
        "نشتی هوا", "", "خرابی pressure switch", "فرسودگی اتصالات", "",
        *_B104_TREE, "سالن ۱", "فرایند برش", "",
    ],
    # R6: tool-change mode with spindle / B Axis terms.
    [
        "B104", "فرز STARRAG SX-051", "B", "106",
        "B Axis مرجع نمی‌شود",
        "B Axis بررسی شد. spindle قفل بود و آزاد شد. انکودر تنظیم شد",
        "مشکل تعویض ابزار", "", "خطای انکودر", "سایش ابزار", "",
        *_B104_TREE, "سالن ۱", "فرایند برش", "",
    ],
    # R7: B105, same model SX-051, PLC cause.
    [
        "B105", "فرز STARRAG SX-051 دوم", "B2", "201",
        "Machine does not start",
        "PLC modules checked. ماژول تغذیه PLC تعویض شد. برنامه PLC تست شد",
        "روشن نشدن دستگاه", "", "عدم بوت PLC", "PLC startup failure", "",
        "ماشین‌ابزار", "فرز", "فرز عمودی", "STARRAGHECKERT", "SX-051",
        "سالن ۱", "فرایند مونتاژ", "",
    ],
    # R8: M210, same manufacturer, different model, same cause wording.
    [
        "M210", "فرز STARRAG SX-090", "M", "301",
        "دستگاه روشن نمی‌شود",
        "power supply تعویض شد. دستگاه تست شد",
        "روشن نشدن", "", "خرابی منبع تغذیه", "خرابی منبع تغذیه", "",
        "ماشین‌ابزار", "فرز", "فرز عمودی", "STARRAGHECKERT", "SX-090",
        "سالن ۳", "فرایند برش", "",
    ],
    # R9: H13, unrelated manufacturer, SAME location/process as B104.
    [
        "H13", "کمپرسور GA-75", "H", "401",
        "Machine does not start",
        "پمپ هیدرولیک تعویض شد. فشار تست شد",
        "روشن نشدن دستگاه", "", "خرابی پمپ هیدرولیک", "hydraulic pump failure", "",
        "تجهیزات تأسیساتی", "کمپرسور", "کمپرسور اسکرو", "ATLAS COPCO", "GA-75",
        "سالن ۱", "فرایند برش", "",
    ],
]

EXPECTED_B104_START_RECORDS = ["B-101", "B-102", "B-103"]
EXPECTED_START_SUPPORT_RECORDS = ["B-101", "B-102", "B-103", "B2-201", "M-301"]
SPARSE_RECORD_ID = "B-103"


def write_b104_workbook(path: str | Path) -> Path:
    """Generate the B104 scenario workbook at ``path``."""
    import openpyxl

    target = Path(path)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "repairs"
    sheet.append(list(M2_HEADERS))
    for row in M2_ROWS:
        sheet.append(list(row))
    workbook.save(str(target))
    return target
