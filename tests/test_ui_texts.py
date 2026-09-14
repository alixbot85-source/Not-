"""
تست متن‌های UI.

مهم‌ترین بررسی: خروجی باید HTML معتبر برای Bot API باشد و
ورودی کاربر همیشه escape شود (جلوگیری از خرابی parse و تزریق تگ).
"""
from __future__ import annotations

import re

import pytest

from app.db.models import (
    Account,
    AccountKind,
    AccountStatus,
    ItemStatus,
    Job,
    JobStatus,
    JobType,
    LinkKind,
    LogLevel,
)
from app.ui.texts import (
    bar,
    error_view,
    esc,
    extraction_report,
    fa_num,
    job_detail,
    job_report,
    main_panel,
    message_preview,
    progress_view,
)

# تگ‌هایی که واقعاً در Bot API پشتیبانی می‌شوند
ALLOWED_TAGS = {
    "b", "i", "u", "s", "a", "code", "pre", "tg-spoiler", "blockquote", "tg-emoji",
}


def extract_tags(html: str) -> set[str]:
    return {m.lower() for m in re.findall(r"</?([a-zA-Z\-]+)", html)}


class TestHtmlValidity:
    def test_only_supported_tags_used(self) -> None:
        samples = [
            main_panel("علی", 3, 5, 7),
            error_view("خطا", "جزئیات"),
            job_report(
                Job(id=1, type=JobType.JOINER, account_id=1, status=JobStatus.COMPLETED),
                "01:30",
            ),
            progress_view(
                title="📥 <b>JOINER</b>",
                account="A",
                job_id=1,
                total=10,
                processed=5,
                success=4,
                already=1,
                failed=0,
                current="گروه",
                status=JobStatus.RUNNING,
            ),
        ]
        for html in samples:
            assert extract_tags(html) <= ALLOWED_TAGS, html

    def test_tags_are_balanced(self) -> None:
        html = main_panel("x", 1, 1, 1)
        for tag in ("b", "i", "blockquote"):
            assert html.count(f"<{tag}>") == html.count(f"</{tag}>")


class TestEscaping:
    @pytest.mark.parametrize(
        "evil",
        [
            "<script>alert(1)</script>",
            "<b>fake bold</b>",
            "a & b",
            "<>&",
            "</blockquote><script>",
        ],
    )
    def test_user_input_is_escaped(self, evil: str) -> None:
        escaped = esc(evil)
        assert "<script" not in escaped
        assert "<b>" not in escaped
        if "&" in evil:
            assert "&amp;" in escaped

    def test_account_label_escaped_in_view(self) -> None:
        from app.ui.texts import account_detail

        account = Account(
            id=1,
            label="<script>bad</script>",
            kind=AccountKind.BOT_API,
            status=AccountStatus.ONLINE,
        )
        html = account_detail(account, [("x", "y")])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_error_detail_escaped(self) -> None:
        html = error_view("خطا", "<img src=x onerror=1>")
        assert "<img" not in html

    def test_preview_keeps_html_when_mode_is_html(self) -> None:
        """در حالت HTML، قالب‌بندی کاربر عمداً حفظ می‌شود (پیش‌نمایش واقعی)."""
        html = message_preview("<b>تست</b>", "HTML", "گروه‌ها", "A", 5)
        assert "<b>تست</b>" in html

    def test_preview_escapes_when_plain(self) -> None:
        html = message_preview("<b>تست</b>", "NONE", "گروه‌ها", "A", 5)
        assert "&lt;b&gt;" in html


class TestProgressBar:
    @pytest.mark.parametrize(
        "percent,filled", [(0, 0), (50, 5), (100, 10), (-10, 0), (150, 10)]
    )
    def test_bar_is_clamped(self, percent: int, filled: int) -> None:
        rendered = bar(percent)
        assert len(rendered) == 10
        assert rendered.count("█") == filled

    def test_progress_shows_real_numbers(self) -> None:
        html = progress_view(
            title="t",
            account="A",
            job_id=42,
            total=1000,
            processed=800,
            success=742,
            already=41,
            failed=17,
            current="Example Group",
            status=JobStatus.RUNNING,
        )
        assert "80%" in html
        assert "742" in html and "1,000" in html
        assert "#42" in html

    def test_zero_total_no_crash(self) -> None:
        html = progress_view(
            title="t", account="A", job_id=1, total=0, processed=0,
            success=0, already=0, failed=0, current="", status=JobStatus.PENDING,
        )
        assert "0%" in html


