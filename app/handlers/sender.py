"""Sender — بخش نهم تا دوازدهم."""
from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import config
from app.db.database import Database
from app.db.models import JobStatus, JobType, TargetKind
from app.eitaa.base import Capability, EitaaError
from app.eitaa.service import build_backend
from app.handlers.common import page_slice, safe_edit
from app.security import clean_text, redact, resolve_inside
from app.services.jobs import JobHandle, JobManager, finalize_job, format_duration
from app.services.progress import ProgressReporter
from app.services.sender import load_targets, parse_manual_targets, run_send
from app.ui import keyboards as kb
from app.ui.callbacks import NS_SENDER, pack, parse
from app.ui.texts import (
    composer_view,
    error_view,
    job_report,
    loading_view,
    message_preview,
    progress_view,
    success_view,
    targets_summary,
    validate_telegram_html,
)

log = logging.getLogger(__name__)
router = Router(name="sender")

ACCOUNT = "sender_account"
TEXT = "sender_text"
PARSE_MODE = "sender_pm"
TARGETS = "sender_targets"
TARGET_KIND = "sender_target_kind"
MEDIA_PATH = "sender_media_path"
MEDIA_NAME = "sender_media_name"

# سقف اندازهٔ فایل دریافتی از تلگرام برای ربات‌ها: ۲۰ مگابایت (محدودیت واقعی Bot API)
MAX_MEDIA_BYTES = 20 * 1024 * 1024


class Compose(StatesGroup):
    waiting_text = State()
    waiting_manual = State()
    waiting_media = State()


