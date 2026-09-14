"""خروجی‌گیری (بخش ۲۱)."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from app.db.database import Database
from app.db.models import JobType
from app.handlers.common import safe_edit
from app.services.exporter import (
    ExportPayload,
    available_formats,
    pdf_available,
    pdf_unavailable_reason,
    render,
)
from app.ui import keyboards as kb
from app.ui.callbacks import NS_EXPORT, NS_JOB, pack, parse
from app.ui.texts import error_view, loading_view

log = logging.getLogger(__name__)
router = Router(name="exports")

MAX_ROWS = 20_000


@router.callback_query(F.data.startswith(f"{NS_EXPORT}:menu:"))
async def cb_menu(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    job_id = cb.int_arg
    job = await db.get_job(job_id)
    if job is None:
        await query.answer("عملیات پیدا نشد.", show_alert=True)
        return
    formats = "، ".join(f.upper() for f in available_formats())
    text = (
        f"📄 <b>خروجی عملیات #{job_id}</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"قالب‌های در دسترس: <b>{formats}</b>\n\n"
        "<blockquote>خروجی‌ها با کدگذاری UTF-8 ساخته می‌شوند. "
        "فایل CSV دارای BOM است تا در Excel فارسی درست باز شود.</blockquote>"
    )
    if not pdf_available():
        text += f"\n\n⚠️ <i>PDF در دسترس نیست: {pdf_unavailable_reason()}</i>"
    await safe_edit(query, text, kb.export_menu(job_id, pdf_available()))
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_EXPORT}:nopdf:"))
async def cb_no_pdf(query: CallbackQuery) -> None:
    await query.answer(pdf_unavailable_reason()[:190], show_alert=True)


@router.callback_query(F.data.startswith(f"{NS_EXPORT}:do:"))
async def cb_export(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    job_id = cb.int_arg
    fmt = cb.arg2.lower()

    job = await db.get_job(job_id)
    if job is None:
        await query.answer("عملیات پیدا نشد.", show_alert=True)
        return
    if fmt not in available_formats():
        await query.answer("این قالب در دسترس نیست.", show_alert=True)
        return

    await safe_edit(query, loading_view("در حال ساخت فایل خروجی..."))

    # دادهٔ واقعی: برای استخراج از جدول لینک‌ها، برای بقیه از آیتم‌ها
    if job.type is JobType.EXTRACT:
        links = await db.list_links(job_id, limit=MAX_ROWS)
        headers = ["ردیف", "لینک", "نوع", "منبع"]
        rows = [[str(i), l.url, l.kind.label, l.source] for i, l in enumerate(links, 1)]
    else:
        items = await db.list_job_items(job_id, limit=MAX_ROWS)
        headers = ["ردیف", "مقصد", "عنوان", "وضعیت", "توضیح"]
        rows = [
            [str(i), it.ref, it.title, it.status.label, it.reason]
            for i, it in enumerate(items, 1)
        ]

    if not rows:
        await safe_edit(
            query,
            "📭 <b>داده‌ای برای خروجی وجود ندارد</b>\n━━━━━━━━━━━━━━\n"
            "این عملیات هنوز نتیجه‌ای ثبت نکرده است.",
            kb.back_only(pack(NS_JOB, "view", job_id)),
        )
        await query.answer()
        return

    payload = ExportPayload(
        title=f"گزارش عملیات {job_id}",
        headers=headers,
        rows=rows,
        summary={
            "نوع عملیات": job.type.value,
            "وضعیت": job.status.value,
            "مجموع": str(job.total),
            "موفق": str(job.success),
            "قبلاً انجام‌شده": str(job.already),
            "ناموفق": str(job.failed),
            "تاریخ ایجاد": job.created_at[:19],
        },
    )

    try:
        content, filename = render(payload, fmt)
    except Exception as exc:  # noqa: BLE001
        log.exception("export failed")
        await safe_edit(
            query,
            error_view("ساخت فایل خروجی انجام نشد.", str(exc)[:200]),
            kb.back_only(pack(NS_EXPORT, "menu", job_id)),
        )
        await query.answer()
        return

    message = query.message
    if message is None:
        await query.answer()
        return

    try:
        await message.answer_document(
            BufferedInputFile(content, filename=filename),
            caption=(
                f"📄 خروجی عملیات <b>#{job_id}</b>\n"
                f"قالب: <code>{fmt.upper()}</code> — {len(rows):,} ردیف"
            ),
        )
        await db.record_export(job_id, fmt, filename)
        await db.audit(query.from_user.id, "export", f"job={job_id} fmt={fmt}")
    except Exception as exc:  # noqa: BLE001
        log.exception("send document failed")
        await safe_edit(
            query,
            error_view("ارسال فایل انجام نشد.", str(exc)[:200]),
            kb.back_only(pack(NS_EXPORT, "menu", job_id)),
        )
        await query.answer()
        return

    await safe_edit(
        query,
        f"✅ <b>خروجی ساخته شد</b>\n━━━━━━━━━━━━━━\n"
        f"فایل <code>{fmt.upper()}</code> با {len(rows):,} ردیف ارسال شد.",
        kb.export_menu(job_id, pdf_available()),
    )
    await query.answer("فایل ارسال شد.")
