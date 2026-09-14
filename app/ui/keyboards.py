"""
سازندهٔ کیبوردهای Inline (بخش ۱۵ و ۱۶).

فقط از انواع دکمهٔ واقعی Bot API استفاده می‌شود:
  • callback_data  • url  • copy_text
هیچ قابلیت غیرواقعی (مثل رنگ دلخواه) استفاده نشده است.
"""
from __future__ import annotations

from math import ceil

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Account, Job, Linkdoni
from app.ui.callbacks import (
    HOME,
    NOOP,
    NS_ACCOUNT,
    NS_AI,
    NS_EXPORT,
    NS_JOB,
    NS_JOINER,
    NS_LINKDONI,
    NS_SENDER,
    NS_SETTINGS,
    pack,
)
from app.ui.texts import account_status_icon

Row = list[InlineKeyboardButton]


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _kb(rows: list[Row]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nav_row(back: str | None = None, home: bool = True) -> Row:
    """ردیف ناوبری استاندارد — در تمام صفحات مهم حاضر است."""
    row: Row = []
    if back:
        row.append(_btn("🔙 بازگشت", back))
    if home:
        row.append(_btn("🏠 خانه", HOME))
    return row


def pagination_row(namespace: str, action: str, page: int, pages: int, arg: str = "") -> Row:
    """
    ردیف صفحه‌بندی: ◀️ قبلی | صفحهٔ x / y | بعدی ▶️
    فقط وقتی نمایش داده می‌شود که بیش از یک صفحه باشد.
    """
    if pages <= 1:
        return []
    prev_page = page - 1 if page > 1 else pages
    next_page = page + 1 if page < pages else 1
    return [
        _btn("◀️ قبلی", pack(namespace, action, prev_page, arg)),
        _btn(f"{page} / {pages}", NOOP),
        _btn("بعدی ▶️", pack(namespace, action, next_page, arg)),
    ]


def page_count(total: int, size: int) -> int:
    return max(1, ceil(total / size)) if size else 1


# ══════════════════════════════════════════════════════════════════
#  منوی اصلی
# ══════════════════════════════════════════════════════════════════
def main_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [_btn("👤 مدیریت اکانت‌ها", pack(NS_ACCOUNT, "list", 1))],
            [
                _btn("📥 Joiner", pack(NS_JOINER, "menu")),
                _btn("📤 Sender", pack(NS_SENDER, "menu")),
            ],
            [_btn("🔗 لینکدونی", pack(NS_LINKDONI, "list", 1))],
            [_btn("📊 عملیات‌ها و گزارش‌ها", pack(NS_JOB, "list", 1))],
            [_btn("⚙️ تنظیمات", pack(NS_SETTINGS, "menu"))],
        ]
    )


# ══════════════════════════════════════════════════════════════════
#  اکانت‌ها
# ══════════════════════════════════════════════════════════════════
def accounts_menu(
    accounts: list[Account], page: int, pages: int, empty: bool
) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    if empty:
        rows.append([_btn("➕ افزودن اکانت", pack(NS_ACCOUNT, "add"))])
        rows.append(nav_row(home=True))
        return _kb(rows)

    for acc in accounts:
        rows.append(
            [
                _btn(
                    f"{account_status_icon(acc.status)} #{acc.id:02d} {acc.label[:22]}",
                    pack(NS_ACCOUNT, "view", acc.id),
                )
            ]
        )
    pagination = pagination_row(NS_ACCOUNT, "list", page, pages)
    if pagination:
        rows.append(pagination)
    rows.append(
        [
            _btn("➕ افزودن", pack(NS_ACCOUNT, "add")),
            _btn("🔄 بررسی وضعیت", pack(NS_ACCOUNT, "checkall")),
        ]
    )
    rows.append(nav_row(home=True))
    return _kb(rows)


def account_detail_menu(account_id: int) -> InlineKeyboardMarkup:
    return _kb(
        [
            [_btn("🔄 بررسی وضعیت", pack(NS_ACCOUNT, "check", account_id))],
            [_btn("🗑 حذف اکانت", pack(NS_ACCOUNT, "delask", account_id))],
            nav_row(back=pack(NS_ACCOUNT, "list", 1)),
        ]
    )


