"""
متن‌های رابط کاربری با فرمت واقعی Telegram Bot API (HTML parse mode).

تگ‌های استفاده‌شده همگی در مستندات رسمی Bot API تأیید شده‌اند:
  <b> <i> <u> <s> <code> <pre> <a> <tg-spoiler> <blockquote> <blockquote expandable>

از تگ‌های غیرواقعی (جدول، رنگ، هدینگ) استفاده نشده است.
جدول‌ها با <pre> به‌صورت متن هم‌عرض شبیه‌سازی می‌شوند.
"""
from __future__ import annotations

import re
from html import escape

from app.db.models import (
    Account,
    AccountStatus,
    ItemStatus,
    Job,
    JobStatus,
    JobType,
    LinkKind,
)

SEP = "━━━━━━━━━━━━━━"


def esc(value: object) -> str:
    """امن‌سازی متن برای parse_mode=HTML — الزامی طبق مستندات Bot API."""
    return escape(str(value), quote=False)


# تگ‌هایی که مستندات رسمی Bot API صراحتاً پشتیبانی می‌کند
ALLOWED_HTML_TAGS: frozenset[str] = frozenset(
    {
        "b", "strong",
        "i", "em",
        "u", "ins",
        "s", "strike", "del",
        "span",            # فقط با class="tg-spoiler"
        "tg-spoiler",
        "a",
        "code", "pre",
        "blockquote",
        "tg-emoji",
    }
)

_TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9\-]*)([^>]*)>")


def validate_telegram_html(text: str) -> str:
    """
    اعتبارسنجی محلی قالب‌بندی HTML طبق قواعد واقعی Bot API.

    خروجی: پیام خطا به فارسی، یا رشتهٔ خالی اگر معتبر باشد.
    این بررسی جای اعتبارسنجی نهایی سرور را نمی‌گیرد، اما جلوی
    خطاهای رایج را پیش از ارسال می‌گیرد.
    """
    stack: list[str] = []
    for match in _TAG_RE.finditer(text):
        closing, name, attrs = match.group(1), match.group(2).lower(), match.group(3)

        if name not in ALLOWED_HTML_TAGS:
            return f"تگ «{name}» در Bot API پشتیبانی نمی‌شود."

        if closing:
            if not stack:
                return f"تگ بستهٔ «{name}» بدون تگ باز است."
            if stack[-1] != name:
                return f"ترتیب تگ‌ها درست نیست: انتظار </{stack[-1]}> بود، </{name}> آمد."
            stack.pop()
            continue

        if name == "a" and "href" not in attrs.lower():
            return "تگ <a> باید ویژگی href داشته باشد."
        if name == "span" and "tg-spoiler" not in attrs.lower():
            return 'تگ <span> فقط با class="tg-spoiler" مجاز است.'
        if name == "tg-emoji" and "emoji-id" not in attrs.lower():
            return "تگ <tg-emoji> باید ویژگی emoji-id داشته باشد."
        stack.append(name)

    if stack:
        return f"تگ «{stack[-1]}» بسته نشده است."
    return ""


def bar(percent: int, width: int = 10) -> str:
    """نوار پیشرفت با کاراکترهای بلوک."""
    percent = max(0, min(100, percent))
    filled = round(percent * width / 100)
    return "█" * filled + "░" * (width - filled)


