"""
گزارش زندهٔ پیشرفت با Edit Message (بخش هفتم).

به‌جای ارسال صدها پیام، یک پیام ویرایش می‌شود.
محدودیت‌های واقعی Bot API که رعایت شده‌اند:
  • ویرایش با همان متن ⇒ خطای «message is not modified» → نادیده گرفته می‌شود.
  • نرخ ویرایش محدود است ⇒ حداقل فاصله بین ویرایش‌ها اعمال می‌شود.
  • خطای 429 ⇒ TelegramRetryAfter واقعی گرفته و رعایت می‌شود.
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from app.security import redact

log = logging.getLogger(__name__)


class ProgressReporter:
    """ویرایشگر پیام پیشرفت با throttle واقعی."""

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        message_id: int,
        min_interval: float = 3.0,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.min_interval = max(0.5, min_interval)
        self._last_edit = 0.0
        self._last_text = ""
        self._lock = asyncio.Lock()

    async def update(
        self,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
        *,
        force: bool = False,
    ) -> bool:
        """
        ویرایش پیام در صورت مجاز بودن.
        خروجی True یعنی واقعاً ویرایش شد.
        """
        async with self._lock:
            now = time.monotonic()
            if not force and now - self._last_edit < self.min_interval:
                return False
            if text == self._last_text and not force:
                return False

            try:
                await self.bot.edit_message_text(
                    text=text,
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    reply_markup=markup,
                )
                self._last_edit = time.monotonic()
                self._last_text = text
                return True
            except TelegramRetryAfter as exc:
                log.warning("progress flood, retry after %ss", exc.retry_after)
                self._last_edit = time.monotonic() + exc.retry_after
                return False
            except TelegramBadRequest as exc:
                message = str(exc).lower()
                if "message is not modified" in message:
                    self._last_text = text
                    return False
                if "message to edit not found" in message:
                    log.info("progress message gone; stop editing")
                    return False
                log.warning("progress edit failed: %s", redact(exc))
                return False
            except Exception as exc:  # noqa: BLE001
                log.warning("progress edit error: %s", redact(exc))
                return False

    async def finish(self, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        """ویرایش نهایی — همیشه اعمال می‌شود."""
        await self.update(text, markup, force=True)
