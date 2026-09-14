"""تست خروجی‌گیری (بخش ۲۱) — شامل تولید واقعی فایل فارسی."""
from __future__ import annotations

import csv
import io
import json

import pytest

from app.services.exporter import (
    BOM,
    ExportPayload,
    available_formats,
    pdf_available,
    render,
    to_csv,
    to_json,
    to_txt,
    xlsx_available,
)


@pytest.fixture()
def payload() -> ExportPayload:
    return ExportPayload(
        title="گزارش عملیات ۱۰۴۲",
        headers=["ردیف", "مقصد", "وضعیت"],
        rows=[
            ["1", "https://eitaa.com/گروه_اول", "✅ موفق"],
            ["2", "https://eitaa.com/group2", "❌ ناموفق"],
            ["3", "کانال تست", "⚠️ قبلاً انجام شده"],
        ],
        summary={"مجموع": "۳", "موفق": "۱"},
    )


class TestTxt:
    def test_utf8_persian(self, payload) -> None:
        data = to_txt(payload)
        text = data.decode("utf-8")
        assert "گزارش عملیات" in text
        assert "گروه_اول" in text


class TestCsv:
    def test_has_bom_for_excel(self, payload) -> None:
        """CSV فارسی بدون BOM در Excel خراب باز می‌شود."""
        text = to_csv(payload).decode("utf-8")
        assert text.startswith(BOM)

    def test_parses_back_correctly(self, payload) -> None:
        text = to_csv(payload).decode("utf-8").lstrip(BOM)
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == payload.headers
        assert len(rows) == 4
        assert "گروه_اول" in rows[1][1]

    def test_injection_chars_survive_quoting(self) -> None:
        data = ExportPayload(
            title="t",
            headers=["a"],
            rows=[['va,lue "quoted"'], ["line\nbreak"]],
            summary={},
        )
        text = to_csv(data).decode("utf-8").lstrip(BOM)
        parsed = list(csv.reader(io.StringIO(text)))
        assert parsed[1] == ['va,lue "quoted"']
        assert parsed[2] == ["line\nbreak"]


class TestJson:
    def test_structure_and_unicode(self, payload) -> None:
        data = json.loads(to_json(payload).decode("utf-8"))
        assert data["title"] == "گزارش عملیات ۱۰۴۲"
        assert data["columns"] == payload.headers
        assert len(data["rows"]) == 3
        assert data["rows"][0]["مقصد"].endswith("گروه_اول")

    def test_not_ascii_escaped(self, payload) -> None:
        raw = to_json(payload).decode("utf-8")
        assert "\\u06af" not in raw  # فارسی باید خوانا بماند


@pytest.mark.skipif(not xlsx_available(), reason="openpyxl نصب نیست")
class TestXlsx:
    def test_generates_valid_workbook(self, payload) -> None:
        import openpyxl

        content, name = render(payload, "xlsx")
        assert name.endswith(".xlsx")
        workbook = openpyxl.load_workbook(io.BytesIO(content))
        sheet = workbook.active
        assert sheet.sheet_view.rightToLeft is True      # RTL واقعی
        assert [c.value for c in sheet[1]] == payload.headers
        assert sheet.max_row == 4


@pytest.mark.skipif(not pdf_available(), reason="فونت فارسی یا کتابخانهٔ PDF موجود نیست")
class TestPdf:
    def test_generates_real_pdf(self, payload) -> None:
        content, name = render(payload, "pdf")
        assert name.endswith(".pdf")
        assert content.startswith(b"%PDF")
        assert len(content) > 1000

    def test_embeds_persian_font(self, payload) -> None:
        content, _ = render(payload, "pdf")
        assert b"Vazirmatn" in content or b"PersianFont" in content


class TestFormats:
    def test_core_formats_always_available(self) -> None:
        formats = available_formats()
        assert {"txt", "csv", "json"}.issubset(set(formats))

    def test_unknown_format_rejected(self, payload) -> None:
        with pytest.raises(ValueError):
            render(payload, "docx")

    def test_filename_is_safe(self, payload) -> None:
        _, name = render(payload, "txt")
        assert "/" not in name and ".." not in name

    @pytest.mark.parametrize("fmt", ["txt", "csv", "json"])
    def test_all_render(self, payload, fmt) -> None:
        content, name = render(payload, fmt)
        assert content and name.endswith(f".{fmt}")
