"""
کارخانهٔ Backend و گزارش قابلیت‌های واقعی.

این ماژول تنها نقطه‌ای است که UI برای گرفتن یک Backend به آن مراجعه می‌کند؛
بنابراین منطق Telegram هرگز مستقیماً به کتابخانه‌های ایتا وابسته نمی‌شود.
"""
from __future__ import annotations

import logging

from app.config import config
from app.db.database import Database
from app.db.models import AccountKind
from app.eitaa.base import Capability, EitaaBackend, EitaaError, EitaaUnavailable
from app.eitaa.eitaayar_backend import (
    EitaayarBackend,
    eitaapy_available,
    eitaapy_import_error,
)
from app.eitaa.bridge_backend import BRIDGE_HINT, BridgeBackend, BridgeClient
from app.eitaa.extractor import scraper_available, scraper_error
from app.eitaa.mtproto_backend import (
    INSTALL_HINT,
    MTProtoBackend,
    mtproto_available,
    mtproto_error,
)

log = logging.getLogger(__name__)


async def build_backend(db: Database, account_id: int) -> EitaaBackend:
    """
    ساخت Backend واقعی برای یک اکانت.
    راز فقط اینجا از دیتابیس خارج می‌شود و هرگز به UI نمی‌رسد.
    """
    account = await db.get_account(account_id)
    if account is None:
        raise EitaaError("اکانت پیدا نشد.")

    if account.kind is AccountKind.BOT_API:
        token = await db.get_account_secret(account_id)
        if not token:
            raise EitaaError("توکن این اکانت در دسترس نیست. دوباره اکانت را اضافه کنید.")
        return EitaayarBackend(token)

    if account.kind is AccountKind.BRIDGE:
        if not config.bridge_ready:
            raise EitaaUnavailable(BRIDGE_HINT)
        phone = await db.get_account_secret(account_id)
        if not phone:
            raise EitaaError("شمارهٔ این اکانت در دسترس نیست. دوباره وارد شوید.")
        return BridgeBackend(config.bridge_url, phone)

    if account.kind is AccountKind.MTPROTO:
        if not mtproto_available():
            raise EitaaUnavailable(INSTALL_HINT)
        session_name = await db.get_account_session_name(account_id)
        if not session_name:
            raise EitaaError("نام نشست این اکانت ثبت نشده است.")
        return MTProtoBackend(session_name, str(config.session_dir))

    raise EitaaError("نوع اکانت پشتیبانی نمی‌شود.")


def capability_report() -> list[tuple[str, Capability, str]]:
    """
    گزارش صادقانهٔ قابلیت‌ها برای صفحهٔ تنظیمات.
    خروجی: (عنوان، وضعیت، توضیح).
    """
    rows: list[tuple[str, Capability, str]] = []

    if eitaapy_available():
        rows.append(
            (
                "ارسال پیام و فایل (ایتایار)",
                Capability.AVAILABLE,
                "کتابخانهٔ eitaapy نصب است: get_me / send_message / send_file",
            )
        )
    else:
        rows.append(
            (
                "ارسال پیام و فایل (ایتایار)",
                Capability.UNAVAILABLE,
                f"eitaapy نصب نیست — {eitaapy_import_error()[:60]}",
            )
        )

    if scraper_available():
        rows.append(
            (
                "استخراج لینک از لینکدونی",
                Capability.AVAILABLE,
                "کتابخانهٔ eitaa نصب است: get_latest_messages / get_info",
            )
        )
    else:
        rows.append(
            (
                "استخراج لینک از لینکدونی",
                Capability.UNAVAILABLE,
                f"eitaa نصب نیست — {scraper_error()[:60]}",
            )
        )

    # نشست کاربری — دو مسیر ممکن: کتابخانهٔ pyeitaa یا سرویس پل EitaaBun
    if mtproto_available():
        rows.append(
            (
                "عضویت در گروه‌ها (Joiner)",
                Capability.AVAILABLE,
                "فریم‌ورک MTProto در دسترس است",
            )
        )
        rows.append(
            ("گروه‌ها / مخاطبین / چت خصوصی", Capability.AVAILABLE, "messages.GetDialogs")
        )
    elif config.bridge_ready:
        rows.append(
            (
                "عضویت در گروه‌ها (Joiner)",
                Capability.AVAILABLE,
                f"از طریق سرویس پل: {config.bridge_url}",
            )
        )
        rows.append(
            (
                "گروه‌ها / مخاطبین / چت خصوصی",
                Capability.AVAILABLE,
                "messages/dialogs از سرویس پل",
            )
        )
    else:
        reason = (mtproto_error() or "نصب نشده")[:70]
        rows.append(("عضویت در گروه‌ها (Joiner)", Capability.UNAVAILABLE, reason))
        rows.append(("گروه‌ها / مخاطبین / چت خصوصی", Capability.UNAVAILABLE, reason))

    rows.append(
        (
            "ورود با شمارهٔ تلفن",
            Capability.AVAILABLE if config.bridge_ready else Capability.UNAVAILABLE,
            f"سرویس پل: {config.bridge_url}"
            if config.bridge_ready
            else "EITAA_BRIDGE_URL تنظیم نشده است",
        )
    )

    rows.append(
        (
            "دستیار هوش مصنوعی",
            Capability.AVAILABLE if config.ai_ready else Capability.UNAVAILABLE,
            "پیکربندی شده" if config.ai_ready else "AI_API_KEY تنظیم نشده است",
        )
    )
    return rows
