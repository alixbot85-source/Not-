"""Joiner — جریان کامل بخش ششم و هفتم."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.config import config
from app.db.database import Database
from app.db.models import JobStatus, JobType, LinkKind
from app.eitaa.base import Capability, EitaaError
from app.eitaa.extractor import LinkExtractor, scraper_available
from app.eitaa.mtproto_backend import INSTALL_HINT, mtproto_available
from app.eitaa.service import build_backend
from app.handlers.common import page_slice, safe_edit
from app.services.jobs import JobHandle, JobManager, finalize_job, format_duration
from app.services.joiner import prepare_join_items, run_extraction, run_join
from app.services.progress import ProgressReporter
from app.ui import keyboards as kb
from app.ui.callbacks import NS_JOINER, pack, parse
from app.ui.texts import (
    error_view,
    extraction_report,
    job_report,
    loading_view,
    progress_view,
)

log = logging.getLogger(__name__)
router = Router(name="joiner")

SELECTED_ACCOUNT = "joiner_account"
EXTRACT_JOB = "joiner_extract_job"


async def _menu_text(db: Database, state: FSMContext) -> tuple[str, bool]:
    data = await state.get_data()
    account_id = data.get(SELECTED_ACCOUNT)
    account = await db.get_account(account_id) if account_id else None
    selected = await db.count_linkdoni(only_selected=True)

    lines = [
        "📥 <b>JOINER</b>",
        "━━━━━━━━━━━━━━",
        "عضویت خودکار در گروه‌های استخراج‌شده از لینکدونی‌ها.",
        "",
        f"اکانت: <b>{account.label if account else '— انتخاب نشده —'}</b>",
        f"لینکدونی انتخاب‌شده: <b>{selected}</b>",
        "",
    ]

    ready = account is not None and selected > 0
    if account is not None and not account.can_join:
        lines.append(
            "⚠️ <b>توجه:</b> این اکانت از نوع توکن ایتایار است و "
            "امکان عضویت در گروه ندارد.\n"
            "<blockquote>عضویت فقط با اکانت «نشست کاربری» ممکن است. "
            "استخراج لینک همچنان کار می‌کند.</blockquote>"
        )
    if not scraper_available():
        lines.append("⚠️ کتابخانهٔ استخراج نصب نیست؛ استخراج لینک ممکن نخواهد بود.")
    if not mtproto_available():
        lines.append(
            "\nℹ️ <i>عضویت در گروه نیازمند فریم‌ورک MTProto است که نصب نشده. "
            "جزئیات در بخش تنظیمات ← وضعیت قابلیت‌ها.</i>"
        )
    if not ready:
        lines.append("\n<i>برای ادامه، اکانت و حداقل یک لینکدونی انتخاب کنید.</i>")
    return "\n".join(lines), ready


@router.callback_query(F.data == f"{NS_JOINER}:menu")
async def cb_menu(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    text, ready = await _menu_text(db, state)
    await safe_edit(query, text, kb.joiner_menu(ready))
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_JOINER}:accs"))
async def cb_accounts(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    page = int(cb.arg) if cb.arg.isdigit() else 1
    total = await db.count_accounts()
    pages = kb.page_count(total, config.page_size)
    page = max(1, min(page, pages))
    accounts = await db.list_accounts(config.page_size, page_slice(page, config.page_size))
    await safe_edit(
        query,
        "👤 <b>انتخاب اکانت</b>\n"
        "━━━━━━━━━━━━━━\n"
        + ("<i>اکانتی ثبت نشده است.</i>" if not accounts else "یک اکانت را انتخاب کنید:"),
        kb.select_account_menu(accounts, page, pages, NS_JOINER),
    )
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_JOINER}:pick:"))
async def cb_pick(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    cb = parse(query.data)
    account = await db.get_account(cb.int_arg)
    if account is None:
        await query.answer("اکانت پیدا نشد.", show_alert=True)
        return
    await state.update_data(**{SELECTED_ACCOUNT: account.id})
    text, ready = await _menu_text(db, state)
    await safe_edit(query, text, kb.joiner_menu(ready))

    # هشدار صریح: اکانت توکنی اصلاً امکان عضویت ندارد
    if not account.can_join:
        await query.answer(
            "این اکانت امکان عضویت در گروه ندارد؛ فقط استخراج لینک ممکن است.",
            show_alert=True,
        )
        return
    await query.answer(f"اکانت «{account.label}» انتخاب شد.")


# ══════════════════════════════════════════════════════════════════
#  مرحلهٔ ۱ تا ۳ — استخراج
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == f"{NS_JOINER}:extract")
async def cb_extract(
    query: CallbackQuery, db: Database, state: FSMContext, jobs: JobManager, bot: Bot
) -> None:
    data = await state.get_data()
    account_id = data.get(SELECTED_ACCOUNT)
    if not account_id:
        await query.answer("ابتدا اکانت را انتخاب کنید.", show_alert=True)
        return
    if not scraper_available():
        await safe_edit(
            query,
            error_view(
                "استخراج لینک ممکن نیست.",
                "کتابخانهٔ eitaa نصب نیست. دستور نصب: pip install eitaa==2.3.1",
            ),
            kb.back_only(pack(NS_JOINER, "menu")),
        )
        await query.answer()
        return

    selected = await db.list_linkdoni(only_selected=True)
    if not selected:
        await query.answer("هیچ لینکدونی‌ای انتخاب نشده است.", show_alert=True)
        return

    job_id = await db.create_job(JobType.EXTRACT, account_id, {"count": len(selected)})
    await state.update_data(**{EXTRACT_JOB: job_id})
    await safe_edit(query, loading_view("در حال آماده‌سازی استخراج..."))

    message = query.message
    if message is None:
        await query.answer()
        return
    reporter = ProgressReporter(
        bot, message.chat.id, message.message_id, config.progress_edit_interval
    )

    # Backend فقط اگر اکانت واقعاً بتواند join کند ساخته می‌شود
    backend = None
    account = await db.get_account(account_id)
    if account is not None and account.can_join and mtproto_available():
        try:
            backend = await build_backend(db, account_id)
        except EitaaError as exc:
            log.info("backend unavailable for extraction: %s", exc.message)

    extractor = LinkExtractor()
    pairs = [(item.id, item.url) for item in selected]

    async def worker(handle: JobHandle) -> None:
        async def on_progress(done: int, total: int, current: str) -> None:
            await reporter.update(
                progress_view(
                    title="🔎 <b>استخراج لینک</b>",
                    account=account.label if account else "—",
                    job_id=job_id,
                    total=total,
                    processed=done,
                    success=done,
                    already=0,
                    failed=0,
                    current=current,
                    status=JobStatus.RUNNING,
                    paused=handle.is_paused,
                ),
                kb.running_menu(job_id, handle.is_paused),
            )

        try:
            stats = await run_extraction(
                db, job_id, pairs, handle, extractor, backend, on_progress
            )
        finally:
            if backend is not None:
                await backend.close()

        await db.set_job_status(
            job_id,
            JobStatus.STOPPED if handle.stop_event.is_set() else JobStatus.COMPLETED,
        )

        # ساخت Job عضویت از نتیجهٔ استخراج
        join_job_id = await db.create_job(JobType.JOINER, account_id, {"source": job_id})
        ready = await prepare_join_items(db, join_job_id, job_id)
        unknown = await db.count_links(job_id, kind=LinkKind.UNKNOWN)

        text = extraction_report(
            checked=stats.checked,
            found=stats.found,
            duplicates=stats.duplicates,
            invalid=stats.invalid,
            kinds=stats.by_kind,
            ready=ready,
        )
        if unknown:
            text += (
                f"\n\n<blockquote>❔ {unknown} لینک به دلیل نامشخص بودن نوع "
                "کنار گذاشته شد. برای تشخیص قطعی نوع لینک، اکانت نشست کاربری لازم است.</blockquote>"
            )
        if ready and (account is None or not account.can_join):
            text += (
                "\n\n⚠️ <i>اکانت فعلی امکان عضویت ندارد؛ فقط خروجی لینک‌ها در دسترس است.</i>"
            )

        can_start = bool(ready) and account is not None and account.can_join
        await reporter.finish(text, kb.extraction_menu(can_start, join_job_id))

    jobs.spawn(job_id, worker)
    await query.answer("استخراج آغاز شد.")


# ══════════════════════════════════════════════════════════════════
#  مرحلهٔ ۴ — عضویت
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith(f"{NS_JOINER}:start:"))
async def cb_start_join(
    query: CallbackQuery, db: Database, jobs: JobManager, bot: Bot
) -> None:
    cb = parse(query.data)
    job_id = cb.int_arg
    job = await db.get_job(job_id)
    if job is None:
        await query.answer("عملیات پیدا نشد.", show_alert=True)
        return
    if jobs.is_running(job_id):
        await query.answer("این عملیات در حال اجراست.", show_alert=True)
        return

    account = await db.get_account(job.account_id) if job.account_id else None
    if account is None:
        await query.answer("اکانت این عملیات موجود نیست.", show_alert=True)
        return
    if not account.can_join:
        await safe_edit(
            query,
            error_view(
                "این اکانت امکان عضویت در گروه ندارد.",
                "عضویت فقط با اکانت «نشست کاربری» ممکن است.",
            ),
            kb.back_only(pack(NS_JOINER, "menu")),
        )
        await query.answer()
        return
    if not mtproto_available():
        await safe_edit(
            query, error_view("عضویت ممکن نیست.", INSTALL_HINT), kb.back_only(pack(NS_JOINER, "menu"))
        )
        await query.answer()
        return

    try:
        backend = await build_backend(db, account.id)
    except EitaaError as exc:
        await safe_edit(
            query,
            error_view(exc.message),
            kb.retry_menu(query.data, pack(NS_JOINER, "menu")),
        )
        await query.answer()
        return

    if backend.can_join is not Capability.AVAILABLE:
        await backend.close()
        await safe_edit(
            query, error_view("عضویت در دسترس نیست.", INSTALL_HINT), kb.back_only(pack(NS_JOINER, "menu"))
        )
        await query.answer()
        return

    message = query.message
    if message is None:
        await query.answer()
        return
    reporter = ProgressReporter(
        bot, message.chat.id, message.message_id, config.progress_edit_interval
    )
    await safe_edit(query, loading_view("در حال شروع عضویت..."))

    async def worker(handle: JobHandle) -> None:
        try:
            async def on_progress(done: int, total: int, current: str) -> None:
                snapshot = await db.get_job(job_id)
                if snapshot is None:
                    return
                await reporter.update(
                    progress_view(
                        title="📥 <b>JOINER</b>",
                        account=account.label,
                        job_id=job_id,
                        total=total,
                        processed=done,
                        success=snapshot.success,
                        already=snapshot.already,
                        failed=snapshot.failed,
                        current=current,
                        status=JobStatus.RUNNING,
                        paused=handle.is_paused,
                    ),
                    kb.running_menu(job_id, handle.is_paused),
                )

            await run_join(db, job_id, backend, handle, on_progress)
        finally:
            await backend.close()

        await finalize_job(db, handle, job_id)
        final = await db.get_job(job_id)
        if final is not None:
            await reporter.finish(
                job_report(final, format_duration(handle.elapsed)),
                kb.report_menu(job_id, final.failed > 0),
            )

    jobs.spawn(job_id, worker)
    await query.answer("عضویت آغاز شد.")
