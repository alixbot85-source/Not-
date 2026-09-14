"""
قراردادهای مشترک لایهٔ سرویس ایتا.

این لایه کاملاً از Telegram UI جدا است (بخش دوم معماری).
هیچ متدی در اینجا رفتار کتابخانه را شبیه‌سازی نمی‌کند؛
اگر قابلیتی واقعاً موجود نباشد، `Capability.UNAVAILABLE` برگردانده می‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Capability(str, Enum):
    """وضعیت واقعی یک قابلیت در Backend انتخاب‌شده."""

    AVAILABLE = "AVAILABLE"        # واقعاً پیاده‌سازی شده و قابل فراخوانی است
    UNAVAILABLE = "UNAVAILABLE"    # کتابخانهٔ لازم نصب نیست
    NOT_SUPPORTED = "NOT_SUPPORTED"  # این Backend اصلاً چنین APIای ندارد

    @property
    def label(self) -> str:
        return {
            Capability.AVAILABLE: "✅ در دسترس",
            Capability.UNAVAILABLE: "⚠️ نیازمند نصب",
            Capability.NOT_SUPPORTED: "⛔️ پشتیبانی نمی‌شود",
        }[self]


class EitaaError(Exception):
    """خطای قابل‌نمایش لایهٔ ایتا — پیام آن برای کاربر امن است."""

    def __init__(self, message: str, *, retryable: bool = False, technical: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.technical = technical or message


class EitaaUnavailable(EitaaError):
    """قابلیت واقعاً در دسترس نیست (کتابخانه نصب نشده یا API ندارد)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


@dataclass(slots=True)
class OpResult:
    """نتیجهٔ یک عملیات تکی (Join یا Send)."""

    ok: bool
    already: bool = False
    invalid: bool = False
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, **data: Any) -> "OpResult":
        return cls(ok=True, data=data)

    @classmethod
    def already_done(cls, reason: str = "قبلاً انجام شده است") -> "OpResult":
        return cls(ok=False, already=True, reason=reason)

    @classmethod
    def bad(cls, reason: str) -> "OpResult":
        return cls(ok=False, invalid=True, reason=reason)

    @classmethod
    def failure(cls, reason: str) -> "OpResult":
        return cls(ok=False, reason=reason)


@dataclass(slots=True)
class Target:
    """یک مقصد ارسال یا یک گروه برای Join."""

    ref: str            # username یا لینک یا chat_id
    title: str = ""
    kind: str = "UNKNOWN"


@dataclass(slots=True)
class AccountIdentity:
    """اطلاعات غیرحساس اکانت برای نمایش در UI."""

    name: str
    detail: str = ""


class EitaaBackend:
    """
    رابط مشترک همهٔ Backendهای ایتا.

    پیاده‌سازی‌ها:
      • EitaayarBackend  → کتابخانهٔ واقعی eitaapy (توکن eitaayar.ir)
      • MTProtoBackend   → فریم‌ورک واقعی pyeitaa (نشست کاربری)
    """

    name: str = "base"

    # --- قابلیت‌ها؛ هر Backend مقدار واقعی خود را اعلام می‌کند ---
    can_validate: Capability = Capability.NOT_SUPPORTED
    can_send_text: Capability = Capability.NOT_SUPPORTED
    can_send_media: Capability = Capability.NOT_SUPPORTED
    can_join: Capability = Capability.NOT_SUPPORTED
    can_list_groups: Capability = Capability.NOT_SUPPORTED
    can_list_contacts: Capability = Capability.NOT_SUPPORTED
    can_list_private: Capability = Capability.NOT_SUPPORTED
    can_resolve: Capability = Capability.NOT_SUPPORTED

    async def validate(self) -> AccountIdentity:
        raise EitaaUnavailable("اعتبارسنجی برای این نوع اکانت پشتیبانی نمی‌شود.")

    async def send_text(self, chat: str, text: str) -> OpResult:
        raise EitaaUnavailable("ارسال متن برای این نوع اکانت پشتیبانی نمی‌شود.")

    async def send_media(self, chat: str, file_path: str, caption: str = "") -> OpResult:
        raise EitaaUnavailable("ارسال فایل برای این نوع اکانت پشتیبانی نمی‌شود.")

    async def join(self, ref: str) -> OpResult:
        raise EitaaUnavailable("عضویت در گروه برای این نوع اکانت پشتیبانی نمی‌شود.")

    async def list_groups(self, limit: int = 200) -> list[Target]:
        raise EitaaUnavailable("دریافت فهرست گروه‌ها برای این نوع اکانت پشتیبانی نمی‌شود.")

    async def list_contacts(self, limit: int = 200) -> list[Target]:
        raise EitaaUnavailable("دریافت مخاطبین برای این نوع اکانت پشتیبانی نمی‌شود.")

    async def list_private(self, limit: int = 200) -> list[Target]:
        raise EitaaUnavailable("دریافت چت‌های خصوصی برای این نوع اکانت پشتیبانی نمی‌شود.")

    async def close(self) -> None:
        return None
