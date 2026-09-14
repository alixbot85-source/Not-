"""
لایهٔ AI (بخش ۳۲ و ۳۳) — EXTERNAL SERVICE REQUIRED.

این سرویس یک کلاینت واقعی برای APIهای سازگار با OpenAI Chat Completions است.
اگر کلید تنظیم نشده باشد، منو با وضعیت «پیکربندی نشده» نمایش داده می‌شود و
هیچ خروجی ساختگی تولید نمی‌شود.

محدودیت امنیتی (طبق صورت مسئله): AI فقط روی «متن پیش‌نویس» کار می‌کند و
هرگز به اکانت، Job یا عملیات حساس دسترسی ندارد.
"""
from __future__ import annotations

import json
import logging
from typing import Final

import aiohttp

from app.config import config
from app.security import redact

log = logging.getLogger(__name__)

TIMEOUT: Final = aiohttp.ClientTimeout(total=60)

ACTIONS: Final[dict[str, str]] = {
    "rewrite": "متن زیر را بازنویسی کن و روان‌تر کن. فقط متن نهایی را بده.",
    "shorten": "متن زیر را کوتاه‌تر کن بدون از دست دادن پیام اصلی. فقط متن نهایی را بده.",
    "expand": "متن زیر را با جزئیات بیشتر گسترش بده. فقط متن نهایی را بده.",
    "summarize": "متن زیر را خلاصه کن. فقط خلاصه را بده.",
    "translate": "متن زیر را به انگلیسی روان ترجمه کن. فقط ترجمه را بده.",
    "grammar": "غلط‌های نگارشی و دستوری متن زیر را اصلاح کن. فقط متن اصلاح‌شده را بده.",
    "title": "برای متن زیر یک عنوان کوتاه و جذاب بنویس. فقط عنوان را بده.",
    "caption": "برای متن زیر یک کپشن کوتاه بنویس. فقط کپشن را بده.",
}

STYLES: Final[dict[str, str]] = {
    "professional": "لحن حرفه‌ای و کاری",
    "friendly": "لحن دوستانه و صمیمی",
    "formal": "لحن رسمی و اداری",
    "marketing": "لحن تبلیغاتی و ترغیب‌کننده",
    "news": "لحن خبری و بی‌طرف",
    "technical": "لحن فنی و دقیق",
    "persian": "فارسی روان و بدون کلمات بیگانه",
    "english": "انگلیسی روان",
}


class AIError(Exception):
    """خطای قابل‌نمایش لایهٔ AI."""


class AIService:
    """کلاینت واقعی Chat Completions (سازگار با OpenAI API)."""

    def __init__(self) -> None:
        self.enabled = config.ai_ready

    @staticmethod
    def _prompt(action: str, style: str | None) -> str:
        instruction = ACTIONS.get(action)
        if instruction is None:
            raise AIError("این عملیات پشتیبانی نمی‌شود.")
        if style:
            tone = STYLES.get(style)
            if tone is None:
                raise AIError("این سبک پشتیبانی نمی‌شود.")
            instruction += f" خروجی با {tone} باشد."
        return instruction

    async def transform(self, text: str, action: str, style: str | None = None) -> str:
        """اجرای واقعی درخواست AI. در صورت نبود کلید، خطای صریح می‌دهد."""
        if not self.enabled:
            raise AIError(
                "سرویس هوش مصنوعی پیکربندی نشده است.\n"
                "برای فعال‌سازی، AI_ENABLED=true و AI_API_KEY را در فایل .env تنظیم کنید."
            )
        if not text.strip():
            raise AIError("متنی برای پردازش وجود ندارد.")

        payload = {
            "model": config.ai_model,
            "messages": [
                {"role": "system", "content": self._prompt(action, style)},
                {"role": "user", "content": text[:4000]},
            ],
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {config.ai_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{config.ai_base_url}/chat/completions"

        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    body = await response.text()
                    if response.status != 200:
                        log.error("AI HTTP %s: %s", response.status, redact(body)[:200])
                        raise AIError(f"سرویس هوش مصنوعی پاسخ نداد (کد {response.status}).")
                    data = json.loads(body)
        except AIError:
            raise
        except aiohttp.ClientError as exc:
            log.error("AI network error: %s", redact(exc))
            raise AIError("ارتباط با سرویس هوش مصنوعی برقرار نشد.") from exc
        except json.JSONDecodeError as exc:
            raise AIError("پاسخ سرویس هوش مصنوعی قابل خواندن نبود.") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("پاسخ سرویس هوش مصنوعی ساختار مورد انتظار را نداشت.") from exc

        result = str(content).strip()
        if not result:
            raise AIError("سرویس هوش مصنوعی خروجی خالی برگرداند.")
        return result[:4000]


ai_service = AIService()