def account_add_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [_btn("📱 ورود با شمارهٔ تلفن", pack(NS_ACCOUNT, "addphone"))],
            [_btn("🤖 توکن ایتایار", pack(NS_ACCOUNT, "addtok"))],
            [_btn("👤 نشست کاربری (MTProto)", pack(NS_ACCOUNT, "addses"))],
            nav_row(back=pack(NS_ACCOUNT, "list", 1)),
        ]
    )


def confirm_menu(yes_data: str, no_data: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [_btn("✅ بله، انجام بده", yes_data), _btn("❌ انصراف", no_data)],
        ]
    )


# ══════════════════════════════════════════════════════════════════
#  لینکدونی
# ══════════════════════════════════════════════════════════════════
def linkdoni_menu(
    items: list[Linkdoni], page: int, pages: int, empty: bool
) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    if empty:
        rows.append([_btn("➕ افزودن لینکدونی", pack(NS_LINKDONI, "add"))])
        rows.append([_btn("🔄 بازیابی پیش‌فرض‌ها", pack(NS_LINKDONI, "seed"))])
        rows.append(nav_row(home=True))
        return _kb(rows)

    for item in items:
        mark = "☑️" if item.selected else "☐"
        name = item.title or item.url.split("/")[-1]
        rows.append(
            [
                _btn(f"{mark} {name[:24]}", pack(NS_LINKDONI, "tgl", item.id, page)),
                _btn("🗑", pack(NS_LINKDONI, "delask", item.id, page)),
            ]
        )
    pagination = pagination_row(NS_LINKDONI, "list", page, pages)
    if pagination:
        rows.append(pagination)
    rows.append(
        [
            _btn("☑️ انتخاب همه", pack(NS_LINKDONI, "all", page)),
            _btn("☐ لغو انتخاب", pack(NS_LINKDONI, "none", page)),
        ]
    )
    rows.append(
        [
            _btn("➕ افزودن", pack(NS_LINKDONI, "add")),
            _btn("🔄 تازه‌سازی", pack(NS_LINKDONI, "list", page)),
        ]
    )
    rows.append(nav_row(home=True))
    return _kb(rows)


# ══════════════════════════════════════════════════════════════════
#  Joiner
# ══════════════════════════════════════════════════════════════════
def joiner_menu(ready: bool) -> InlineKeyboardMarkup:
    rows: list[Row] = [[_btn("👤 انتخاب اکانت", pack(NS_JOINER, "accs", 1))]]
    if ready:
        rows.append([_btn("🔗 انتخاب لینکدونی", pack(NS_LINKDONI, "list", 1))])
        rows.append([_btn("▶️ شروع استخراج", pack(NS_JOINER, "extract"))])
    rows.append(nav_row(home=True))
    return _kb(rows)


def select_account_menu(
    accounts: list[Account], page: int, pages: int, namespace: str, action: str = "pick"
) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    for acc in accounts:
        rows.append(
            [
                _btn(
                    f"{account_status_icon(acc.status)} #{acc.id:02d} {acc.label[:22]}",
                    pack(namespace, action, acc.id),
                )
            ]
        )
    if not accounts:
        rows.append([_btn("➕ افزودن اکانت", pack(NS_ACCOUNT, "add"))])
    pagination = pagination_row(namespace, "accs", page, pages)
    if pagination:
        rows.append(pagination)
    rows.append(nav_row(back=pack(namespace, "menu")))
    return _kb(rows)


def extraction_menu(has_targets: bool, job_id: int) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    if has_targets:
        rows.append([_btn("▶️ شروع عضویت", pack(NS_JOINER, "start", job_id))])
    rows.append([_btn("📄 خروجی لینک‌ها", pack(NS_EXPORT, "menu", job_id))])
    rows.append(nav_row(back=pack(NS_JOINER, "menu")))
    return _kb(rows)


def running_menu(job_id: int, paused: bool, can_pause: bool = True) -> InlineKeyboardMarkup:
    """کنترل Job در حال اجرا — Pause واقعی است چون وضعیت در DB ذخیره می‌شود."""
    row: Row = []
    if can_pause:
        row.append(
            _btn("▶️ ادامه", pack(NS_JOB, "resume", job_id))
            if paused
            else _btn("⏸ توقف موقت", pack(NS_JOB, "pause", job_id))
        )
    row.append(_btn("⏹ توقف", pack(NS_JOB, "stop", job_id)))
    return _kb([row, [_btn("🔄 به‌روزرسانی", pack(NS_JOB, "view", job_id))]])


