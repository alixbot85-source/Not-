"""
تست جریان‌های واقعی کاربر از طریق Dispatcher.

به‌جای صدا زدن مستقیم هندلرها، Updateهای واقعی تلگرام ساخته و از کل زنجیرهٔ
Middleware ➜ Router ➜ Handler عبور داده می‌شوند. تماس‌های شبکه به Bot API
در لایهٔ Session شبیه‌سازی می‌شوند (سندباکس به api.telegram.org دسترسی ندارد)،
اما منطق پنل کاملاً واقعی اجرا می‌شود.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update, User

from app.db.database import Database
from app.db.models import AccountKind, JobType
from app.services.jobs import JobManager

pytestmark = pytest.mark.asyncio

ADMIN_ID = 1001
STRANGER_ID = 999_999


class FakeSession:
    """
    جایگزین لایهٔ شبکهٔ aiogram.
    هر فراخوانی API ثبت می‌شود و پاسخ معتبر برمی‌گرداند.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._message_id = 1000

    async def __call__(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None):
        name = type(method).__name__
        data = method.model_dump(exclude_none=True)
        self.calls.append((name, data))

        if name in {"SendMessage", "EditMessageText", "SendDocument"}:
            self._message_id += 1
            return Message(
                message_id=self._message_id,
                date=datetime.now(),
                chat=Chat(id=data.get("chat_id", ADMIN_ID), type="private"),
                text=data.get("text", data.get("caption", "")),
            )
        if name in {"AnswerCallbackQuery", "SetMyCommands", "DeleteMessage"}:
            return True
        return True

    async def close(self) -> None:
        return None

    def texts(self) -> list[str]:
        return [d.get("text", "") for _, d in self.calls if "text" in d]

    def last_text(self) -> str:
        texts = self.texts()
        return texts[-1] if texts else ""

    def last_markup(self) -> dict[str, Any]:
        """آخرین صفحه‌کلید اینلاین ارسال‌شده (به‌صورت dict خام)."""
        for name, data in reversed(self.calls):
            if name in {"SendMessage", "EditMessageText"} and "reply_markup" in data:
                return data["reply_markup"]
        return {}

    def buttons(self) -> list[str]:
        """callback_data تمام دکمه‌های آخرین صفحه‌کلید."""
        markup = self.last_markup()
        return [
            b.get("callback_data", "")
            for row in markup.get("inline_keyboard", [])
            for b in row
        ]

    def alerts(self) -> list[str]:
        return [
            d.get("text", "")
            for n, d in self.calls
            if n == "AnswerCallbackQuery" and d.get("text")
        ]

    def clear(self) -> None:
        self.calls.clear()


def _detach_routers() -> None:
    """
    routerهای aiogram در سطح ماژول ساخته می‌شوند و هرکدام فقط به یک Dispatcher
    می‌چسبند. برای اینکه هر تست بتواند Dispatcher تازه بسازد، اتصال قبلی آزاد
    می‌شود. در اجرای واقعی فقط یک Dispatcher وجود دارد و این کار لازم نیست.
    """
    from app.handlers import (
        accounts,
        ai,
        common,
        exports,
        jobs as jobs_handlers,
        joiner,
        linkdoni,
        sender,
        settings,
    )

    for module in (
        accounts, linkdoni, joiner, sender, jobs_handlers, exports, ai, settings, common,
    ):
        module.router._parent_router = None  # noqa: SLF001


@pytest.fixture()
async def harness(tmp_path):
    """محیط کامل: دیتابیس واقعی + Dispatcher واقعی + Session جعلی."""
    import app.config as config_module
    from app.bot import build_dispatcher

    _detach_routers()
    object.__setattr__(config_module.config, "admin_ids", frozenset({ADMIN_ID}))
    object.__setattr__(config_module.config, "data_dir", tmp_path)
    object.__setattr__(config_module.config, "rate_limit_events", 10_000)

    db = Database(tmp_path / "flow.db")
    await db.connect()
    manager = JobManager(db)
    dispatcher = build_dispatcher(db, manager)

    session = FakeSession()
    bot = Bot(
        token="123456:TEST_abcdefghijklmnopqrstuvwxyz12",
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,  # type: ignore[arg-type]
    )
    yield dispatcher, bot, db, session, manager
    await db.close()


def make_message(text: str, user_id: int = ADMIN_ID) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="تستر"),
            text=text,
        ),
    )


