"""Synthetic fixtures for package tests.

All data is invented for testing (equipment codes like ``QX-101``,
generic Persian maintenance phrases). No real customer data. Workbooks
are generated at test time with openpyxl — no binary fixtures in git.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SYNTHETIC_HEADERS: list[str] = [
    "تجهیز",
    "پیشوند درخواست",
    "شماره درخواست",
    "شرح درخواست",
    "شرح تعمیر",
    "حالت خرابی",
    "مکانیزم خرابی",
    "دلیل بروز عیب",
    "t1",
    "t2",
    "t3",
    "t4",
    "t5",
    "درخت موقعیت",
    "درخت فرایند",
]

SYNTHETIC_ROWS: list[list[Any]] = [
    [
        "QX-101",
        "QX",
        "1001",
        "دستگاه روشن نمی‌شود",
        "تعویض بلبرینگ اسپیندل انجام شد",
        "روشن نشدن دستگاه",
        "خرابی بلبرینگ",
        "فرسودگی",
        "ماشین‌ابزار",
        "فرز",
        "فرز عمودی",
        "سازنده الف",
        "مدل X1",
        "سالن ۱",
        "فرایند برش",
    ],
    [
        "QX-102",
        "QX",
        "1002",
        "نشتی هوا از اتصالات",
        "",
        "نشتی هوا",
        "",
        "",
        "ماشین‌ابزار",
        "فرز",
        "فرز عمودی",
        "سازنده الف",
        "مدل X1",
        "سالن ۱",
        "فرایند برش",
    ],
    [
        "QY-201",
        "QY",
        "2001",
        "محور مرجع نمی‌شود",
        "تنظیم مجدد انکودر محور",
        "عدم مرجع محور",
        "خطای انکودر",
        "نوسان برق",
        "ماشین‌ابزار",
        "تراش",
        "تراش افقی",
        "سازنده ب",
        "مدل Y2",
        "سالن ۲",
        "فرایند تراش",
    ],
]


def write_workbook(
    path: str | Path,
    headers: list[str] | None = None,
    rows: list[list[Any]] | None = None,
) -> Path:
    """Generate a synthetic .xlsx workbook at ``path``."""
    import openpyxl

    target = Path(path)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "repairs"
    sheet.append(list(headers if headers is not None else SYNTHETIC_HEADERS))
    for row in rows if rows is not None else SYNTHETIC_ROWS:
        sheet.append(list(row))
    workbook.save(str(target))
    return target
