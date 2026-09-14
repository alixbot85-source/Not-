"""
استخراج لینک از لینکدونی‌ها (بخش ششم، مرحلهٔ ۲).

منبع واقعی: کتابخانهٔ «eitaa» 2.3.1 (EitaaPyKit) که صفحات عمومی eitaa.com را
واقعاً می‌خواند. متدهای تأییدشده با inspect:

    Eitaa.get_latest_messages(channel_id) -> list[dict]   (کلید 'text')
    Eitaa.get_info(channel_or_user_id)    -> dict         (کلید 'is_channel')

طبقه‌بندی نوع لینک:
  • لینک دعوت (`/joinchat/…` یا `/+…`) → INVITE  (قابل تشخیص از روی ساختار، قطعی)
  • مسیرهای رزروشدهٔ ایتا               → UNKNOWN (کنار گذاشته می‌شود)
  • سایر موارد                          → UNKNOWN تا زمانی که یک منبع واقعی
    (MTProto ResolveUsername یا get_info) نوع را قطعی کند.

طبق بخش ۶: «اگر تشخیص قطعی نوع لینک ممکن نیست، Unknown ثبت شود. حدس نزن.»
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

from app.db.models import LinkKind
from app.security import normalize_eitaa_url, redact

log = logging.getLogger(__name__)

try:
    from eitaa import Eitaa as _Eitaa

    _EITAA_READY = True
    _EITAA_ERROR = ""
except Exception as exc:  # noqa: BLE001
    _Eitaa = None  # type: ignore[assignment]
    _EITAA_READY = False
    _EITAA_ERROR = str(exc)


def scraper_available() -> bool:
    return _EITAA_READY


def scraper_error() -> str:
    return _EITAA_ERROR


# مسیرهایی که گروه/کانال نیستند
RESERVED = {
    "s", "joinchat", "addstickers", "share", "about", "faq", "apps", "download",
    "privacy", "terms", "support", "blog", "login", "api", "img", "css", "js",
}

_LINK_RE = re.compile(r"(?:https?://)?(?:www\.)?eitaa\.(?:com|ir)/[A-Za-z0-9_+/\-]{2,}", re.I)


@dataclass(slots=True)
class ExtractionStats:
    """آمار واقعی مرحلهٔ استخراج — برای گزارش بخش ۶ مرحلهٔ ۳."""

    checked: int = 0
    found: int = 0
    duplicates: int = 0
    invalid: int = 0
    by_kind: dict[LinkKind, int] = field(default_factory=dict)

    @property
    def joinable(self) -> int:
        """فقط مواردی که واقعاً قابل تلاش برای Join هستند."""
        return self.by_kind.get(LinkKind.GROUP, 0) + self.by_kind.get(LinkKind.INVITE, 0)


def classify(url: str) -> LinkKind:
    """طبقه‌بندی بر اساس ساختار قطعی لینک. هرچه قطعی نباشد UNKNOWN است."""
    lowered = url.lower()
    if "/joinchat/" in lowered or "/+" in lowered:
        return LinkKind.INVITE
    path = url.split("eitaa.com/", 1)[-1].strip("/")
    if not path or "/" in path or path.lower() in RESERVED:
        return LinkKind.UNKNOWN
    return LinkKind.UNKNOWN  # بدون منبع واقعی، نوع قطعی نیست


def find_links(text: str) -> list[str]:
    """یافتن و نرمال‌سازی لینک‌های ایتا در یک متن."""
    out: list[str] = []
    for match in _LINK_RE.findall(text or ""):
        normalized = normalize_eitaa_url(match)
        if normalized:
            out.append(normalized)
    return out


class LinkExtractor:
    """استخراج‌کنندهٔ واقعی (I/O مسدودکننده در thread جدا اجرا می‌شود)."""

    def __init__(self) -> None:
        self._enabled = _EITAA_READY

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _channel_id(url: str) -> str:
        return url.split("eitaa.com/", 1)[-1].strip("/").split("/")[0]

    async def fetch_links(self, linkdoni_url: str) -> tuple[list[str], str]:
        """
        پیام‌های عمومی یک لینکدونی را می‌خواند و لینک‌های داخلشان را برمی‌گرداند.
        خروجی: (لینک‌ها، پیام خطا). خطا خالی یعنی موفق.
        """
        if not self._enabled:
            return [], "کتابخانهٔ eitaa نصب نیست."

        channel = self._channel_id(linkdoni_url)
        if not channel or channel.lower() in RESERVED:
            return [], "آدرس لینکدونی معتبر نیست."

        try:
            messages = await asyncio.to_thread(_Eitaa.get_latest_messages, channel)
        except Exception as exc:  # noqa: BLE001
            log.info("extract failed for %s: %s", channel, redact(exc))
            return [], "دسترسی به این لینکدونی ممکن نشد."

        links: list[str] = []
        for message in messages or []:
            if isinstance(message, dict):
                links.extend(find_links(str(message.get("text", ""))))
        return links, ""

    async def verify_kind(self, url: str) -> LinkKind:
        """
        تلاش برای تشخیص قطعی نوع با get_info واقعی.
        فقط «کانال» از طریق کلید is_channel قطعی است؛ بقیه UNKNOWN می‌مانند.
        """
        if not self._enabled:
            return LinkKind.UNKNOWN
        try:
            info = await asyncio.to_thread(_Eitaa.get_info, self._channel_id(url))
        except Exception:  # noqa: BLE001
            return LinkKind.UNKNOWN
        if isinstance(info, dict) and "is_channel" in info:
            return LinkKind.CHANNEL if info["is_channel"] else LinkKind.USER
        return LinkKind.UNKNOWN


def deduplicate(urls: list[str]) -> tuple[list[str], int]:
    """حذف تکراری‌ها با حفظ ترتیب. خروجی: (یکتاها، تعداد تکراری)."""
    seen: set[str] = set()
    unique: list[str] = []
    duplicates = 0
    for url in urls:
        key = url.lower().rstrip("/")
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(url)
    return unique, duplicates