def make_callback(data: str, user_id: int = ADMIN_ID) -> Update:
    from aiogram.types import CallbackQuery

    return Update(
        update_id=2,
        callback_query=CallbackQuery(
            id="cb1",
            from_user=User(id=user_id, is_bot=False, first_name="تستر"),
            chat_instance="ci",
            data=data,
            message=Message(
                message_id=500,
                date=datetime.now(),
                chat=Chat(id=user_id, type="private"),
                text="قبلی",
            ),
        ),
    )


async def feed(dispatcher: Dispatcher, bot: Bot, update: Update) -> None:
    await dispatcher.feed_update(bot, update)


# ══════════════════════════════════════════════════════════════════
class TestAuthorization:
    async def test_stranger_is_blocked(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_message("/start", user_id=STRANGER_ID))
        assert "دسترسی مجاز نیست" in session.last_text()

    async def test_stranger_callback_blocked(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("account:list:1", user_id=STRANGER_ID))
        assert any("دسترسی" in a for a in session.alerts())

    async def test_admin_allowed(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_message("/start"))
        assert "پنل اصلی" in session.last_text()


class TestStartAndNavigation:
    async def test_start_shows_main_panel(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_message("/start"))
        text = session.last_text()
        assert "پنل اصلی" in text
        send = [d for n, d in session.calls if n == "SendMessage"][-1]
        buttons = [
            b["text"] for row in send["reply_markup"]["inline_keyboard"] for b in row
        ]
        assert any("اکانت" in b for b in buttons)
        assert any("Joiner" in b for b in buttons)
        assert any("Sender" in b for b in buttons)

    async def test_home_button_returns(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("main:home"))
        assert "پنل اصلی" in session.last_text()

    async def test_help_and_cancel(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_message("/help"))
        assert "راهنما" in session.last_text()
        session.clear()
        await feed(dispatcher, bot, make_message("/cancel"))
        assert "لغو" in " ".join(session.texts())

    async def test_invalid_callback_rejected(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("garbage"))
        assert any("نامعتبر" in a for a in session.alerts())


class TestEmptyStates:
    async def test_accounts_empty_state(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("account:list:1"))
        text = session.last_text()
        assert "📭" in text and "اکانتی اضافه نشده" in text

    async def test_jobs_empty_state(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("job:list:1"))
        assert "📭" in session.last_text()

    async def test_linkdoni_empty_state(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("linkdoni:list:1"))
        assert "📭" in session.last_text()