def fa_num(value: object) -> str:
    """جداکنندهٔ هزارگان برای خوانایی."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


# ══════════════════════════════════════════════════════════════════
#  صفحات اصلی
# ══════════════════════════════════════════════════════════════════
def main_panel(name: str, accounts: int, linkdoni: int, jobs: int) -> str:
    return (
        "🏠 <b>پنل اصلی</b>\n"
        f"{SEP}\n"
        f"سلام <b>{esc(name)}</b> 👋\n\n"
        "<blockquote>مدیریت اکانت‌های ایتا از طریق این پنل انجام می‌شود. "
        "ربات تلگرام فقط نقش کنترل را دارد و عملیات روی ایتا اجرا می‌شود.</blockquote>\n\n"
        f"👤 اکانت‌ها: <b>{fa_num(accounts)}</b>\n"
        f"🔗 لینکدونی: <b>{fa_num(linkdoni)}</b>\n"
        f"📊 عملیات‌ها: <b>{fa_num(jobs)}</b>\n\n"
        "<i>یک بخش را انتخاب کنید:</i>"
    )


def accounts_header(total: int, page: int, pages: int) -> str:
    return (
        "👤 <b>مدیریت اکانت‌ها</b>\n"
        f"{SEP}\n"
        f"مجموع: <b>{fa_num(total)}</b> اکانت — صفحهٔ {page}/{pages}\n\n"
        "<i>برای دیدن جزئیات، روی اکانت بزنید.</i>"
    )


def accounts_empty() -> str:
    return (
        "👤 <b>مدیریت اکانت‌ها</b>\n"
        f"{SEP}\n"
        "📭 هنوز اکانتی اضافه نشده است.\n\n"
        "<blockquote>برای شروع، یک اکانت اضافه کنید. "
        "اطلاعات حساس به‌صورت رمزشده ذخیره می‌شود و هرگز نمایش داده نمی‌شود.</blockquote>"
    )


def account_detail(account: Account, caps: list[tuple[str, str]]) -> str:
    lines = [
        f"<b>Account #{account.id:02d}</b>",
        SEP,
        f"نام: <b>{esc(account.label)}</b>",
        f"نوع: {esc(account.kind.label)}",
        f"وضعیت: {esc(account.status.label)}",
    ]
    if account.identity:
        lines.append(f"شناسه: <code>{esc(account.identity)}</code>")
    if account.status_note:
        lines.append(f"یادداشت: <i>{esc(account.status_note)}</i>")
    if account.last_checked:
        lines.append(f"آخرین بررسی: <code>{esc(account.last_checked[:19])}</code>")
    lines.append("")
    lines.append("<b>قابلیت‌ها</b>")
    for title, status in caps:
        lines.append(f"• {esc(title)}: {esc(status)}")
    lines.append("")
    lines.append("<tg-spoiler>اطلاعات محرمانه هرگز نمایش داده نمی‌شود.</tg-spoiler>")
    return "\n".join(lines)


def linkdoni_header(total: int, selected: int, page: int, pages: int) -> str:
    return (
        "🔗 <b>مدیریت لینکدونی</b>\n"
        f"{SEP}\n"
        f"مجموع: <b>{fa_num(total)}</b> — انتخاب‌شده: <b>{fa_num(selected)}</b>\n"
        f"صفحهٔ {page}/{pages}\n\n"
        "<i>با زدن روی هر مورد، انتخاب آن جابه‌جا می‌شود.</i>"
    )


def linkdoni_empty() -> str:
    return (
        "🔗 <b>مدیریت لینکدونی</b>\n"
        f"{SEP}\n"
        "📭 هیچ لینکدونی‌ای وجود ندارد.\n\n"
        "<blockquote>لینکدونی‌ها منبع استخراج لینک گروه‌ها هستند.</blockquote>"
    )


# ══════════════════════════════════════════════════════════════════
#  Joiner
# ══════════════════════════════════════════════════════════════════
def extraction_report(
    checked: int, found: int, duplicates: int, invalid: int, kinds: dict[LinkKind, int], ready: int
) -> str:
    rows = "\n".join(
        f"{kind.label:<12} {fa_num(count)}" for kind, count in kinds.items() if count
    )
    return (
        "🔗 <b>استخراج کامل شد</b>\n"
        f"{SEP}\n"
        f"لینکدونی بررسی‌شده: <b>{fa_num(checked)}</b>\n"
        f"لینک یافت‌شده: <b>{fa_num(found)}</b>\n"
        f"تکراری: <b>{fa_num(duplicates)}</b>\n"
        f"نامعتبر: <b>{fa_num(invalid)}</b>\n\n"
        + (f"<pre>{esc(rows)}</pre>\n" if rows else "")
        + f"\n✅ آمادهٔ عضویت: <b>{fa_num(ready)}</b>\n\n"
        + (
            "<blockquote>فقط لینک‌هایی که نوعشان قطعی تشخیص داده شده برای عضویت "
            "استفاده می‌شوند. موارد نامشخص کنار گذاشته می‌شوند.</blockquote>"
            if ready
            else "<i>موردی برای عضویت پیدا نشد.</i>"
        )
    )


def progress_view(
    *,
    title: str,
    account: str,
    job_id: int,
    total: int,
    processed: int,
    success: int,
    already: int,
    failed: int,
    current: str,
    status: JobStatus,
    paused: bool = False,
) -> str:
    percent = int(processed * 100 / total) if total else 0
    state = "⏸ موقتاً متوقف" if paused else status.label
    return (
        f"{title}\n"
        f"{SEP}\n"
        f"عملیات: <code>#{job_id}</code>\n"
        f"اکانت: <b>{esc(account)}</b>\n\n"
        f"<b>پیشرفت</b>\n"
        f"<code>{bar(percent)}</code> {percent}%\n"
        f"پردازش‌شده: <b>{fa_num(processed)}</b> / {fa_num(total)}\n\n"
        f"✅ موفق: <b>{fa_num(success)}</b>\n"
        f"⚠️ قبلاً: <b>{fa_num(already)}</b>\n"
        f"❌ ناموفق: <b>{fa_num(failed)}</b>\n\n"
        f"<b>مورد جاری</b>\n"
        f"<code>{esc(current or '—')}</code>\n\n"
        f"وضعیت: {esc(state)}"
    )


def job_report(job: Job, duration: str) -> str:
    icon = "✅" if job.status is JobStatus.COMPLETED else "⏹"
    return (
        f"{icon} <b>گزارش عملیات #{job.id}</b>\n"
        f"{SEP}\n"
        f"نوع: {esc(job.type.label)}\n"
        f"وضعیت: {esc(job.status.label)}\n\n"
        f"مجموع: <b>{fa_num(job.total)}</b>\n"
        f"✅ موفق: <b>{fa_num(job.success)}</b>\n"
        f"⚠️ قبلاً: <b>{fa_num(job.already)}</b>\n"
        f"❌ ناموفق: <b>{fa_num(job.failed)}</b>\n\n"
        f"مدت زمان: <code>{esc(duration)}</code>"
        + (
            f"\n\n<blockquote expandable>دلیل خطا:\n{esc(job.error)}</blockquote>"
            if job.error
            else ""
        )
    )


def job_row(job: Job) -> str:
    return f"#{job.id} {job.type.label} — {job.status.label} ({job.percent}%)"


def job_detail(job: Job, account_label: str) -> str:
    return (
        f"<b>JOB #{job.id}</b>\n"
        f"{SEP}\n"
        f"نوع: {esc(job.type.label)}\n"
        f"اکانت: <b>{esc(account_label)}</b>\n"
        f"وضعیت: {esc(job.status.label)}\n\n"
        f"<code>{bar(job.percent)}</code> {job.percent}%\n"
        f"پردازش‌شده: <b>{fa_num(job.processed)}</b> / {fa_num(job.total)}\n"
        f"✅ {fa_num(job.success)}  ⚠️ {fa_num(job.already)}  ❌ {fa_num(job.failed)}\n\n"
        f"ایجاد: <code>{esc(job.created_at[:19])}</code>"
        + (
            "\n\n♻️ <i>این عملیات قابل ادامه است.</i>"
            if job.recoverable
            else ""
        )
    )


# ══════════════════════════════════════════════════════════════════
#  Sender
# ══════════════════════════════════════════════════════════════════
def message_preview(
    text: str,
    parse_mode: str,
    target: str,
    account: str,
    count: int,
    media_name: str = "",
    media_supported: bool = True,
) -> str:
    body = text if parse_mode == "HTML" else esc(text)
    lines = [
        "📝 <b>پیش‌نمایش پیام</b>",
        SEP,
        body,
        SEP,
        f"مقصد: <b>{esc(target)}</b> ({fa_num(count)} مورد)",
        f"اکانت: <b>{esc(account)}</b>",
        f"قالب: <code>{esc(parse_mode)}</code>",
    ]
    if media_name:
        lines.append(f"پیوست: <b>{esc(media_name)}</b>")
        if not media_supported:
            lines.append(
                "⚠️ <i>این اکانت از ارسال فایل پشتیبانی نمی‌کند؛ فقط متن ارسال می‌شود.</i>"
            )
    return "\n".join(lines)


def targets_summary(groups: int, contacts: int, private: int, manual: int) -> str:
    return (
        "🎯 <b>مقصدهای ارسال</b>\n"
        f"{SEP}\n"
        f"👥 گروه‌ها: <b>{fa_num(groups)}</b>\n"
        f"👤 مخاطبین: <b>{fa_num(contacts)}</b>\n"
        f"💬 چت‌های خصوصی: <b>{fa_num(private)}</b>\n"
        f"✍️ دستی: <b>{fa_num(manual)}</b>\n\n"
        "<i>یک مقصد را انتخاب کنید.</i>"
    )


def composer_view(text: str, parse_mode: str, media_name: str = "") -> str:
    preview = text.strip() or "<i>هنوز متنی ثبت نشده است.</i>"
    media_line = (
        f"پیوست: <b>{esc(media_name)}</b>\n"
        if media_name
        else "پیوست: <i>ندارد</i>\n"
    )
    return (
        "📝 <b>ویرایشگر پیام</b>\n"
        f"{SEP}\n"
        f"قالب فعلی: <code>{esc(parse_mode)}</code>\n"
        f"{media_line}\n"
        f"<b>متن:</b>\n{preview if parse_mode == 'HTML' else esc(text)}\n\n"
        "<blockquote expandable>قالب‌های پشتیبانی‌شدهٔ Bot API:\n"
        "&lt;b&gt;پررنگ&lt;/b&gt;\n"
        "&lt;i&gt;کج&lt;/i&gt;\n"
        "&lt;u&gt;زیرخط&lt;/u&gt;\n"
        "&lt;s&gt;خط‌خورده&lt;/s&gt;\n"
        "&lt;tg-spoiler&gt;اسپویلر&lt;/tg-spoiler&gt;\n"
        "&lt;code&gt;کد&lt;/code&gt;\n"
        "&lt;pre&gt;بلوک کد&lt;/pre&gt;\n"
        "&lt;a href=\"...\"&gt;لینک&lt;/a&gt;\n"
        "&lt;blockquote&gt;نقل‌قول&lt;/blockquote&gt;</blockquote>"
    )


# ══════════════════════════════════════════════════════════════════
#  حالت‌های عمومی
# ══════════════════════════════════════════════════════════════════
def error_view(reason: str, detail: str = "") -> str:
    return (
        "❌ <b>عملیات انجام نشد</b>\n"
        f"{SEP}\n"
        f"<b>دلیل:</b>\n{esc(reason)}\n"
        + (f"\n<blockquote expandable>{esc(detail)}</blockquote>" if detail else "")
        + "\n\n<i>جزئیات فنی فقط در فایل لاگ ثبت می‌شود.</i>"
    )


def success_view(message: str, detail: str = "") -> str:
    return (
        "✅ <b>انجام شد</b>\n"
        f"{SEP}\n"
        f"{esc(message)}"
        + (f"\n\n<i>{esc(detail)}</i>" if detail else "")
    )


def loading_view(message: str = "در حال پردازش...") -> str:
    return f"⏳ <b>{esc(message)}</b>\n{SEP}\n<i>لطفاً چند لحظه صبر کنید.</i>"


def confirm_view(question: str, warning: str = "") -> str:
    return (
        "⚠️ <b>تأیید عملیات</b>\n"
        f"{SEP}\n"
        f"{esc(question)}"
        + (f"\n\n<blockquote>{esc(warning)}</blockquote>" if warning else "")
    )


def logs_view(job_id: int, rows: list[tuple[str, str, str]], page: int, pages: int) -> str:
    if not rows:
        return f"📋 <b>لاگ عملیات #{job_id}</b>\n{SEP}\n📭 لاگی ثبت نشده است."
    body = "\n".join(f"{time} {icon} {esc(msg)}" for time, icon, msg in rows)
    return (
        f"📋 <b>لاگ عملیات #{job_id}</b>\n"
        f"{SEP}\n"
        f"<blockquote expandable>{body}</blockquote>\n"
        f"صفحهٔ {page}/{pages}"
    )


def item_line(status: ItemStatus, title: str) -> str:
    return f"{status.label} — {esc(title)}"


def job_type_title(job_type: JobType) -> str:
    return {
        JobType.JOINER: "📥 <b>JOINER</b>",
        JobType.SENDER: "📤 <b>SENDER</b>",
        JobType.EXTRACT: "🔎 <b>استخراج لینک</b>",
    }[job_type]


def account_status_icon(status: AccountStatus) -> str:
    return {
        AccountStatus.ONLINE: "🟢",
        AccountStatus.INVALID: "🔴",
        AccountStatus.ERROR: "🟠",
        AccountStatus.UNKNOWN: "⚪️",
    }[status]
