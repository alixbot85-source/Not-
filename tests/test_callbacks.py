"""تست سیستم Callback و کیبوردها (بخش ۱۵ و ۱۶)."""
from __future__ import annotations

import pytest

from app.db.models import Account, AccountKind, AccountStatus, Job, JobStatus, JobType, Linkdoni
from app.ui import keyboards as kb
from app.ui.callbacks import MAX_CALLBACK_BYTES, CallbackError, pack, parse


class TestPackParse:
    def test_roundtrip(self) -> None:
        data = pack("account", "view", 12)
        assert data == "account:view:12"
        cb = parse(data)
        assert (cb.namespace, cb.action, cb.int_arg) == ("account", "view", 12)

    def test_two_args(self) -> None:
        cb = parse(pack("linkdoni", "tgl", 5, 2))
        assert cb.int_arg == 5 and cb.int_arg2 == 2

    @pytest.mark.parametrize(
        "bad",
        ["", None, "nocolon", "UPPER:case", "a:b:c:d:e", "a:b:;drop", "x:y:<script>"],
    )
    def test_invalid_rejected(self, bad) -> None:
        with pytest.raises(CallbackError):
            parse(bad)

    def test_non_numeric_arg_raises(self) -> None:
        with pytest.raises(CallbackError):
            parse("account:view:abc").int_arg

    def test_length_limit_enforced(self) -> None:
        """محدودیت واقعی Bot API برای callback_data ۶۴ بایت است."""
        with pytest.raises(CallbackError):
            pack("account", "view", "x" * 100)


class TestKeyboardLimits:
    """هیچ دکمه‌ای نباید از محدودیت واقعی تلگرام عبور کند."""

    @staticmethod
    def _check(markup) -> None:
        for row in markup.inline_keyboard:
            for button in row:
                if button.callback_data is not None:
                    assert len(button.callback_data.encode()) <= MAX_CALLBACK_BYTES
                assert button.text

    def test_main_menu(self) -> None:
        self._check(kb.main_menu())

    def test_accounts_menu(self) -> None:
        accounts = [
            Account(
                id=i,
                label="اکانت با نام بسیار طولانی برای تست محدودیت",
                kind=AccountKind.BOT_API,
                status=AccountStatus.ONLINE,
            )
            for i in range(1, 9)
        ]
        self._check(kb.accounts_menu(accounts, 1, 3, empty=False))
        self._check(kb.accounts_menu([], 1, 1, empty=True))

    def test_linkdoni_menu(self) -> None:
        items = [
            Linkdoni(id=i, url=f"https://eitaa.com/channel{i}", title="ل" * 50)
            for i in range(1, 9)
        ]
        self._check(kb.linkdoni_menu(items, 2, 5, empty=False))

    def test_jobs_menu(self) -> None:
        jobs = [
            Job(id=i, type=JobType.JOINER, account_id=1, status=JobStatus.RUNNING)
            for i in range(1, 9)
        ]
        self._check(kb.jobs_menu(jobs, 1, 2))

    def test_all_static_menus(self) -> None:
        for markup in (
            kb.account_add_menu(),
            kb.targets_menu(),
            kb.preview_menu(),
            kb.settings_menu(),
            kb.ai_menu(),
            kb.ai_styles_menu(),
            kb.composer_menu(True),
            kb.composer_menu(False),
            kb.sender_menu(True, True, True),
            kb.joiner_menu(True),
            kb.export_menu(999, True),
            kb.export_menu(999, False),
            kb.running_menu(42, paused=False),
            kb.running_menu(42, paused=True),
            kb.report_menu(7, has_failed=True),
        ):
            self._check(markup)


class TestPagination:
    def test_page_count(self) -> None:
        assert kb.page_count(0, 8) == 1
        assert kb.page_count(8, 8) == 1
        assert kb.page_count(9, 8) == 2
        assert kb.page_count(100, 8) == 13

    def test_hidden_for_single_page(self) -> None:
        assert kb.pagination_row("account", "list", 1, 1) == []

    def test_wraps_around(self) -> None:
        row = kb.pagination_row("account", "list", 1, 5)
        assert row[0].callback_data == "account:list:5"   # قبلی از صفحهٔ ۱ → آخر
        assert row[2].callback_data == "account:list:2"
        assert row[1].text == "1 / 5"

    def test_last_page_wraps_to_first(self) -> None:
        row = kb.pagination_row("job", "list", 5, 5)
        assert row[2].callback_data == "job:list:1"


class TestNavigation:
    def test_back_and_home_present(self) -> None:
        row = kb.nav_row(back="account:list:1")
        labels = [b.text for b in row]
        assert any("بازگشت" in t for t in labels)
        assert any("خانه" in t for t in labels)

    def test_important_pages_have_navigation(self) -> None:
        """بخش ۲۵: هر صفحهٔ مهم باید Back یا Home داشته باشد."""
        for markup in (
            kb.main_menu(),
            kb.account_add_menu(),
            kb.targets_menu(),
            kb.settings_menu(),
            kb.jobs_menu([], 1, 1),
        ):
            flat = [b.callback_data for row in markup.inline_keyboard for b in row]
            assert any(d and ("main:home" in d or ":menu" in d or ":list" in d) for d in flat)
