"""
Middlewareهای امنیتی (بخش ۲۸).

  • AuthMiddleware      — فقط ادمین‌های تعریف‌شده اجازهٔ استفاده دارند.
  • RateLimitMiddleware — محدودسازی نرخ درخواست هر کاربر.
  • ErrorMiddleware     — هیچ Traceback خامی به کاربر نمی‌رسد (بخش ۲۷).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import config
from app.security import RateLimiter, redact
from app.ui.texts import error_view

log = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]

DENIED = (
    "⛔️ <b>دسترسی مجاز نیست</b>\n"
    "━━━━━━━━━━━━━━\n"
    "این پنل خصوصی است و فقط برای مدیران تعریف‌شده کار می‌کند."
)


def _user_id(event: TelegramObject) -> int | None:
    user = getattr(event, "from_user", None)
    return user.id if user is not None else None


class AuthMiddleware(BaseMiddleware):
    """Authorization — هم برای پیام‌ها هم برای callbackها."""

    async def __call__(
        self, handler: Handler, event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        user_id = _user_id(event)
        if not config.is_admin(user_id):
            log.warning("دسترسی رد شد برای کاربر %s", user_id)
            if isinstance(event, CallbackQuery):
                await event.answer("دسترسی مجاز نیست", show_alert=True)
            elif isinstance(event, Message):
                await event.answer(DENIED)
            return None

        db = data.get("db")
        if db is not None and isinstance(event, Message):
            user = getattr(event, "from_user", None)
            if user is not None:
                await db.upsert_user(user.id, user.username or "", True)
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Rate limit + Flood handling."""

    def __init__(self) -> None:
        self.limiter = RateLimiter(config.rate_limit_events, config.rate_limit_window)

    async def __call__(
        self, handler: Handler, event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        user_id = _user_id(event)
        if user_id is not None and not self.limiter.allow(user_id):
            wait = int(self.limiter.retry_after(user_id)) + 1
            if isinstance(event, CallbackQuery):
                await event.answer(f"کمی آرام‌تر! {wait} ثانیه صبر کنید.", show_alert=False)
            elif isinstance(event, Message):
                await event.answer(f"⏳ تعداد درخواست‌ها زیاد است. {wait} ثانیه صبر کنید.")
            return None
        return await handler(event, data)


class ErrorMiddleware(BaseMiddleware):
    """
    Error Handling سراسری — کاربر پیام قابل‌فهم می‌بیند،
    جزئیات فنی فقط در لاگ ثبت می‌شود.
    """

    async def __call__(
        self, handler: Handler, event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:  # noqa: BLE001
            log.exception("خطای پردازش‌نشده در هندلر")
            text = error_view(
                "خطای غیرمنتظره‌ای رخ داد.",
                "این مورد در فایل لاگ ثبت شد. لطفاً دوباره تلاش کنید.",
            )
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer("خطا رخ داد", show_alert=True)
                    if event.message is not None:
                        await event.message.answer(text)
                elif isinstance(event, Message):
                    await event.answer(text)
            except Exception:  # noqa: BLE001
                log.error("ارسال پیام خطا هم ناموفق بود: %s", redact(exc))
            return None
