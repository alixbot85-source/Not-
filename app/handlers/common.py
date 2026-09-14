"""ابزارهای مشترک هندلرها + صفحهٔ اصلی و /start."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.db.database import Database
from app.ui import keyboards as kb
from app.ui.callbacks import CallbackError, parse
from app.ui.texts import main_panel

log = logging.getLogger(__name__)
router = Router(name="common")


async def safe_edit(
    query: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    """
    ویرایش امن پیام.
    خطای «message is not modified» رفتار عادی Bot API است و نادیده گرفته می‌شود.
    """
    message = query.message
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        if "message to edit not found" in str(exc).lower():
            await message.answer(text, reply_markup=markup)
            return
        log.warning("edit failed: %s", exc)
        try:
            await message.answer(text, reply_markup=markup)
        except TelegramBadRequest:
            pass


def page_slice(page: int, size: int) -> int:
    return max(0, (page - 1) * size)


async def show_main_panel(
    db: Database, name: str, edit: CallbackQuery | None = None, message: Message | None = None
) -> None:
    text = main_panel(
        name=name,
        accounts=await db.count_accounts(),
        linkdoni=await db.count_linkdoni(),
        jobs=await db.count_jobs(),
    )
    markup = kb.main_menu()
    if edit is not None:
        await safe_edit(edit, text, markup)
    elif message is not None:
        await message.answer(text, reply_markup=markup)


# ══════════════════════════════════════════════════════════════════
@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    name = (user.first_name if user else "") or "کاربر"
    await db.audit(user.id if user else 0, "start")
    await show_main_panel(db, name, message=message)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "ℹ️ <b>راهنما</b>\n"
        "━━━━━━━━━━━━━━\n"
        "<b>/start</b> — نمایش پنل اصلی\n"
        "<b>/cancel</b> — لغو عملیات جاری\n"
        "<b>/help</b> — همین راهنما\n\n"
        "<blockquote>تمام بخش‌ها از طریق دکمه‌های پنل اصلی در دسترس‌اند.</blockquote>",
        reply_markup=kb.main_menu(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    user = message.from_user
    await message.answer("✅ عملیات جاری لغو شد.")
    await show_main_panel(db, (user.first_name if user else "") or "کاربر", message=message)


@router.callback_query(F.data == "main:home")
async def cb_home(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    user = query.from_user
    await show_main_panel(db, user.first_name or "کاربر", edit=query)
    await query.answer()


@router.callback_query(F.data.startswith("noop:"))
async def cb_noop(query: CallbackQuery) -> None:
    """دکمه‌های نمایشی مثل شمارندهٔ صفحه."""
    await query.answer()


@router.callback_query()
async def cb_unknown(query: CallbackQuery) -> None:
    """
    آخرین خط دفاع: هر callback ناشناخته یا دستکاری‌شده اینجا می‌افتد.
    این هندلر باید آخرین router ثبت‌شده باشد.
    """
    try:
        parsed = parse(query.data)
        log.warning("callback بدون هندلر: %s", parsed)
        await query.answer("این دکمه دیگر معتبر نیست.", show_alert=True)
    except CallbackError:
        log.warning("callback نامعتبر دریافت شد: %r", query.data)
        await query.answer("درخواست نامعتبر است.", show_alert=True)