async def _menu(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    data = await state.get_data()
    account = await db.get_account(data[ACCOUNT]) if data.get(ACCOUNT) else None
    text = data.get(TEXT, "")
    targets = data.get(TARGETS) or []
    kind = data.get(TARGET_KIND, "")

    body = (
        "📤 <b>SENDER</b>\n"
        "━━━━━━━━━━━━━━\n"
        "ارسال پیام به گروه‌ها، مخاطبین یا چت‌های خصوصی.\n\n"
        f"اکانت: <b>{account.label if account else '— انتخاب نشده —'}</b>\n"
        f"متن: <b>{'ثبت شده' if text else '— خالی —'}</b>\n"
        f"مقصد: <b>{TargetKind[kind].label if kind in TargetKind.__members__ else '— انتخاب نشده —'}"
        f"{f' ({len(targets)})' if targets else ''}</b>\n"
    )
    if account is not None and not account.can_send:
        body += "\n⚠️ این اکانت امکان ارسال ندارد."
    await safe_edit(
        query, body, kb.sender_menu(account is not None, bool(text), bool(targets))
    )


@router.callback_query(F.data == f"{NS_SENDER}:menu")
async def cb_menu(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    await _menu(query, db, state)
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_SENDER}:accs"))
async def cb_accounts(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    page = int(cb.arg) if cb.arg.isdigit() else 1
    total = await db.count_accounts()
    pages = kb.page_count(total, config.page_size)
    page = max(1, min(page, pages))
    accounts = await db.list_accounts(config.page_size, page_slice(page, config.page_size))
    await safe_edit(
        query,
        "👤 <b>انتخاب اکانت</b>\n━━━━━━━━━━━━━━\n"
        + ("<i>اکانتی ثبت نشده است.</i>" if not accounts else "یک اکانت را انتخاب کنید:"),
        kb.select_account_menu(accounts, page, pages, NS_SENDER),
    )
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_SENDER}:pick:"))
async def cb_pick(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    cb = parse(query.data)
    account = await db.get_account(cb.int_arg)
    if account is None:
        await query.answer("اکانت پیدا نشد.", show_alert=True)
        return
    await state.update_data(**{ACCOUNT: account.id, TARGETS: [], TARGET_KIND: ""})
    await _menu(query, db, state)
    await query.answer(f"اکانت «{account.label}» انتخاب شد.")


# ───────────────────────── Composer ─────────────────────────
@router.callback_query(F.data == f"{NS_SENDER}:compose")
async def cb_compose(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    media_name = data.get(MEDIA_NAME, "")
    await safe_edit(
        query,
        composer_view(data.get(TEXT, ""), data.get(PARSE_MODE, "HTML"), media_name),
        kb.composer_menu(config.ai_ready, bool(media_name)),
    )
    await query.answer()


# ───────────────────────── Media attachment ─────────────────────────
@router.callback_query(F.data.startswith(f"{NS_SENDER}:media:"))
async def cb_media(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    cb = parse(query.data)
    data = await state.get_data()

    if cb.arg == "clear":
        old = data.get(MEDIA_PATH, "")
        if old:
            with suppress(OSError):
                Path(old).unlink()
        await state.update_data(**{MEDIA_PATH: "", MEDIA_NAME: ""})
        await safe_edit(
            query,
            composer_view(data.get(TEXT, ""), data.get(PARSE_MODE, "HTML"), ""),
            kb.composer_menu(config.ai_ready, False),
        )
        await query.answer("پیوست حذف شد.")
        return

    # افزودن پیوست — فقط اگر اکانت انتخاب‌شده واقعاً از ارسال فایل پشتیبانی کند
    account_id = data.get(ACCOUNT)
    if not account_id:
        await query.answer("ابتدا اکانت را انتخاب کنید.", show_alert=True)
        return
    try:
        backend = await build_backend(db, account_id)
    except EitaaError as exc:
        await query.answer(exc.message, show_alert=True)
        return
    supported = backend.can_send_media is Capability.AVAILABLE
    await backend.close()
    if not supported:
        await query.answer(
            "این اکانت از ارسال فایل پشتیبانی نمی‌کند.", show_alert=True
        )
        return

    await state.set_state(Compose.waiting_media)
    await safe_edit(
        query,
        "📎 <b>افزودن پیوست</b>\n"
        "━━━━━━━━━━━━━━\n"
        "یک فایل، عکس یا ویدیو بفرستید.\n\n"
        f"حداکثر حجم: <b>{MAX_MEDIA_BYTES // (1024 * 1024)} مگابایت</b> "
        "(محدودیت دریافت فایل در Bot API)\n\n"
        "برای لغو: /cancel",
        kb.back_only(pack(NS_SENDER, "compose")),
    )
    await query.answer()


@router.message(Compose.waiting_media)
async def on_media(message: Message, state: FSMContext, bot: Bot) -> None:
    """دریافت فایل از تلگرام و ذخیرهٔ امن آن برای ارسال به ایتا."""
    doc = message.document
    file_id = ""
    file_name = ""
    size = 0

    if doc is not None:
        file_id, file_name, size = doc.file_id, doc.file_name or "file", doc.file_size or 0
    elif message.photo:
        photo = message.photo[-1]
        file_id, file_name, size = photo.file_id, f"photo_{photo.file_unique_id}.jpg", photo.file_size or 0
    elif message.video is not None:
        vid = message.video
        file_id, file_name, size = vid.file_id, vid.file_name or f"video_{vid.file_unique_id}.mp4", vid.file_size or 0
    elif message.audio is not None:
        aud = message.audio
        file_id, file_name, size = aud.file_id, aud.file_name or f"audio_{aud.file_unique_id}.mp3", aud.file_size or 0
    else:
        await message.answer("فقط فایل، عکس، ویدیو یا صوت پذیرفته می‌شود.")
        return

    if size > MAX_MEDIA_BYTES:
        await message.answer(
            error_view(
                "حجم فایل بیش از حد مجاز است.",
                f"{size // (1024 * 1024)} مگابایت دریافت شد؛ "
                f"حداکثر {MAX_MEDIA_BYTES // (1024 * 1024)} مگابایت.",
            ),
            reply_markup=kb.back_only(pack(NS_SENDER, "compose")),
        )
        return

    # مسیر امن داخل پوشهٔ media — بدون امکان Path Traversal
    user = message.from_user
    prefix = f"{user.id}_" if user is not None else ""
    target = resolve_inside(config.media_dir, f"{prefix}{file_name}")
    try:
        await bot.download(file_id, destination=target)
    except TelegramAPIError as exc:
        log.warning("download failed: %s", redact(exc))
        await message.answer(
            error_view("دریافت فایل از تلگرام انجام نشد.", "دوباره تلاش کنید."),
            reply_markup=kb.back_only(pack(NS_SENDER, "compose")),
        )
        return

    await state.update_data(**{MEDIA_PATH: str(target), MEDIA_NAME: target.name})
    await state.set_state(None)
    await message.answer(
        success_view(f"پیوست ثبت شد: {target.name}"),
        reply_markup=kb.composer_menu(config.ai_ready, True),
    )


@router.callback_query(F.data == f"{NS_SENDER}:edit")
async def cb_edit(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Compose.waiting_text)
    await safe_edit(
        query,
        "✏️ <b>ویرایش متن پیام</b>\n"
        "━━━━━━━━━━━━━━\n"
        "متن را بفرستید.\n\n"
        "<blockquote expandable>قالب‌بندی پشتیبانی‌شده (HTML):\n"
        "&lt;b&gt;پررنگ&lt;/b&gt; • &lt;i&gt;کج&lt;/i&gt; • &lt;u&gt;زیرخط&lt;/u&gt;\n"
        "&lt;s&gt;خط‌خورده&lt;/s&gt; • &lt;tg-spoiler&gt;اسپویلر&lt;/tg-spoiler&gt;\n"
        "&lt;code&gt;کد&lt;/code&gt; • &lt;pre&gt;بلوک&lt;/pre&gt;\n"
        "&lt;a href=\"https://...\"&gt;لینک&lt;/a&gt;\n"
        "&lt;blockquote&gt;نقل‌قول&lt;/blockquote&gt;</blockquote>\n\n"
        "⚠️ <i>قالب‌بندی HTML مربوط به نمایش در تلگرام است. متنی که به ایتا "
        "ارسال می‌شود متن ساده خواهد بود.</i>\n\n"
        "برای لغو: /cancel",
        kb.back_only(pack(NS_SENDER, "compose")),
    )
    await query.answer()


@router.message(Compose.waiting_text)
async def on_text(message: Message, state: FSMContext, db: Database) -> None:
    text = clean_text(message.text or "", 4000)
    if not text.strip():
        await message.answer("متن خالی است. دوباره بفرستید.")
        return

    data = await state.get_data()
    parse_mode = data.get(PARSE_MODE, "HTML")
    if parse_mode == "HTML":
        # اعتبارسنجی محلی طبق قواعد واقعی Bot API — بدون ارسال پیام آزمایشی
        problem = validate_telegram_html(text)
        if problem:
            await message.answer(
                error_view("قالب‌بندی متن معتبر نیست.", problem),
                reply_markup=kb.retry_menu(
                    pack(NS_SENDER, "edit"), pack(NS_SENDER, "compose")
                ),
            )
            return

    await state.update_data(**{TEXT: text})
    await state.set_state(None)
    user = message.from_user
    if user is not None:
        await db.save_draft(user.id, text, parse_mode)
    await message.answer(
        success_view("متن پیام ثبت شد."),
        reply_markup=kb.composer_menu(config.ai_ready, bool(data.get(MEDIA_NAME))),
    )


@router.callback_query(F.data.startswith(f"{NS_SENDER}:pm:"))
async def cb_parse_mode(query: CallbackQuery, state: FSMContext) -> None:
    cb = parse(query.data)
    mode = "HTML" if cb.arg == "HTML" else "NONE"
    await state.update_data(**{PARSE_MODE: mode})
    data = await state.get_data()
    media_name = data.get(MEDIA_NAME, "")
    await safe_edit(
        query,
        composer_view(data.get(TEXT, ""), mode, media_name),
        kb.composer_menu(config.ai_ready, bool(media_name)),
    )
    await query.answer(f"قالب روی {mode} تنظیم شد.")


# ───────────────────────── Targets ─────────────────────────
@router.callback_query(F.data == f"{NS_SENDER}:targets")
async def cb_targets(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    targets = data.get(TARGETS) or []
    kind = data.get(TARGET_KIND, "")
    counts = {"GROUPS": 0, "CONTACTS": 0, "PRIVATE": 0, "MANUAL": 0}
    if kind in counts:
        counts[kind] = len(targets)
    await safe_edit(
        query,
        targets_summary(
            counts["GROUPS"], counts["CONTACTS"], counts["PRIVATE"], counts["MANUAL"]
        ),
        kb.targets_menu(),
    )
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_SENDER}:target:"))
async def cb_target_pick(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    cb = parse(query.data)
    kind = cb.arg
    data = await state.get_data()
    account_id = data.get(ACCOUNT)
    if not account_id:
        await query.answer("ابتدا اکانت را انتخاب کنید.", show_alert=True)
        return

    if kind == "MANUAL":
        await state.set_state(Compose.waiting_manual)
        await safe_edit(
            query,
            "✍️ <b>ورود دستی مقصدها</b>\n"
            "━━━━━━━━━━━━━━\n"
            "هر خط یک شناسه یا لینک.\n\n"
            "<code>@channel</code>\n"
            "<code>https://eitaa.com/channel</code>\n\n"
            "برای لغو: /cancel",
            kb.back_only(pack(NS_SENDER, "targets")),
        )
        await query.answer()
        return

    await safe_edit(query, loading_view("در حال دریافت فهرست مقصدها..."))
    try:
        backend = await build_backend(db, account_id)
    except EitaaError as exc:
        await safe_edit(
            query, error_view(exc.message), kb.back_only(pack(NS_SENDER, "targets"))
        )
        await query.answer()
        return

    try:
        items, error = await load_targets(backend, kind)
    finally:
        await backend.close()

    if error:
        await safe_edit(
            query,
            error_view("دریافت مقصدها ممکن نشد.", error),
            kb.back_only(pack(NS_SENDER, "targets")),
        )
        await query.answer()
        return
    if not items:
        await safe_edit(
            query,
            "📭 <b>موردی پیدا نشد</b>\n━━━━━━━━━━━━━━\n"
            "برای این اکانت مقصدی در این دسته وجود ندارد.",
            kb.back_only(pack(NS_SENDER, "targets")),
        )
        await query.answer()
        return

    await state.update_data(**{TARGETS: items, TARGET_KIND: kind})
    await _menu(query, db, state)
    await query.answer(f"{len(items)} مقصد انتخاب شد.")


@router.message(Compose.waiting_manual)
async def on_manual(message: Message, db: Database, state: FSMContext) -> None:
    items = parse_manual_targets(message.text or "")
    if not items:
        await message.answer(
            error_view("هیچ مقصد معتبری پیدا نشد.", "هر خط باید یک شناسه یا لینک ایتا باشد.")
        )
        return
    await state.update_data(**{TARGETS: items, TARGET_KIND: "MANUAL"})
    await state.set_state(None)
    await message.answer(
        success_view(f"{len(items)} مقصد ثبت شد."),
        reply_markup=kb.back_only(pack(NS_SENDER, "menu")),
    )


# ───────────────────────── Preview & Send ─────────────────────────
@router.callback_query(F.data == f"{NS_SENDER}:preview")
async def cb_preview(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get(TEXT, "")
    targets = data.get(TARGETS) or []
    account = await db.get_account(data[ACCOUNT]) if data.get(ACCOUNT) else None
    if not text or not targets or account is None:
        await query.answer("اطلاعات ارسال کامل نیست.", show_alert=True)
        return
    kind = data.get(TARGET_KIND, "MANUAL")
    media_name = data.get(MEDIA_NAME, "")
    media_ok = True
    if media_name:
        try:
            backend = await build_backend(db, account.id)
            media_ok = backend.can_send_media is Capability.AVAILABLE
            await backend.close()
        except EitaaError:
            media_ok = False
    await safe_edit(
        query,
        message_preview(
            text,
            data.get(PARSE_MODE, "HTML"),
            TargetKind[kind].label if kind in TargetKind.__members__ else kind,
            account.label,
            len(targets),
            media_name,
            media_ok,
        ),
        kb.preview_menu(),
    )
    await query.answer()


@router.callback_query(F.data == f"{NS_SENDER}:start")
async def cb_start(
    query: CallbackQuery, db: Database, state: FSMContext, jobs: JobManager, bot: Bot
) -> None:
    data = await state.get_data()
    text = data.get(TEXT, "")
    targets = data.get(TARGETS) or []
    account_id = data.get(ACCOUNT)
    if not text or not targets or not account_id:
        await query.answer("اطلاعات ارسال کامل نیست.", show_alert=True)
        return

    account = await db.get_account(account_id)
    if account is None:
        await query.answer("اکانت پیدا نشد.", show_alert=True)
        return

    try:
        backend = await build_backend(db, account_id)
    except EitaaError as exc:
        await safe_edit(
            query, error_view(exc.message), kb.back_only(pack(NS_SENDER, "menu"))
        )
        await query.answer()
        return

    job_id = await db.create_job(
        JobType.SENDER, account_id, {"kind": data.get(TARGET_KIND, ""), "count": len(targets)}
    )
    await db.add_job_items(job_id, [(ref, title) for ref, title in targets])
    await db.set_job_total(job_id, len(targets))

    message = query.message
    if message is None:
        await query.answer()
        return
    reporter = ProgressReporter(
        bot, message.chat.id, message.message_id, config.progress_edit_interval
    )
    await safe_edit(query, loading_view("در حال شروع ارسال..."))

    async def worker(handle: JobHandle) -> None:
        try:
            async def on_progress(done: int, total: int, current: str) -> None:
                snapshot = await db.get_job(job_id)
                if snapshot is None:
                    return
                await reporter.update(
                    progress_view(
                        title="📤 <b>SENDER</b>",
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

            await run_send(
                db,
                job_id,
                backend,
                handle,
                text,
                media_path=data.get(MEDIA_PATH, ""),
                on_progress=on_progress,
            )
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
    await query.answer("ارسال آغاز شد.")


@router.callback_query(F.data == f"{NS_SENDER}:stats")
async def cb_stats(query: CallbackQuery, db: Database) -> None:
    jobs_list = await db.list_jobs(100)
    sender_jobs = [j for j in jobs_list if j.type is JobType.SENDER]
    total = sum(j.total for j in sender_jobs)
    success = sum(j.success for j in sender_jobs)
    failed = sum(j.failed for j in sender_jobs)
    rate = f"{success * 100 // total}%" if total else "—"
    await safe_edit(
        query,
        "📊 <b>آمار ارسال</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"تعداد عملیات: <b>{len(sender_jobs)}</b>\n"
        f"مجموع مقصدها: <b>{total:,}</b>\n"
        f"✅ موفق: <b>{success:,}</b>\n"
        f"❌ ناموفق: <b>{failed:,}</b>\n"
        f"نرخ موفقیت: <b>{rate}</b>",
        kb.back_only(pack(NS_SENDER, "menu")),
    )
    await query.answer()
