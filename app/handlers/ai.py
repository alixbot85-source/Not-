"""دستیار هوش مصنوعی در Composer (بخش ۳۳) — EXTERNAL SERVICE REQUIRED."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.config import config
from app.db.database import Database
from app.handlers.common import safe_edit
from app.services.ai import AIError, ai_service
from app.ui import keyboards as kb
from app.ui.callbacks import NS_AI, NS_SENDER, pack, parse
from app.ui.texts import composer_view, error_view, loading_view

log = logging.getLogger(__name__)
router = Router(name="ai")

TEXT_KEY = "sender_text"
PM_KEY = "sender_pm"

NOT_CONFIGURED = (
    "سرویس هوش مصنوعی پیکربندی نشده است.\n\n"
    "برای فعال‌سازی، این مقادیر را در فایل .env تنظیم کنید:\n"
    "AI_ENABLED=true\n"
    "AI_API_KEY=<کلید شما>\n"
    "AI_BASE_URL=<آدرس سرویس سازگار با OpenAI>"
)


@router.callback_query(F.data == f"{NS_AI}:menu")
async def cb_menu(query: CallbackQuery, state: FSMContext) -> None:
    if not config.ai_ready:
        await safe_edit(
            query,
            error_view("دستیار هوشمند در دسترس نیست.", NOT_CONFIGURED),
            kb.back_only(pack(NS_SENDER, "compose")),
        )
        await query.answer()
        return
    data = await state.get_data()
    if not data.get(TEXT_KEY):
        await query.answer("ابتدا متن پیام را بنویسید.", show_alert=True)
        return
    await safe_edit(
        query,
        "🧠 <b>دستیار هوشمند</b>\n"
        "━━━━━━━━━━━━━━\n"
        "یک عملیات را انتخاب کنید. نتیجه جایگزین متن فعلی می‌شود.\n\n"
        "<blockquote>دستیار فقط روی متن پیش‌نویس کار می‌کند و به اکانت‌ها "
        "یا عملیات‌ها دسترسی ندارد.</blockquote>",
        kb.ai_menu(),
    )
    await query.answer()


@router.callback_query(F.data == f"{NS_AI}:styles")
async def cb_styles(query: CallbackQuery) -> None:
    await safe_edit(
        query,
        "🎨 <b>تغییر لحن</b>\n━━━━━━━━━━━━━━\nلحن موردنظر را انتخاب کنید:",
        kb.ai_styles_menu(),
    )
    await query.answer()


async def _apply(
    query: CallbackQuery, state: FSMContext, db: Database, action: str, style: str | None
) -> None:
    data = await state.get_data()
    text = data.get(TEXT_KEY, "")
    if not text:
        await query.answer("متنی برای پردازش وجود ندارد.", show_alert=True)
        return

    await safe_edit(query, loading_view("در حال پردازش با هوش مصنوعی..."))
    try:
        result = await ai_service.transform(text, action, style)
    except AIError as exc:
        await safe_edit(
            query,
            error_view("پردازش انجام نشد.", str(exc)),
            kb.retry_menu(query.data or pack(NS_AI, "menu"), pack(NS_AI, "menu")),
        )
        await query.answer()
        return

    await state.update_data(**{TEXT_KEY: result})
    user = query.from_user
    await db.save_draft(user.id, result, data.get(PM_KEY, "HTML"))
    await db.audit(user.id, "ai_transform", action)
    await safe_edit(
        query,
        "✅ <b>متن به‌روزرسانی شد</b>\n━━━━━━━━━━━━━━\n\n"
        + composer_view(result, data.get(PM_KEY, "HTML")),
        kb.composer_menu(True),
    )
    await query.answer("انجام شد.")


@router.callback_query(F.data.startswith(f"{NS_AI}:act:"))
async def cb_action(query: CallbackQuery, state: FSMContext, db: Database) -> None:
    cb = parse(query.data)
    await _apply(query, state, db, cb.arg, None)


@router.callback_query(F.data.startswith(f"{NS_AI}:style:"))
async def cb_style(query: CallbackQuery, state: FSMContext, db: Database) -> None:
    cb = parse(query.data)
    await _apply(query, state, db, "rewrite", cb.arg)
