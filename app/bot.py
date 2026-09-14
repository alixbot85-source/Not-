"""
نقطهٔ ورود ربات — اتصال همهٔ اجزا.

اجرا:  python -m app.bot     یا     python run.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramUnauthorizedError,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import config
from app.db.database import Database
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
from app.logging_setup import setup_logging
from app.middlewares import AuthMiddleware, ErrorMiddleware, RateLimitMiddleware
from app.services.jobs import JobManager

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="پنل اصلی"),
    BotCommand(command="cancel", description="لغو عملیات جاری"),
    BotCommand(command="help", description="راهنما"),
]


class DependencyMiddleware:
    """تزریق وابستگی‌ها (db و jobs) به تمام هندلرها."""

    def __init__(self, **deps: Any) -> None:
        self.deps = deps

    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        data.update(self.deps)
        return await handler(event, data)


def build_dispatcher(db: Database, job_manager: JobManager) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())

    injector = DependencyMiddleware(db=db, jobs=job_manager)
    for observer in (dispatcher.message, dispatcher.callback_query):
        observer.middleware(injector)
        observer.middleware(ErrorMiddleware())
        observer.middleware(AuthMiddleware())
        observer.middleware(RateLimitMiddleware())

    # ترتیب مهم است: common آخر ثبت می‌شود چون هندلر fallback دارد.
    for router in (
        accounts.router,
        linkdoni.router,
        joiner.router,
        sender.router,
        jobs_handlers.router,
        exports.router,
        ai.router,
        settings.router,
        common.router,
    ):
        dispatcher.include_router(router)
    return dispatcher


async def main() -> int:
    config.ensure_dirs()
    setup_logging(config.log_dir, config.log_level)

    errors = config.validate()
    if errors:
        for error in errors:
            log.error("پیکربندی ناقص: %s", error)
        print("\n❌ ربات اجرا نشد. موارد زیر را در فایل .env تنظیم کنید:\n")
        for error in errors:
            print(f"  • {error}")
        print("\nنمونه در فایل .env.example موجود است.\n")
        return 1

    db = Database(config.db_path)
    await db.connect()

    # درج لینکدونی‌های پیش‌فرض فقط در اولین اجرا
    if await db.count_linkdoni() == 0 and config.default_linkdoni:
        added = await db.seed_default_linkdoni(config.default_linkdoni)
        log.info("لینکدونی پیش‌فرض درج شد: %s مورد", added)

    job_manager = JobManager(db)
    recovered = await job_manager.recover_orphans()
    if recovered:
        log.warning("عملیات‌های بازیابی‌شده پس از راه‌اندازی مجدد: %s", recovered)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(db, job_manager)

    exit_code = 0
    try:
        # بررسی اتصال و اعتبار توکن پیش از شروع polling
        try:
            me = await bot.get_me()
            log.info("اتصال برقرار شد: @%s", me.username)
        except TelegramUnauthorizedError:
            log.error("توکن ربات پذیرفته نشد.")
            print(
                "\n❌ توکن ربات معتبر نیست.\n"
                "   مقدار BOT_TOKEN را در فایل .env بررسی کنید.\n"
            )
            return 1
        except TelegramNetworkError as exc:
            log.error("اتصال به سرور تلگرام برقرار نشد: %s", exc)
            print(
                "\n❌ ارتباط با سرور تلگرام برقرار نشد.\n"
                "   اتصال اینترنت یا دسترسی به api.telegram.org را بررسی کنید.\n"
                "   (در صورت نیاز از پراکسی استفاده کنید.)\n"
            )
            return 1

        try:
            await bot.set_my_commands(COMMANDS)
        except TelegramAPIError as exc:
            log.warning("ثبت دستورات ناموفق بود: %s", exc)

        log.info("ربات شروع شد. تعداد ادمین‌ها: %s", len(config.admin_ids))
        await dispatcher.start_polling(bot, allowed_updates=["message", "callback_query"])
    except (KeyboardInterrupt, SystemExit):
        log.info("سیگنال خاموشی دریافت شد.")
    except TelegramNetworkError as exc:
        log.error("ارتباط شبکه قطع شد: %s", exc)
        print("\n❌ ارتباط با سرور تلگرام قطع شد. ربات متوقف شد.\n")
        exit_code = 1
    finally:
        await job_manager.shutdown()
        await db.close()
        await bot.session.close()
        log.info("ربات متوقف شد.")
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
