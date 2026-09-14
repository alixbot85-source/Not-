"""مدل‌های دادهٔ منطقی + وضعیت‌های استاندارد (بخش ۱۷ و ۲۹)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ══════════════════════════════════════════════════════════════════
#  وضعیت‌های استاندارد — بخش ۱۷
# ══════════════════════════════════════════════════════════════════
class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def label(self) -> str:
        return {
            JobStatus.PENDING: "🟡 در انتظار",
            JobStatus.RUNNING: "🔄 در حال اجرا",
            JobStatus.STOPPING: "⏳ در حال توقف",
            JobStatus.STOPPED: "⏹ متوقف شد",
            JobStatus.COMPLETED: "✅ تکمیل شد",
            JobStatus.FAILED: "❌ ناموفق",
            JobStatus.CANCELLED: "🚫 لغو شد",
        }[self]

    @property
    def is_final(self) -> bool:
        return self in {
            JobStatus.STOPPED,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }


class JobType(str, Enum):
    JOINER = "JOINER"
    SENDER = "SENDER"
    EXTRACT = "EXTRACT"

    @property
    def label(self) -> str:
        return {
            JobType.JOINER: "📥 Joiner",
            JobType.SENDER: "📤 Sender",
            JobType.EXTRACT: "🔎 استخراج لینک",
        }[self]


class LogLevel(str, Enum):
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    DEBUG = "DEBUG"

    @property
    def icon(self) -> str:
        return {
            LogLevel.INFO: "ℹ️",
            LogLevel.SUCCESS: "✅",
            LogLevel.WARNING: "⚠️",
            LogLevel.ERROR: "❌",
            LogLevel.DEBUG: "🐞",
        }[self]


class AccountStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    ONLINE = "ONLINE"
    INVALID = "INVALID"
    ERROR = "ERROR"

    @property
    def label(self) -> str:
        return {
            AccountStatus.UNKNOWN: "⚪️ بررسی‌نشده",
            AccountStatus.ONLINE: "🟢 آنلاین",
            AccountStatus.INVALID: "🔴 نامعتبر",
            AccountStatus.ERROR: "🟠 خطا",
        }[self]


class AccountKind(str, Enum):
    """
    نوع پشتیبان اکانت — تعیین‌کنندهٔ قابلیت‌های واقعی.

    BOT_API : توکن eitaayar.ir از طریق کتابخانهٔ eitaapy — فقط ارسال.
    MTPROTO : نشست کاربری MTProto از طریق فریم‌ورک pyeitaa — Join و Dialogs.
              (وضعیت در دسترس بودن در زمان اجرا بررسی می‌شود؛ هرگز شبیه‌سازی نمی‌شود.)
    BRIDGE  : نشست کاربری واقعی از طریق سرویس EitaaBun (ورود با شمارهٔ تلفن).
    """

    BOT_API = "BOT_API"
    MTPROTO = "MTPROTO"
    BRIDGE = "BRIDGE"

    @property
    def label(self) -> str:
        return {
            AccountKind.BOT_API: "🤖 توکن ایتایار",
            AccountKind.MTPROTO: "👤 نشست کاربری",
            AccountKind.BRIDGE: "📱 ورود با شماره",
        }[self]


class LinkKind(str, Enum):
    """طبقه‌بندی لینک — «Unknown» یعنی قطعی تشخیص داده نشد (بخش ۶، حدس ممنوع)."""

    GROUP = "GROUP"
    CHANNEL = "CHANNEL"
    USER = "USER"
    INVITE = "INVITE"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        return {
            LinkKind.GROUP: "👥 گروه",
            LinkKind.CHANNEL: "📢 کانال",
            LinkKind.USER: "👤 کاربر",
            LinkKind.INVITE: "🔗 لینک دعوت",
            LinkKind.UNKNOWN: "❔ نامشخص",
        }[self]


class TargetKind(str, Enum):
    GROUPS = "GROUPS"
    CONTACTS = "CONTACTS"
    PRIVATE = "PRIVATE"
    MANUAL = "MANUAL"

    @property
    def label(self) -> str:
        return {
            TargetKind.GROUPS: "👥 گروه‌ها",
            TargetKind.CONTACTS: "👤 مخاطبین",
            TargetKind.PRIVATE: "💬 چت‌های خصوصی",
            TargetKind.MANUAL: "✍️ مقصد دستی",
        }[self]


class ItemStatus(str, Enum):
    """نتیجهٔ پردازش یک آیتم (یک گروه برای Join یا یک مقصد برای Send)."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    ALREADY = "ALREADY"
    FAILED = "FAILED"
    INVALID = "INVALID"
    SKIPPED = "SKIPPED"

    @property
    def label(self) -> str:
        return {
            ItemStatus.PENDING: "⏳ در انتظار",
            ItemStatus.SUCCESS: "✅ موفق",
            ItemStatus.ALREADY: "⚠️ قبلاً انجام شده",
            ItemStatus.FAILED: "❌ ناموفق",
            ItemStatus.INVALID: "🚫 نامعتبر",
            ItemStatus.SKIPPED: "⏭ رد شد",
        }[self]


# ══════════════════════════════════════════════════════════════════
#  رکوردها
# ══════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class Account:
    id: int
    label: str
    kind: AccountKind
    status: AccountStatus
    identity: str = ""          # نام نمایشی امن (هرگز شامل راز نیست)
    status_note: str = ""
    last_checked: str | None = None
    created_at: str = ""

    @property
    def display(self) -> str:
        return f"Account #{self.id:02d} — {self.label}"

    @property
    def can_join(self) -> bool:
        """Join فقط با نشست کاربری واقعی ممکن است، نه با توکن."""
        return self.kind in {AccountKind.MTPROTO, AccountKind.BRIDGE}

    @property
    def can_send(self) -> bool:
        return True


@dataclass(slots=True)
class Linkdoni:
    id: int
    url: str
    title: str = ""
    selected: bool = False
    is_default: bool = False
    last_status: str = ""
    created_at: str = ""


@dataclass(slots=True)
class Job:
    id: int
    type: JobType
    account_id: int | None
    status: JobStatus
    total: int = 0
    processed: int = 0
    success: int = 0
    already: int = 0
    failed: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    recoverable: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str = ""

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return min(100, int(self.processed * 100 / self.total))


@dataclass(slots=True)
class JobItem:
    id: int
    job_id: int
    ref: str
    title: str
    status: ItemStatus
    reason: str = ""


@dataclass(slots=True)
class JobLog:
    id: int
    job_id: int
    level: LogLevel
    message: str
    created_at: str


@dataclass(slots=True)
class ExtractedLink:
    id: int
    job_id: int
    url: str
    kind: LinkKind
    source: str = ""
