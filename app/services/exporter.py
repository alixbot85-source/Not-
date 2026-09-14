"""
خروجی‌گیری (بخش ۲۱) — TXT / CSV / JSON / XLSX / PDF.

نکات واقعی پیاده‌سازی‌شده:
  • UTF-8 و در جاهای لازم UTF-8 BOM (برای باز شدن درست CSV در Excel فارسی).
  • PDF با reportlab + فونت واقعی فارسی + arabic_reshaper + python-bidi (RTL).
  • اگر فونت فارسی موجود نباشد، PDF **غیرفعال** و صادقانه اعلام می‌شود؛
    خروجیِ ناخوانا تولید نمی‌کنیم.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from app.config import config
from app.security import safe_filename

log = logging.getLogger(__name__)

BOM = "\ufeff"


@dataclass(slots=True)
class ExportPayload:
    """داده‌های آمادهٔ خروجی."""

    title: str
    headers: list[str]
    rows: list[list[str]]
    summary: dict[str, str]


# ══════════════════════════════════════════════════════════════════
#  تشخیص واقعی امکانات
# ══════════════════════════════════════════════════════════════════
def _font_file() -> Path | None:
    """اولین فونت فارسی موجود را برمی‌گرداند (بدون حدس)."""
    candidates = [config.font_path, config.data_dir / "fonts" / "Vazirmatn-Regular.ttf"]
    for path in candidates:
        if path.is_file():
            return path
    return None


def pdf_available() -> bool:
    """PDF فقط با کتابخانه‌ها و فونت فارسی واقعی فعال است."""
    if _font_file() is None:
        return False
    try:
        import arabic_reshaper  # noqa: F401
        import bidi  # noqa: F401
        import reportlab  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def xlsx_available() -> bool:
    try:
        import openpyxl  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def pdf_unavailable_reason() -> str:
    if _font_file() is None:
        return (
            "فونت فارسی پیدا نشد. یک فایل TTF فارسی را در مسیر "
            f"{config.font_path} قرار دهید یا PERSIAN_FONT_PATH را تنظیم کنید."
        )
    try:
        import arabic_reshaper  # noqa: F401
        import bidi  # noqa: F401
        import reportlab  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return f"کتابخانهٔ لازم نصب نیست: {exc}"
    return ""


# ══════════════════════════════════════════════════════════════════
#  تولیدکننده‌ها
# ══════════════════════════════════════════════════════════════════
def to_txt(payload: ExportPayload) -> bytes:
    lines = [payload.title, "=" * 40, ""]
    for key, value in payload.summary.items():
        lines.append(f"{key}: {value}")
    lines += ["", " | ".join(payload.headers), "-" * 40]
    lines += [" | ".join(row) for row in payload.rows]
    return "\n".join(lines).encode("utf-8")


def to_csv(payload: ExportPayload) -> bytes:
    """CSV با BOM تا Excel فارسی را درست بخواند."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(payload.headers)
    writer.writerows(payload.rows)
    return (BOM + buffer.getvalue()).encode("utf-8")


def to_json(payload: ExportPayload) -> bytes:
    data = {
        "title": payload.title,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": payload.summary,
        "columns": payload.headers,
        "rows": [dict(zip(payload.headers, row)) for row in payload.rows],
    }
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def to_xlsx(payload: ExportPayload) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Report"
    sheet.sheet_view.rightToLeft = True  # نمایش RTL واقعی

    sheet.append(payload.headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    for row in payload.rows:
        sheet.append(row)

    for column_index, header in enumerate(payload.headers, start=1):
        width = max([len(header)] + [len(r[column_index - 1]) for r in payload.rows] or [10])
        sheet.column_dimensions[sheet.cell(1, column_index).column_letter].width = min(50, width + 4)

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _shape(text: str) -> str:
    """شکل‌دهی حروف فارسی + اعمال الگوریتم BiDi برای نمایش درست RTL."""
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.reshape(str(text)))


def to_pdf(payload: ExportPayload) -> bytes:
    """PDF فارسی با فونت واقعی. فقط وقتی صدا زده می‌شود که pdf_available() باشد."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_path = _font_file()
    if font_path is None:
        raise RuntimeError(pdf_unavailable_reason())

    font_name = "PersianFont"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))

    stream = io.BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    title_style = ParagraphStyle(
        "title", fontName=font_name, fontSize=15, alignment=2, spaceAfter=10
    )
    normal_style = ParagraphStyle("normal", fontName=font_name, fontSize=9, alignment=2)

    story: list[object] = [Paragraph(_shape(payload.title), title_style)]
    for key, value in payload.summary.items():
        story.append(Paragraph(_shape(f"{key}: {value}"), normal_style))
    story.append(Spacer(1, 8))

    header = [Paragraph(_shape(h), normal_style) for h in reversed(payload.headers)]
    body = [
        [Paragraph(_shape(cell), normal_style) for cell in reversed(row)]
        for row in payload.rows[:800]  # سقف منطقی برای اندازهٔ فایل
    ]
    table = Table([header, *body], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    if len(payload.rows) > 800:
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(_shape(f"... و {len(payload.rows) - 800} ردیف دیگر"), normal_style)
        )
    doc.build(story)
    return stream.getvalue()


# ══════════════════════════════════════════════════════════════════
FORMATS = {
    "txt": ("text/plain", to_txt),
    "csv": ("text/csv", to_csv),
    "json": ("application/json", to_json),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", to_xlsx),
    "pdf": ("application/pdf", to_pdf),
}


def available_formats() -> list[str]:
    formats = ["txt", "csv", "json"]
    if xlsx_available():
        formats.append("xlsx")
    if pdf_available():
        formats.append("pdf")
    return formats


def render(payload: ExportPayload, fmt: str) -> tuple[bytes, str]:
    """تولید محتوا. خروجی: (بایت‌ها، نام فایل)."""
    fmt = fmt.lower().strip()
    if fmt not in FORMATS:
        raise ValueError(f"قالب پشتیبانی نمی‌شود: {fmt}")
    if fmt == "pdf" and not pdf_available():
        raise RuntimeError(pdf_unavailable_reason())
    if fmt == "xlsx" and not xlsx_available():
        raise RuntimeError("کتابخانهٔ openpyxl نصب نیست.")

    _, generator = FORMATS[fmt]
    content = generator(payload)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = safe_filename(f"{payload.title}-{stamp}.{fmt}")
    return content, name


def build_job_payload(
    job_id: int,
    job_type: str,
    summary: dict[str, str],
    rows: Sequence[tuple[str, str, str]],
) -> ExportPayload:
    """ساخت payload از آیتم‌های یک Job."""
    return ExportPayload(
        title=f"گزارش عملیات {job_id} - {job_type}",
        headers=["ردیف", "مقصد", "وضعیت", "توضیح"],
        rows=[[str(i), ref, status, reason] for i, (ref, status, reason) in enumerate(rows, 1)],
        summary=summary,
    )