class TestNumbers:
    def test_thousand_separator(self) -> None:
        assert fa_num(1284) == "1,284"
        assert fa_num(0) == "0"
        assert fa_num("x") == "x"


class TestExtractionReport:
    def test_reports_real_counts(self) -> None:
        html = extraction_report(
            checked=20,
            found=1284,
            duplicates=137,
            invalid=31,
            kinds={LinkKind.GROUP: 1116, LinkKind.UNKNOWN: 0},
            ready=1116,
        )
        assert "20" in html and "1,284" in html and "137" in html
        assert "1,116" in html

    def test_empty_state_message(self) -> None:
        html = extraction_report(0, 0, 0, 0, {}, 0)
        assert "پیدا نشد" in html


class TestStatusLabels:
    def test_every_status_has_label(self) -> None:
        for status in JobStatus:
            assert status.label
        for status in ItemStatus:
            assert status.label
        for level in LogLevel:
            assert level.icon
        for kind in LinkKind:
            assert kind.label

    def test_final_states(self) -> None:
        assert JobStatus.COMPLETED.is_final
        assert JobStatus.FAILED.is_final
        assert not JobStatus.RUNNING.is_final
        assert not JobStatus.PENDING.is_final


class TestJobDetail:
    def test_recoverable_hint_shown(self) -> None:
        job = Job(
            id=5,
            type=JobType.JOINER,
            account_id=1,
            status=JobStatus.STOPPED,
            total=10,
            processed=6,
            recoverable=True,
            created_at="2026-01-01T10:00:00",
        )
        assert "قابل ادامه" in job_detail(job, "A")

    def test_not_recoverable_has_no_hint(self) -> None:
        job = Job(
            id=5,
            type=JobType.JOINER,
            account_id=1,
            status=JobStatus.COMPLETED,
            recoverable=False,
            created_at="2026-01-01T10:00:00",
        )
        assert "قابل ادامه" not in job_detail(job, "A")


class TestHtmlValidator:
    """اعتبارسنجی قالب‌بندی طبق قواعد واقعی Bot API."""

    @pytest.mark.parametrize(
        "text",
        [
            "متن ساده بدون تگ",
            "<b>پررنگ</b>",
            "<b><i>تو در تو</i></b>",
            "<tg-spoiler>مخفی</tg-spoiler>",
            '<a href="https://eitaa.com/x">لینک</a>',
            "<blockquote>نقل‌قول</blockquote>",
            "<pre><code>کد</code></pre>",
            '<span class="tg-spoiler">اسپویلر</span>',
            "<s>خط‌خورده</s><u>زیرخط</u>",
        ],
    )
    def test_valid_markup_accepted(self, text: str) -> None:
        from app.ui.texts import validate_telegram_html

        assert validate_telegram_html(text) == ""

    @pytest.mark.parametrize(
        "text,hint",
        [
            ("<marquee>x</marquee>", "پشتیبانی نمی‌شود"),
            ("<div>x</div>", "پشتیبانی نمی‌شود"),
            ("<script>x</script>", "پشتیبانی نمی‌شود"),
            ("<b>باز مانده", "بسته نشده"),
            ("<b><i>x</b></i>", "ترتیب"),
            ("بدون باز</b>", "بدون تگ باز"),
            ("<a>بدون لینک</a>", "href"),
            ("<span>بدون کلاس</span>", "tg-spoiler"),
        ],
    )
    def test_invalid_markup_rejected(self, text: str, hint: str) -> None:
        from app.ui.texts import validate_telegram_html

        problem = validate_telegram_html(text)
        assert problem and hint in problem

    def test_allowed_tag_list_matches_bot_api(self) -> None:
        from app.ui.texts import ALLOWED_HTML_TAGS

        # موارد تأییدشده در مستندات رسمی
        for tag in ("b", "i", "u", "s", "a", "code", "pre", "blockquote", "tg-spoiler"):
            assert tag in ALLOWED_HTML_TAGS
        # مواردی که Bot API پشتیبانی نمی‌کند
        for tag in ("div", "h1", "table", "img", "font", "marquee"):
            assert tag not in ALLOWED_HTML_TAGS
