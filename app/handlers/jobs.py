"""Jobs، لاگ‌ها و گزارش‌ها (بخش ۱۸ تا ۲۰)."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from app.config import config
from app.db.database import Database
from app.db.models import ItemStatus, JobStatus, JobType
from app.eitaa.base import EitaaError
from app.eitaa.service import build_backend
from app.handlers.common import page_slice, safe_edit
from app.services.jobs import JobHandle, JobManager, finalize_job, format_duration
from app.services.joiner import run_join
from app.services.progress import ProgressReporter
from app.services.sender import run_send
from app.ui import keyboards as kb
from app.ui.callbacks import NS_JOB, pack, parse
from app.ui.texts import (
    error_view,
    job_detail,
    job_report,
    loading_view,
    logs_view,
    progress_view,
)

log = logging.getLogger(__name__)
router = Router(name="jobs")

LOGS_PER_PAGE = 12


@router.callback_query(F.data.startswith(f"{NS_JOB}:list"))
async def cb_list(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    page = int(cb.arg) if cb.arg.isdigit() else 1
    total = await db.count_jobs()
    pages = kb.page_count(total, config.page_size)
    page = max(1, min(page, pages))
    jobs_list = await db.list_jobs(config.page_size, page_slice(page, config.page_size))

    if not jobs_list:
        text = (
            "📊 <b>عملیات‌ها</b>\n━━━━━━━━━━━━━━\n"
            "📭 هنوز عملیاتی ثبت نشده است.\n\n"
            "<blockquote>با اجرای Joiner یا Sender، عملیات‌ها اینجا ثبت می‌شوند.</blockquote>"
        )
    else:
        text = (
            "📊 <b>عملیات‌ها و گزارش‌ها</b>\n━━━━━━━━━━━━━━\n"
            f"مجموع: <b>{total}</b> — صفحهٔ {page}/{pages}\n\n"
            "<i>برای جزئیات، روی هر عملیات بزنید.</i>"
        )
    await safe_edit(query, text, kb.jobs_menu(jobs_list, page, pages))
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_JOB}:view:"))
async def cb_view(query: CallbackQuery, db: Database, jobs: JobManager) -> None:
    cb = parse(query.data)
    job = await db.get_job(cb.int_arg)
    if job is None:
        await query.answer("عملیات پیدا نشد.", show_alert=True)
        return
    account = await db.get_account(job.account_id) if job.account_id else None
    handle = jobs.get(job.id)
    running = jobs.is_running(job.id)
    failed = await db.list_job_items(job.id, status=ItemStatus.FAILED, limit=1)
    await safe_edit(
        query,
        job_detail(job, account.label if account else "—"),
        kb.job_detail_menu(
            job, running, handle.is_paused if handle else False, bool(failed)
        ),
    )
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_JOB}:stop:"))
async def cb_stop(query: CallbackQuery, db: Database, jobs: JobManager) -> None:
    cb = parse(query.data)
    ok = await jobs.request_stop(cb.int_arg)
    await db.audit(query.from_user.id, "job_stop", f"#{cb.arg}")
    await query.answer(
        "درخواست توقف ثبت شد." if ok else "این عملیات در حال اجرا نیست.", show_alert=not ok
    )


@router.callback_query(F.data.startswith(f"{NS_JOB}:pause:"))
async def cb_pause(query: CallbackQuery, jobs: JobManager) -> None:
    cb = parse(query.data)
    ok = await jobs.pause(cb.int_arg)
    await query.answer("عملیات موقتاً متوقف شد." if ok else "امکان توقف موقت نیست.")


@router.callback_query(F.data.startswith(f"{NS_JOB}:resume:"))
async def cb_resume(query: CallbackQuery, jobs: JobManager) -> None:
    cb = parse(query.data)
    ok = await jobs.resume(cb.int_arg)
    await query.answer("عملیات از سر گرفته شد." if ok else "عملیات متوقف نبود.")


@router.callback_query(F.data.startswith(f"{NS_JOB}:logs:"))
async def cb_logs(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    page = int(cb.arg) if cb.arg.isdigit() else 1
    job_id = int(cb.arg2) if cb.arg2.isdigit() else 0
    total = await db.count_logs(job_id)
    pages = kb.page_count(total, LOGS_PER_PAGE)
    page = max(1, min(page, pages))
    entries = await db.list_logs(job_id, LOGS_PER_PAGE, page_slice(page, LOGS_PER_PAGE))
    rows = [(e.created_at[11:19], e.level.icon, e.message) for e in entries]
    await safe_edit(query, logs_view(job_id, rows, page, pages), kb.logs_menu(job_id, page, pages))
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_JOB}:retry:"))
async def cb_retry(query: CallbackQuery, db: Database, jobs: JobManager, bot: Bot) -> None:
    """تلاش مجدد روی آیتم‌های ناموفق — واقعی، با بازگرداندن آن‌ها به صف."""
    cb = parse(query.data)
    job_id = cb.int_arg
    if jobs.is_running(job_id):
        await query.answer("این عملیات در حال اجراست.", show_alert=True)
        return
    count = await db.reset_failed_items(job_id)
    if count == 0:
        await query.answer("موردی برای تلاش مجدد وجود ندارد.", show_alert=True)
        return
    await db.bump_job_counters(job_id, processed=-count, failed=-count)
    await _resume_job(query, db, jobs, bot, job_id, note=f"{count} مورد به صف بازگشت.")


@router.callback_query(F.data.startswith(f"{NS_JOB}:resumejob:"))
async def cb_resume_job(query: CallbackQuery, db: Database, jobs: JobManager, bot: Bot) -> None:
    """ادامهٔ Job پس از توقف یا restart (بخش ۳۱)."""
    cb = parse(query.data)
    await _resume_job(query, db, jobs, bot, cb.int_arg, note="ادامهٔ عملیات")


async def _resume_job(
    query: CallbackQuery,
    db: Database,
    jobs: JobManager,
    bot: Bot,
    job_id: int,
    note: str,
) -> None:
    job = await db.get_job(job_id)
    if job is None:
        await query.answer("عملیات پیدا نشد.", show_alert=True)
        return
    pending = await db.pending_items(job_id)
    if not pending:
        await query.answer("موردی برای ادامه وجود ندارد.", show_alert=True)
        return
    if job.type is JobType.EXTRACT:
        await query.answer("عملیات استخراج قابل ادامه نیست؛ دوباره اجرا کنید.", show_alert=True)
        return
    if job.account_id is None:
        await query.answer("اکانت این عملیات موجود نیست.", show_alert=True)
        return

    account = await db.get_account(job.account_id)
    if account is None:
        await query.answer("اکانت این عملیات حذف شده است.", show_alert=True)
        return

    try:
        backend = await build_backend(db, job.account_id)
    except EitaaError as exc:
        await safe_edit(
            query, error_view(exc.message), kb.back_only(pack(NS_JOB, "view", job_id))
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
    await safe_edit(query, loading_view(note))

    title = "📥 <b>JOINER</b>" if job.type is JobType.JOINER else "📤 <b>SENDER</b>"
    text = str(job.params.get("text", "")) if job.type is JobType.SENDER else ""

    async def worker(handle: JobHandle) -> None:
        try:
            async def on_progress(done: int, total: int, current: str) -> None:
                snapshot = await db.get_job(job_id)
                if snapshot is None:
                    return
                await reporter.update(
                    progress_view(
                        title=title,
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

            if job.type is JobType.JOINER:
                await run_join(db, job_id, backend, handle, on_progress)
            else:
                if not text:
                    await db.set_job_status(
                        job_id, JobStatus.FAILED, error="متن پیام این عملیات ذخیره نشده است."
                    )
                    await reporter.finish(
                        error_view(
                            "ادامهٔ این ارسال ممکن نیست.",
                            "متن پیام برای این عملیات ذخیره نشده بود.",
                        ),
                        kb.back_only(pack(NS_JOB, "view", job_id)),
                    )
                    return
                await run_send(db, job_id, backend, handle, text, on_progress=on_progress)
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
    await query.answer("عملیات ادامه یافت.")