def report_menu(job_id: int, has_failed: bool) -> InlineKeyboardMarkup:
    rows: list[Row] = [
        [
            _btn("📄 خروجی", pack(NS_EXPORT, "menu", job_id)),
            _btn("📋 لاگ‌ها", pack(NS_JOB, "logs", job_id, 1)),
        ]
    ]
    if has_failed:
        rows.append([_btn("🔄 تلاش مجدد ناموفق‌ها", pack(NS_JOB, "retry", job_id))])
    rows.append(nav_row(back=pack(NS_JOB, "list", 1)))
    return _kb(rows)


# ══════════════════════════════════════════════════════════════════
#  Sender
# ══════════════════════════════════════════════════════════════════
def sender_menu(has_account: bool, has_text: bool, has_target: bool) -> InlineKeyboardMarkup:
    rows: list[Row] = [
        [_btn(f"{'✅' if has_account else '👤'} انتخاب اکانت", pack(NS_SENDER, "accs", 1))],
        [_btn(f"{'✅' if has_text else '📝'} متن پیام", pack(NS_SENDER, "compose"))],
        [_btn(f"{'✅' if has_target else '🎯'} مقصدها", pack(NS_SENDER, "targets"))],
    ]
    if has_account and has_text and has_target:
        rows.append([_btn("👁 پیش‌نمایش و ارسال", pack(NS_SENDER, "preview"))])
    rows.append([_btn("📊 آمار ارسال", pack(NS_SENDER, "stats"))])
    rows.append(nav_row(home=True))
    return _kb(rows)


def composer_menu(ai_ready: bool, has_media: bool = False) -> InlineKeyboardMarkup:
    rows: list[Row] = [
        [_btn("✏️ ویرایش متن", pack(NS_SENDER, "edit"))],
        [
            _btn("🎨 قالب: HTML", pack(NS_SENDER, "pm", "HTML")),
            _btn("متن ساده", pack(NS_SENDER, "pm", "NONE")),
        ],
        [
            _btn("🗑 حذف پیوست", pack(NS_SENDER, "media", "clear"))
            if has_media
            else _btn("📎 افزودن پیوست", pack(NS_SENDER, "media", "add"))
        ],
    ]
    if ai_ready:
        rows.append([_btn("🧠 دستیار هوشمند", pack(NS_AI, "menu"))])
    rows.append(nav_row(back=pack(NS_SENDER, "menu")))
    return _kb(rows)


def targets_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [_btn("👥 گروه‌ها", pack(NS_SENDER, "target", "GROUPS"))],
            [_btn("👤 مخاطبین", pack(NS_SENDER, "target", "CONTACTS"))],
            [_btn("💬 چت‌های خصوصی", pack(NS_SENDER, "target", "PRIVATE"))],
            [_btn("✍️ ورود دستی", pack(NS_SENDER, "target", "MANUAL"))],
            nav_row(back=pack(NS_SENDER, "menu")),
        ]
    )


def preview_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                _btn("✅ تأیید و ارسال", pack(NS_SENDER, "start")),
                _btn("✏️ ویرایش", pack(NS_SENDER, "compose")),
            ],
            [_btn("❌ انصراف", pack(NS_SENDER, "menu"))],
        ]
    )


# ══════════════════════════════════════════════════════════════════
#  Jobs / Export / AI / Settings
# ══════════════════════════════════════════════════════════════════
def jobs_menu(jobs: list[Job], page: int, pages: int) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    for job in jobs:
        rows.append(
            [
                _btn(
                    f"#{job.id} {job.type.label} {job.status.label} {job.percent}%",
                    pack(NS_JOB, "view", job.id),
                )
            ]
        )
    if not jobs:
        rows.append([_btn("📥 شروع Joiner", pack(NS_JOINER, "menu"))])
    pagination = pagination_row(NS_JOB, "list", page, pages)
    if pagination:
        rows.append(pagination)
    rows.append(nav_row(home=True))
    return _kb(rows)


