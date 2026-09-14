"""مدیریت لینکدونی (بخش پنجم)."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import config
from app.db.database import Database
from app.handlers.common import page_slice, safe_edit
from app.security import normalize_eitaa_url
from app.ui import keyboards as kb
from app.ui.callbacks import NS_LINKDONI, pack, parse
from app.ui.texts import (
    confirm_view,
    error_view,
    linkdoni_empty,
    linkdoni_header,
    success_view,
)

log = logging.getLogger(__name__)
router = Router(name="linkdoni")


class AddLinkdoni(StatesGroup):
    waiting_urls = State()


async def render_list(query: CallbackQuery, db: Database, page: int) -> None:
    total = await db.count_linkdoni()
    if total == 0:
        await safe_edit(query, linkdoni_empty(), kb.linkdoni_menu([], 1, 1, empty=True))
        return
    pages = kb.page_count(total, config.page_size)
    page = max(1, min(page, pages))
    items = await db.list_linkdoni(config.page_size, page_slice(page, config.page_size))
    selected = await db.count_linkdoni(only_selected=True)
    await safe_edit(
        query,
        linkdoni_header(total, selected, page, pages),
        kb.linkdoni_menu(items, page, pages, empty=False),
    )


@router.callback_query(F.data.startswith(f"{NS_LINKDONI}:list"))
async def cb_list(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    cb = parse(query.data)
    await render_list(query, db, int(cb.arg) if cb.arg.isdigit() else 1)
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_LINKDONI}:tgl:"))
async def cb_toggle(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    await db.toggle_linkdoni(cb.int_arg)
    page = int(cb.arg2) if cb.arg2.isdigit() else 1
    await render_list(query, db, page)
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_LINKDONI}:all"))
async def cb_select_all(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    await db.set_all_linkdoni_selected(True)
    await render_list(query, db, int(cb.arg) if cb.arg.isdigit() else 1)
    await query.answer("همه انتخاب شدند.")


@router.callback_query(F.data.startswith(f"{NS_LINKDONI}:none"))
async def cb_clear_all(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    await db.set_all_linkdoni_selected(False)
    await render_list(query, db, int(cb.arg) if cb.arg.isdigit() else 1)
    await query.answer("انتخاب‌ها پاک شد.")


@router.callback_query(F.data == f"{NS_LINKDONI}:seed")
async def cb_seed(query: CallbackQuery, db: Database) -> None:
    added = await db.seed_default_linkdoni(config.default_linkdoni)
    await query.answer(f"{added} لینکدونی پیش‌فرض اضافه شد.", show_alert=True)
    await render_list(query, db, 1)


@router.callback_query(F.data == f"{NS_LINKDONI}:add")
async def cb_add(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddLinkdoni.waiting_urls)
    await safe_edit(
        query,
        "➕ <b>افزودن لینکدونی</b>\n"
        "━━━━━━━━━━━━━━\n"
        "یک یا چند آدرس بفرستید (هر خط یک مورد).\n\n"
        "قالب‌های پذیرفته‌شده:\n"
        "<code>https://eitaa.com/example</code>\n"
        "<code>@example</code>\n"
        "<code>example</code>\n\n"
        "<blockquote>لینک‌های تکراری ذخیره نمی‌شوند و "
        "فقط دامنهٔ رسمی ایتا پذیرفته می‌شود.</blockquote>\n\n"
        "برای لغو: /cancel",
        kb.back_only(pack(NS_LINKDONI, "list", 1)),
    )
    await query.answer()


@router.message(AddLinkdoni.waiting_urls)
async def on_urls(message: Message, db: Database, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("متنی دریافت نشد. دوباره تلاش کنید.")
        return

    added = duplicate = invalid = 0
    for line in raw.replace(",", "\n").splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        url = normalize_eitaa_url(candidate)
        if url is None:
            invalid += 1
            continue
        if await db.add_linkdoni(url) is None:
            duplicate += 1
        else:
            added += 1

    await state.clear()
    user = message.from_user
    await db.audit(user.id if user else 0, "linkdoni_add", f"added={added}")

    if added == 0 and invalid and not duplicate:
        await message.answer(
            error_view(
                "هیچ لینک معتبری پیدا نشد.",
                "فقط آدرس‌های دامنهٔ eitaa.com پذیرفته می‌شوند.",
            ),
            reply_markup=kb.retry_menu(
                pack(NS_LINKDONI, "add"), pack(NS_LINKDONI, "list", 1)
            ),
        )
        return

    details = []
    if added:
        details.append(f"{added} مورد افزوده شد")
    if duplicate:
        details.append(f"{duplicate} تکراری بود")
    if invalid:
        details.append(f"{invalid} نامعتبر بود")
    await message.answer(
        success_view("لینکدونی‌ها بررسی شدند.", "، ".join(details)),
        reply_markup=kb.back_only(pack(NS_LINKDONI, "list", 1)),
    )


@router.callback_query(F.data.startswith(f"{NS_LINKDONI}:delask:"))
async def cb_delete_ask(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    item = await db.get_linkdoni(cb.int_arg)
    if item is None:
        await query.answer("این مورد وجود ندارد.", show_alert=True)
        return
    page = cb.arg2 if cb.arg2.isdigit() else "1"
    await safe_edit(
        query,
        confirm_view(f"این لینکدونی حذف شود؟\n\n{item.url}"),
        kb.confirm_menu(
            pack(NS_LINKDONI, "del", item.id, page), pack(NS_LINKDONI, "list", page)
        ),
    )
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_LINKDONI}:del:"))
async def cb_delete(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    await db.delete_linkdoni(cb.int_arg)
    await db.audit(query.from_user.id, "linkdoni_delete", f"#{cb.arg}")
    await query.answer("حذف شد.")
    await render_list(query, db, int(cb.arg2) if cb.arg2.isdigit() else 1)
