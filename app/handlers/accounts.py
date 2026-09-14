"""مدیریت اکانت‌ها (بخش چهارم)."""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import config
from app.db.database import Database
from app.db.models import AccountKind, AccountStatus
from app.eitaa.base import Capability, EitaaError
from app.eitaa.bridge_backend import (
    BRIDGE_HINT,
    confirm_login_code,
    confirm_login_password,
    send_login_code,
)
from app.eitaa.mtproto_backend import INSTALL_HINT, mtproto_available
from app.eitaa.service import build_backend
from app.handlers.common import page_slice, safe_edit
from app.security import clean_text, mask_phone
from app.ui import keyboards as kb
from app.ui.callbacks import NS_ACCOUNT, pack, parse
from app.ui.texts import (
    account_detail,
    accounts_empty,
    accounts_header,
    confirm_view,
    error_view,
    loading_view,
    success_view,
)

log = logging.getLogger(__name__)
router = Router(name="accounts")

# توکن ایتایار — قالب واقعی مشاهده‌شده: bot<digits>:<uuid>
TOKEN_RE = re.compile(r"^bot\d+:[0-9a-fA-F\-]{20,}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9_\-]{3,40}$")


class AddAccount(StatesGroup):
    waiting_token = State()
    waiting_label = State()
    waiting_session = State()
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()


# شمارهٔ ایران: +989xxxxxxxxx یا 09xxxxxxxxx
PHONE_RE = re.compile(r"^\+?\d{10,15}$")


def _capabilities(kind: AccountKind) -> list[tuple[str, str]]:
    """گزارش صادقانهٔ قابلیت‌های واقعی هر نوع اکانت."""
    if kind is AccountKind.BOT_API:
        return [
            ("ارسال پیام", Capability.AVAILABLE.label),
            ("ارسال فایل", Capability.AVAILABLE.label),
            ("عضویت در گروه", Capability.NOT_SUPPORTED.label),
            ("فهرست گروه‌ها/مخاطبین", Capability.NOT_SUPPORTED.label),
        ]
    if kind is AccountKind.BRIDGE:
        status = (
            Capability.AVAILABLE if config.bridge_ready else Capability.UNAVAILABLE
        )
        return [
            ("ارسال پیام", status.label),
            ("ارسال فایل", status.label),
            ("عضویت در گروه", status.label),
            ("فهرست گروه‌ها/مخاطبین", status.label),
        ]

    status = Capability.AVAILABLE if mtproto_available() else Capability.UNAVAILABLE
    return [
        ("ارسال پیام", status.label),
        ("عضویت در گروه", status.label),
        ("فهرست گروه‌ها/مخاطبین", status.label),
    ]


async def render_list(query: CallbackQuery, db: Database, page: int) -> None:
    total = await db.count_accounts()
    if total == 0:
        await safe_edit(query, accounts_empty(), kb.accounts_menu([], 1, 1, empty=True))
        return
    pages = kb.page_count(total, config.page_size)
    page = max(1, min(page, pages))
    accounts = await db.list_accounts(config.page_size, page_slice(page, config.page_size))
    await safe_edit(
        query,
        accounts_header(total, page, pages),
        kb.accounts_menu(accounts, page, pages, empty=False),
    )


# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith(f"{NS_ACCOUNT}:list"))
async def cb_list(query: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    cb = parse(query.data)
    page = int(cb.arg) if cb.arg.isdigit() else 1
    await render_list(query, db, page)
    await query.answer()


@router.callback_query(F.data == f"{NS_ACCOUNT}:add")
async def cb_add(query: CallbackQuery) -> None:
    await safe_edit(
        query,
        "➕ <b>افزودن اکانت</b>\n"
        "━━━━━━━━━━━━━━\n"
        "نوع اکانت را انتخاب کنید:\n\n"
        "<b>🤖 توکن ایتایار</b>\n"
        "<blockquote>از <code>eitaayar.ir</code> گرفته می‌شود. "
        "امکان ارسال پیام و فایل دارد. برای عضویت در گروه مناسب نیست.</blockquote>\n\n"
        "<b>👤 نشست کاربری</b>\n"
        "<blockquote>برای Joiner و دریافت فهرست گروه‌ها لازم است.</blockquote>",
        kb.account_add_menu(),
    )
    await query.answer()


@router.callback_query(F.data == f"{NS_ACCOUNT}:addtok")
async def cb_add_token(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddAccount.waiting_token)
    await safe_edit(
        query,
        "🤖 <b>افزودن اکانت ایتایار</b>\n"
        "━━━━━━━━━━━━━━\n"
        "توکن را ارسال کنید.\n\n"
        "قالب: <code>bot12345:xxxxxxxx-xxxx-...</code>\n\n"
        "<blockquote>🔒 توکن بلافاصله رمزنگاری و ذخیره می‌شود، "
        "پیام شما حذف می‌گردد و هرگز در پنل یا لاگ نمایش داده نمی‌شود.</blockquote>\n\n"
        "برای لغو: /cancel",
        kb.back_only(pack(NS_ACCOUNT, "list", 1)),
    )
    await query.answer()


@router.message(AddAccount.waiting_token)
async def on_token(message: Message, db: Database, state: FSMContext) -> None:
    token = (message.text or "").strip()
    try:  # حذف فوری پیام حاوی راز
        await message.delete()
    except Exception:  # noqa: BLE001
        log.info("امکان حذف پیام توکن نبود (دسترسی حذف لازم است)")

    if not TOKEN_RE.match(token):
        await message.answer(
            error_view(
                "قالب توکن معتبر نیست.",
                "توکن ایتایار به شکل bot12345:<uuid> است.",
            ),
            reply_markup=kb.retry_menu(
                pack(NS_ACCOUNT, "addtok"), pack(NS_ACCOUNT, "list", 1)
            ),
        )
        return

    await state.update_data(secret=token)
    await state.set_state(AddAccount.waiting_label)
    await message.answer(
        "✅ توکن دریافت و رمزنگاری شد.\n\n"
        "حالا یک <b>نام نمایشی</b> برای این اکانت بفرستید (مثلاً «کانال اصلی»).",
    )


@router.callback_query(F.data == f"{NS_ACCOUNT}:addses")
async def cb_add_session(query: CallbackQuery, state: FSMContext) -> None:
    if not mtproto_available():
        await safe_edit(
            query,
            error_view("افزودن نشست کاربری در حال حاضر ممکن نیست.", INSTALL_HINT),
            kb.back_only(pack(NS_ACCOUNT, "list", 1)),
        )
        await query.answer()
        return

    await state.set_state(AddAccount.waiting_session)
    await safe_edit(
        query,
        "👤 <b>افزودن نشست کاربری</b>\n"
        "━━━━━━━━━━━━━━\n"
        "نام فایل نشست را بفرستید (بدون پسوند).\n\n"
        f"فایل نشست باید از قبل در مسیر زیر موجود باشد:\n"
        f"<code>{config.session_dir}</code>\n\n"
        "<blockquote>ورود با شماره تلفن باید بیرون از پنل و با ابزار رسمی "
        "فریم‌ورک انجام شود؛ پنل کد تأیید را دریافت نمی‌کند.</blockquote>\n\n"
        "برای لغو: /cancel",
        kb.back_only(pack(NS_ACCOUNT, "list", 1)),
    )
    await query.answer()


@router.message(AddAccount.waiting_session)
async def on_session(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not SESSION_RE.match(name):
        await message.answer(
            error_view(
                "نام نشست معتبر نیست.",
                "فقط حروف انگلیسی، عدد، خط تیره و زیرخط (۳ تا ۴۰ کاراکتر).",
            )
        )
        return
    session_file = config.session_dir / f"{name}.session"
    if not session_file.is_file():
        await message.answer(
            error_view(
                "فایل نشست پیدا نشد.",
                f"انتظار می‌رفت این فایل موجود باشد:\n{session_file}",
            ),
            reply_markup=kb.retry_menu(
                pack(NS_ACCOUNT, "addses"), pack(NS_ACCOUNT, "list", 1)
            ),
        )
        return

    await state.update_data(session_name=name)
    await state.set_state(AddAccount.waiting_label)
    await message.answer("✅ نشست پیدا شد.\n\nیک <b>نام نمایشی</b> برای این اکانت بفرستید.")


@router.message(AddAccount.waiting_label)
async def on_label(message: Message, db: Database, state: FSMContext) -> None:
    label = clean_text(message.text or "", 60).strip()
    if not label:
        await message.answer("نام نمایشی خالی است. دوباره بفرستید.")
        return

    data = await state.get_data()
    await state.clear()
    secret = data.get("secret", "")
    session_name = data.get("session_name", "")
    phone = data.get("phone", "")

    if phone:
        # ورود با شماره: خودِ شماره کلید نشست در سرویس پل است، پس
        # مثل یک راز رمزنگاری‌شده ذخیره می‌شود.
        kind = AccountKind.BRIDGE
        secret = phone
    elif session_name:
        kind = AccountKind.MTPROTO
    else:
        kind = AccountKind.BOT_API

    account_id = await db.add_account(label, kind, secret=secret, session_name=session_name)
    user = message.from_user
    await db.audit(user.id if user else 0, "account_add", f"#{account_id} kind={kind.value}")

    status = await message.answer(loading_view("در حال بررسی اعتبار اکانت..."))
    note, account_status, identity = await _check_account(db, account_id)
    await db.update_account_status(account_id, account_status, note, identity)

    account = await db.get_account(account_id)
    if account is None:
        await status.edit_text(error_view("اکانت ذخیره نشد."))
        return
    await status.edit_text(
        success_view(f"اکانت «{label}» اضافه شد.", note)
        + "\n\n"
        + account_detail(account, _capabilities(kind)),
        reply_markup=kb.account_detail_menu(account_id),
    )


async def _check_account(db: Database, account_id: int) -> tuple[str, AccountStatus, str]:
    """اعتبارسنجی واقعی اکانت. خروجی: (یادداشت، وضعیت، شناسه)."""
    try:
        backend = await build_backend(db, account_id)
    except EitaaError as exc:
        return exc.message, AccountStatus.ERROR, ""
    try:
        identity = await backend.validate()
        return "اتصال برقرار است.", AccountStatus.ONLINE, identity.name
    except EitaaError as exc:
        status = AccountStatus.ERROR if exc.retryable else AccountStatus.INVALID
        return exc.message, status, ""
    except Exception as exc:  # noqa: BLE001
        log.warning("check failed: %s", exc)
        return "بررسی وضعیت انجام نشد.", AccountStatus.ERROR, ""
    finally:
        await backend.close()


@router.callback_query(F.data.startswith(f"{NS_ACCOUNT}:view:"))
async def cb_view(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    account = await db.get_account(cb.int_arg)
    if account is None:
        await query.answer("اکانت پیدا نشد.", show_alert=True)
        await render_list(query, db, 1)
        return
    await safe_edit(
        query,
        account_detail(account, _capabilities(account.kind)),
        kb.account_detail_menu(account.id),
    )
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_ACCOUNT}:check:"))
async def cb_check(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    account_id = cb.int_arg
    await safe_edit(query, loading_view("در حال بررسی وضعیت اکانت..."))
    note, status, identity = await _check_account(db, account_id)
    await db.update_account_status(account_id, status, note, identity)
    account = await db.get_account(account_id)
    if account is None:
        await query.answer("اکانت پیدا نشد.", show_alert=True)
        return
    await safe_edit(
        query,
        account_detail(account, _capabilities(account.kind)),
        kb.account_detail_menu(account_id),
    )
    await query.answer("بررسی انجام شد.")


@router.callback_query(F.data == f"{NS_ACCOUNT}:checkall")
async def cb_check_all(query: CallbackQuery, db: Database) -> None:
    accounts = await db.list_accounts()
    if not accounts:
        await query.answer("اکانتی وجود ندارد.", show_alert=True)
        return
    await safe_edit(query, loading_view(f"در حال بررسی {len(accounts)} اکانت..."))
    online = 0
    for account in accounts:
        note, status, identity = await _check_account(db, account.id)
        await db.update_account_status(account.id, status, note, identity)
        if status is AccountStatus.ONLINE:
            online += 1
    await query.answer(f"{online} از {len(accounts)} اکانت آنلاین است.", show_alert=True)
    await render_list(query, db, 1)


@router.callback_query(F.data.startswith(f"{NS_ACCOUNT}:delask:"))
async def cb_delete_ask(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    account = await db.get_account(cb.int_arg)
    if account is None:
        await query.answer("اکانت پیدا نشد.", show_alert=True)
        return
    await safe_edit(
        query,
        confirm_view(
            f"اکانت «{account.label}» حذف شود؟",
            "این عمل برگشت‌پذیر نیست. فایل نشست روی دیسک حذف نمی‌شود.",
        ),
        kb.confirm_menu(
            pack(NS_ACCOUNT, "del", account.id), pack(NS_ACCOUNT, "view", account.id)
        ),
    )
    await query.answer()


@router.callback_query(F.data.startswith(f"{NS_ACCOUNT}:del:"))
async def cb_delete(query: CallbackQuery, db: Database) -> None:
    cb = parse(query.data)
    ok = await db.delete_account(cb.int_arg)
    await db.audit(query.from_user.id, "account_delete", f"#{cb.arg}")
    await query.answer("اکانت حذف شد." if ok else "اکانت پیدا نشد.", show_alert=True)
    await render_list(query, db, 1)


# ══════════════════════════════════════════════════════════════════
#  ورود با شمارهٔ تلفن — از طریق سرویس پل EitaaBun
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == f"{NS_ACCOUNT}:addphone")
async def cb_add_phone(query: CallbackQuery, state: FSMContext) -> None:
    if not config.bridge_ready:
        await safe_edit(
            query,
            error_view("ورود با شمارهٔ تلفن پیکربندی نشده است.", BRIDGE_HINT),
            kb.back_only(pack(NS_ACCOUNT, "list", 1)),
        )
        await query.answer()
        return

    await state.set_state(AddAccount.waiting_phone)
    await safe_edit(
        query,
        "📱 <b>ورود با شمارهٔ تلفن</b>\n"
        "━━━━━━━━━━━━━━\n"
        "شمارهٔ موبایل حساب ایتا را بفرستید.\n\n"
        "<code>+989121234567</code>\n"
        "یا\n"
        "<code>09121234567</code>\n\n"
        "<blockquote>کد تأیید به همین شماره در «ایتا» ارسال می‌شود. "
        "شمارهٔ شما رمزنگاری‌شده ذخیره می‌شود و هرگز کامل نمایش داده "
        "نمی‌شود.</blockquote>\n\n"
        "برای لغو: /cancel",
        kb.back_only(pack(NS_ACCOUNT, "list", 1)),
    )
    await query.answer()


def _normalize_phone(raw: str) -> str:
    """تبدیل 09xxxxxxxxx به +989xxxxxxxxx بدون حدس‌زدن کشور برای بقیه."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = "+98" + digits[1:]
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits


@router.message(AddAccount.waiting_phone)
async def on_phone(message: Message, state: FSMContext) -> None:
    phone = _normalize_phone(message.text or "")
    if not PHONE_RE.match(phone):
        await message.answer(
            error_view(
                "شمارهٔ تلفن معتبر نیست.",
                "نمونهٔ درست: +989121234567 یا 09121234567",
            )
        )
        return

    status = await message.answer(loading_view("در حال ارسال کد تأیید..."))
    try:
        data = await send_login_code(config.bridge_url, phone)
    except EitaaError as exc:
        await status.edit_text(
            error_view("ارسال کد تأیید انجام نشد.", exc.message),
            reply_markup=kb.retry_menu(
                pack(NS_ACCOUNT, "addphone"), pack(NS_ACCOUNT, "list", 1)
            ),
        )
        return

    await state.update_data(
        phone=phone,
        phone_hash=str(data.get("phone_hash", "")),
        imei=str(data.get("imei", "")),
    )
    await state.set_state(AddAccount.waiting_code)
    await status.edit_text(
        "🔑 <b>کد تأیید</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"کد به شمارهٔ <b>{mask_phone(phone)}</b> ارسال شد.\n\n"
        "کد دریافتی را بفرستید (فقط عدد).\n\n"
        "برای لغو: /cancel",
        reply_markup=kb.back_only(pack(NS_ACCOUNT, "list", 1)),
    )


@router.message(AddAccount.waiting_code)
async def on_code(message: Message, state: FSMContext) -> None:
    code = re.sub(r"\D", "", message.text or "")
    if not code:
        await message.answer("کد باید فقط عدد باشد. دوباره بفرستید.")
        return

    data = await state.get_data()
    phone = data.get("phone", "")
    status = await message.answer(loading_view("در حال بررسی کد..."))

    try:
        await confirm_login_code(config.bridge_url, phone, code)
    except EitaaError as exc:
        if "SESSION_PASSWORD_NEEDED" in exc.technical:
            await state.set_state(AddAccount.waiting_password)
            await status.edit_text(
                "🔐 <b>رمز دومرحله‌ای</b>\n"
                "━━━━━━━━━━━━━━\n"
                "این حساب رمز دومرحله‌ای دارد. رمز را بفرستید.\n\n"
                "<blockquote>رمز فقط برای ساخت نشست استفاده می‌شود و "
                "ذخیره نمی‌گردد.</blockquote>\n\n"
                "برای لغو: /cancel",
                reply_markup=kb.back_only(pack(NS_ACCOUNT, "list", 1)),
            )
            return
        await status.edit_text(
            error_view("ورود انجام نشد.", exc.message),
            reply_markup=kb.retry_menu(
                pack(NS_ACCOUNT, "addphone"), pack(NS_ACCOUNT, "list", 1)
            ),
        )
        return

    await state.set_state(AddAccount.waiting_label)
    await status.edit_text(
        "✅ ورود موفق بود.\n\nیک <b>نام نمایشی</b> برای این اکانت بفرستید."
    )


@router.message(AddAccount.waiting_password)
async def on_password(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    if not password:
        await message.answer("رمز خالی است. دوباره بفرستید.")
        return

    # پیام حاوی رمز بلافاصله حذف می‌شود
    try:
        await message.delete()
    except Exception:  # noqa: BLE001 — حذف نشدن نباید جریان را بشکند
        pass

    data = await state.get_data()
    phone = data.get("phone", "")
    status = await message.answer(loading_view("در حال بررسی رمز..."))

    try:
        await confirm_login_password(config.bridge_url, phone, password)
    except EitaaError as exc:
        await status.edit_text(
            error_view("رمز پذیرفته نشد.", exc.message),
            reply_markup=kb.retry_menu(
                pack(NS_ACCOUNT, "addphone"), pack(NS_ACCOUNT, "list", 1)
            ),
        )
        return

    await state.set_state(AddAccount.waiting_label)
    await status.edit_text(
        "✅ ورود موفق بود.\n\nیک <b>نام نمایشی</b> برای این اکانت بفرستید."
    )