def job_detail_menu(job: Job, running: bool, paused: bool, has_failed: bool) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    if running:
        rows.append(
            [
                (
                    _btn("▶️ ادامه", pack(NS_JOB, "resume", job.id))
                    if paused
                    else _btn("⏸ توقف موقت", pack(NS_JOB, "pause", job.id))
                ),
                _btn("⏹ توقف", pack(NS_JOB, "stop", job.id)),
            ]
        )
    elif job.recoverable:
        rows.append([_btn("♻️ ادامهٔ عملیات", pack(NS_JOB, "resumejob", job.id))])
    rows.append(
        [
            _btn("📋 لاگ‌ها", pack(NS_JOB, "logs", job.id, 1)),
            _btn("📄 خروجی", pack(NS_EXPORT, "menu", job.id)),
        ]
    )
    if has_failed:
        rows.append([_btn("🔄 تلاش مجدد ناموفق‌ها", pack(NS_JOB, "retry", job.id))])
    rows.append([_btn("🔄 به‌روزرسانی", pack(NS_JOB, "view", job.id))])
    rows.append(nav_row(back=pack(NS_JOB, "list", 1)))
    return _kb(rows)


def export_menu(job_id: int, pdf_ready: bool) -> InlineKeyboardMarkup:
    rows: list[Row] = [
        [
            _btn("TXT", pack(NS_EXPORT, "do", job_id, "txt")),
            _btn("CSV", pack(NS_EXPORT, "do", job_id, "csv")),
            _btn("JSON", pack(NS_EXPORT, "do", job_id, "json")),
        ],
        [
            _btn("XLSX", pack(NS_EXPORT, "do", job_id, "xlsx")),
            (
                _btn("PDF", pack(NS_EXPORT, "do", job_id, "pdf"))
                if pdf_ready
                else _btn("PDF ⚠️", pack(NS_EXPORT, "nopdf", job_id))
            ),
        ],
        nav_row(back=pack(NS_JOB, "view", job_id)),
    ]
    return _kb(rows)


def logs_menu(job_id: int, page: int, pages: int) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    pagination = pagination_row(NS_JOB, "logs", page, pages, str(job_id))
    if pagination:
        rows.append(pagination)
    rows.append(nav_row(back=pack(NS_JOB, "view", job_id)))
    return _kb(rows)


def ai_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                _btn("✏️ بازنویسی", pack(NS_AI, "act", "rewrite")),
                _btn("📉 کوتاه‌سازی", pack(NS_AI, "act", "shorten")),
            ],
            [
                _btn("📈 گسترش", pack(NS_AI, "act", "expand")),
                _btn("📝 خلاصه", pack(NS_AI, "act", "summarize")),
            ],
            [
                _btn("🌐 ترجمه", pack(NS_AI, "act", "translate")),
                _btn("🎨 تغییر لحن", pack(NS_AI, "styles")),
            ],
            nav_row(back=pack(NS_SENDER, "compose")),
        ]
    )


def ai_styles_menu() -> InlineKeyboardMarkup:
    styles = [
        ("حرفه‌ای", "professional"),
        ("دوستانه", "friendly"),
        ("رسمی", "formal"),
        ("تبلیغاتی", "marketing"),
        ("خبری", "news"),
        ("فنی", "technical"),
    ]
    rows: list[Row] = []
    for index in range(0, len(styles), 2):
        rows.append(
            [_btn(label, pack(NS_AI, "style", key)) for label, key in styles[index : index + 2]]
        )
    rows.append(nav_row(back=pack(NS_AI, "menu")))
    return _kb(rows)


def settings_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [_btn("🧩 وضعیت قابلیت‌ها", pack(NS_SETTINGS, "caps"))],
            [_btn("⏱ تأخیر و محدودیت‌ها", pack(NS_SETTINGS, "limits"))],
            [_btn("🛡 گزارش دسترسی", pack(NS_SETTINGS, "audit", 1))],
            nav_row(home=True),
        ]
    )


def back_only(back: str) -> InlineKeyboardMarkup:
    return _kb([nav_row(back=back)])


def retry_menu(retry_data: str, back_data: str) -> InlineKeyboardMarkup:
    """کیبورد حالت خطا — طبق بخش ۲۷ همیشه Retry و Back دارد."""
    return _kb([[_btn("🔄 تلاش مجدد", retry_data)], nav_row(back=back_data)])