class TestAccountFlow:
    async def test_add_token_flow_rejects_bad_format(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        await feed(dispatcher, bot, make_callback("account:addtok"))
        session.clear()
        await feed(dispatcher, bot, make_message("not-a-valid-token"))
        assert "معتبر نیست" in session.last_text()
        assert await db.count_accounts() == 0

    async def test_full_add_flow_stores_encrypted(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        await feed(dispatcher, bot, make_callback("account:addtok"))
        await feed(
            dispatcher, bot, make_message("bot12345:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        )
        session.clear()
        await feed(dispatcher, bot, make_message("کانال تست"))

        assert await db.count_accounts() == 1
        account = (await db.list_accounts())[0]
        assert account.label == "کانال تست"
        assert account.kind is AccountKind.BOT_API
        # راز هرگز در متن پنل ظاهر نمی‌شود
        assert "aaaaaaaa-bbbb" not in " ".join(session.texts())

    async def test_view_and_delete_with_confirmation(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        account_id = await db.add_account("حذفی", AccountKind.BOT_API, secret="bot1:x")

        await feed(dispatcher, bot, make_callback(f"account:view:{account_id}"))
        assert "حذفی" in session.last_text()

        session.clear()
        await feed(dispatcher, bot, make_callback(f"account:delask:{account_id}"))
        assert "تأیید" in session.last_text()      # عملیات خطرناک تأیید دارد
        assert await db.count_accounts() == 1

        await feed(dispatcher, bot, make_callback(f"account:del:{account_id}"))
        assert await db.count_accounts() == 0

    async def test_pagination_renders(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        for i in range(20):
            await db.add_account(f"acc{i}", AccountKind.BOT_API, secret="bot1:x")
        await feed(dispatcher, bot, make_callback("account:list:2"))
        edit = [d for n, d in session.calls if n == "EditMessageText"][-1]
        buttons = [
            b["text"] for row in edit["reply_markup"]["inline_keyboard"] for b in row
        ]
        assert any("/" in b for b in buttons)      # شمارندهٔ صفحه


class TestLinkdoniFlow:
    async def test_add_dedup_and_invalid(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        await feed(dispatcher, bot, make_callback("linkdoni:add"))
        session.clear()
        await feed(
            dispatcher,
            bot,
            make_message(
                "https://eitaa.com/one\n"
                "https://eitaa.com/one\n"        # تکراری
                "https://t.me/notallowed\n"      # نامعتبر
                "@two"
            ),
        )
        assert await db.count_linkdoni() == 2
        text = session.last_text()
        assert "تکراری" in text and "نامعتبر" in text

    async def test_select_all_and_clear(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        for i in range(3):
            await db.add_linkdoni(f"https://eitaa.com/c{i}")
        await feed(dispatcher, bot, make_callback("linkdoni:all:1"))
        assert await db.count_linkdoni(only_selected=True) == 3
        await feed(dispatcher, bot, make_callback("linkdoni:none:1"))
        assert await db.count_linkdoni(only_selected=True) == 0

    async def test_toggle_single(self, harness) -> None:
        dispatcher, bot, db, _, _ = harness
        item_id = await db.add_linkdoni("https://eitaa.com/x")
        await feed(dispatcher, bot, make_callback(f"linkdoni:tgl:{item_id}:1"))
        assert await db.count_linkdoni(only_selected=True) == 1


class TestJoinerGuards:
    async def test_requires_account_first(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("joiner:extract"))
        assert any("اکانت" in a for a in session.alerts())

    async def test_warns_bot_account_cannot_join(self, harness) -> None:
        """اکانت توکنی نمی‌تواند join کند — باید صادقانه هشدار دهد، نه تظاهر."""
        dispatcher, bot, db, session, _ = harness
        account_id = await db.add_account("توکنی", AccountKind.BOT_API, secret="bot1:x")
        await feed(dispatcher, bot, make_callback(f"joiner:pick:{account_id}"))

        # هشدار هم در متن صفحه و هم به‌صورت alert نمایش داده می‌شود
        assert "امکان عضویت در گروه ندارد" in " ".join(session.texts())
        assert any("امکان عضویت" in a for a in session.alerts())


class TestSenderFlow:
    async def test_compose_and_preview(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        account_id = await db.add_account("ارسالی", AccountKind.BOT_API, secret="bot1:x")

        await feed(dispatcher, bot, make_callback(f"sender:pick:{account_id}"))
        await feed(dispatcher, bot, make_callback("sender:edit"))
        await feed(dispatcher, bot, make_message("<b>سلام</b> دنیا"))
        await feed(dispatcher, bot, make_callback("sender:target:MANUAL"))
        await feed(dispatcher, bot, make_message("@alpha\n@beta"))

        session.clear()
        await feed(dispatcher, bot, make_callback("sender:preview"))
        text = session.last_text()
        assert "پیش‌نمایش" in text
        assert "<b>سلام</b>" in text        # قالب‌بندی واقعی حفظ شده
        assert "2" in text                  # تعداد مقصدها

    async def test_preview_blocked_when_incomplete(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("sender:preview"))
        assert any("کامل نیست" in a for a in session.alerts())

    async def test_manual_targets_rejects_garbage(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        account_id = await db.add_account("a", AccountKind.BOT_API, secret="bot1:x")
        await feed(dispatcher, bot, make_callback(f"sender:pick:{account_id}"))
        await feed(dispatcher, bot, make_callback("sender:target:MANUAL"))
        session.clear()
        await feed(dispatcher, bot, make_message("   \n  "))
        assert "معتبر" in session.last_text()

    async def test_stats_page(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("sender:stats"))
        assert "آمار ارسال" in session.last_text()

    async def test_invalid_html_rejected_without_probe_message(self, harness) -> None:
        """قالب‌بندی نادرست باید محلی رد شود — نه با ارسال پیام آزمایشی."""
        dispatcher, bot, db, session, _ = harness
        account_id = await db.add_account("a", AccountKind.BOT_API, secret="bot1:x")
        await feed(dispatcher, bot, make_callback(f"sender:pick:{account_id}"))
        await feed(dispatcher, bot, make_callback("sender:edit"))
        session.clear()
        await feed(dispatcher, bot, make_message("<marquee>بد</marquee>"))

        assert "معتبر نیست" in session.last_text()
        # هیچ پیام آزمایشی ارسال و حذف نشده است
        assert not any(name == "DeleteMessage" for name, _ in session.calls)

    async def test_media_button_offered_and_cleared(self, harness) -> None:
        """پیوست فقط برای اکانتی که واقعاً فایل می‌فرستد پیشنهاد می‌شود."""
        dispatcher, bot, db, session, _ = harness
        account_id = await db.add_account("a", AccountKind.BOT_API, secret="bot1:x")
        await feed(dispatcher, bot, make_callback(f"sender:pick:{account_id}"))
        session.clear()
        await feed(dispatcher, bot, make_callback("sender:compose"))

        assert "پیوست" in session.last_text()
        assert any(cb.startswith("sender:media") for cb in session.buttons())

    async def test_media_rejected_for_account_without_capability(self, harness) -> None:
        """اکانت MTProto بدون کتابخانه نباید وانمود کند فایل می‌فرستد."""
        dispatcher, bot, db, session, _ = harness
        account_id = await db.add_account("mt", AccountKind.MTPROTO, secret="")
        await feed(dispatcher, bot, make_callback(f"sender:pick:{account_id}"))
        session.clear()
        await feed(dispatcher, bot, make_callback("sender:media:add"))
        assert session.alerts(), "باید هشدار صادقانه بدهد"


class TestJobsAndExport:
    async def test_job_detail_and_logs(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        from app.db.models import LogLevel

        job_id = await db.create_job(JobType.JOINER, None)
        await db.set_job_total(job_id, 5)
        await db.add_log(job_id, LogLevel.INFO, "شروع شد")

        await feed(dispatcher, bot, make_callback(f"job:view:{job_id}"))
        assert f"JOB #{job_id}" in session.last_text()

        session.clear()
        await feed(dispatcher, bot, make_callback(f"job:logs:1:{job_id}"))
        assert "شروع شد" in session.last_text()

    async def test_export_empty_job(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        job_id = await db.create_job(JobType.JOINER, None)
        await feed(dispatcher, bot, make_callback(f"export:do:{job_id}:csv"))
        assert "داده‌ای برای خروجی" in session.last_text()

    async def test_export_produces_document(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        job_id = await db.create_job(JobType.JOINER, None)
        await db.add_job_items(job_id, [("https://eitaa.com/g1", "گروه یک")])

        await feed(dispatcher, bot, make_callback(f"export:do:{job_id}:csv"))
        documents = [d for n, d in session.calls if n == "SendDocument"]
        assert documents, "فایل خروجی ارسال نشد"
        assert documents[0]["document"].filename.endswith(".csv")

    async def test_stop_unknown_job(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("job:stop:4242"))
        assert any("اجرا نیست" in a for a in session.alerts())


class TestSettings:
    async def test_capability_report_is_shown(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("settings:caps"))
        text = session.last_text()
        assert "وضعیت قابلیت‌ها" in text
        assert "ارسال پیام و فایل" in text

    async def test_limits_page(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("settings:limits"))
        assert "تأخیر" in session.last_text()

    async def test_audit_page(self, harness) -> None:
        dispatcher, bot, db, session, _ = harness
        await db.audit(ADMIN_ID, "test_action", "detail")
        await feed(dispatcher, bot, make_callback("settings:audit:1"))
        assert "گزارش دسترسی" in session.last_text()


class TestAiGuard:
    async def test_disabled_ai_reports_honestly(self, harness) -> None:
        dispatcher, bot, _, session, _ = harness
        await feed(dispatcher, bot, make_callback("ai:menu"))
        text = session.last_text()
        assert "پیکربندی نشده" in text or "در دسترس نیست" in text


class TestNoSecretLeak:
    async def test_no_token_appears_in_any_response(self, harness) -> None:
        """بررسی سراسری: هیچ رازی نباید در خروجی پنل دیده شود."""
        dispatcher, bot, db, session, _ = harness
        secret = "bot55555:ffffffff-1111-2222-3333-444444444444"
        account_id = await db.add_account("محرمانه", AccountKind.BOT_API, secret=secret)

        for data in (
            "account:list:1",
            f"account:view:{account_id}",
            "settings:caps",
            "main:home",
        ):
            await feed(dispatcher, bot, make_callback(data))

        blob = " ".join(session.texts())
        assert secret not in blob
        assert "ffffffff-1111" not in blob
