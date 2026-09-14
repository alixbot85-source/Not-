"""تنظیمات، وضعیت قابلیت‌ها و گزارش دسترسی (بخش ۲۵ و ۲۸)."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from app.config import config
from app.db.database import Database
from app.eitaa.service import capability_report
from app.handlers.common import page_slice, safe_edit
from app.services.exporter import (
    available_formats,
    pdf_available,
    pdf_unavailable_reason,
)
from app.ui import keyboards as kb
from app.ui.callbacks import NS_SETTINGS, pack, parse
from app.ui.texts import esc

log = logging.getLogger(__name__)
router = Router(name="settings")

AUDIT_PER_PAGE = 10


@router.callback_query(F.data == f"{NS_SETTINGS}:menu")
async def cb_menu(query: CallbackQuery) -> None:
    await safe_edit(
        query,
        "⚙️ <b>تنظیمات</b>\n"
        "━━━━━━━━━━━━━━\n"
        "پیکربندی از فایل <code>.env</code> خوانده می‌شود.\n\n"
        "<blockquote>مقادیر حساس مثل توکن‌ها هرگز در این صفحه نمایش "
        "داده نمی‌شوند.</blockquote>",
        kb.settings_menu(),
    )
    await query.answer()


@router.callback_query(F.data == f"{NS_SETTINGS}:caps")
async def cb_capabilities(query: CallbackQuery) -> None:
    """گزارش صادقانهٔ وضعیت واقعی قابلیت‌ها."""
    lines = ["🧩 <b>وضعیت قابلیت‌ها</b>", "━━━━━━━━━━━━━━", ""]
    for title, capability, detail in capability_report():
        lines.append(f"{capability.label} <b>{esc(title)}</b>")
        lines.append(f"<i>{esc(detail)}</i>\n")

    formats = "، ".join(f.upper() for f in available_formats())
    lines.append(f"📄 <b>قالب‌های خروجی:</b> {formats}")
    if not pdf_available():
        lines.append(f"<i>PDF: {esc(pdf_unavailable_reason())}</i>")

    lines.append(
        "\n<blockquote expandable>این گزارش از بررسی واقعی کتابخانه‌های نصب‌شده "
        "ساخته می‌شود، نه از فرض. قابلیتی که در دسترس نباشد شبیه‌سازی نمی‌شود.</blockquote>"
    )
    await safe_edit(query, "\n".join(lines), kb.back_only(pack(NS_SETTINGS, "menu")))
    await query.answer()


@router.callback_query(F.data == f"{NS_SETTINGS}:limits")
async def cb_limits(query: CallbackQuery) -> None:
    await safe_edit(
        query,
        "⏱ <b>تأخیرها و محدودیت‌ها</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"تأخیر بین عضویت‌ها: <b>{config.join_delay}</b> ثانیه\n"
        f"تأخیر بین ارسال‌ها: <b>{config.send_delay}</b> ثانیه\n"
        f"حداکثر تلاش مجدد: <b>{config.max_retries}</b>\n"
        f"ضریب backoff: <b>{config.retry_backoff}</b>\n"
        f"فاصلهٔ به‌روزرسانی پیشرفت: <b>{config.progress_edit_interval}</b> ثانیه\n"
        f"اندازهٔ صفحه: <b>{config.page_size}</b>\n\n"
        f"محدودیت نرخ پنل: <b>{config.rate_limit_events}</b> درخواست "
        f"در <b>{config.rate_limit_window}</b> ثانیه\n\n"
        "<blockquote>برای تغییر، مقادیر را در فایل <code>.env</code> "
        "ویرایش کرده و ربات را دوباره اجرا کنید.</blockquote>",
        kb.back_only(pack(NS_SETTINGS, "menu")),
    )
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_SETTINGS}:audit"))
async def cb_audit(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    page = int(cb.arg) if cb.arg.isdigit() else 1
    total = await db.count_audit()
    pages = kb.page_count(total, AUDIT_PER_PAGE)
    page = max(1, min(page, pages))
    entries = await db.list_audit(AUDIT_PER_PAGE, page_slice(page, AUDIT_PER_PAGE))

    if not entries:
        body = "📭 هنوز رویدادی ثبت نشده است."
    else:
        rows = "\n".join(
            f"{e['created_at'][11:19]} • {esc(e['action'])} {esc(e['detail'])}" for e in entries
        )
        body = f"<blockquote expandable>{rows}</blockquote>\nصفحهٔ {page}/{pages}"

    rows_kb = []
    pagination = kb.pagination_row(NS_SETTINGS, "audit", page, pages)
    if pagination:
        rows_kb.append(pagination)
    rows_kb.append(kb.nav_row(back=pack(NS_SETTINGS, "menu")))

    await safe_edit(
        query,
        "🛡 <b>گزارش دسترسی</b>\n━━━━━━━━━━━━━━\n" + body,
        InlineKeyboardMarkup(inline_keyboard=rows_kb),
    )
    await query.answer()
