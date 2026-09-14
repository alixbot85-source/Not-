"""
سیستم Callback استاندارد (بخش ۱۵).

قالب:  <namespace>:<action>[:<arg>[:<arg2>]]
مثال:  account:view:12 | joiner:page:2 | sender:target:GROUPS

قوانین:
  • کوتاه — محدودیت واقعی Bot API برای callback_data ۶۴ بایت است.
  • بدون Collision — هر namespace جداست.
  • Validation شده — پارس با الگوی سخت‌گیرانه انجام می‌شود.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CALLBACK_BYTES = 64  # محدودیت واقعی Telegram Bot API

_PATTERN = re.compile(r"^[a-z]+(?::[A-Za-z0-9_\-]+){1,3}$")


class CallbackError(ValueError):
    """callback_data نامعتبر یا دستکاری‌شده."""


@dataclass(frozen=True, slots=True)
class CB:
    namespace: str
    action: str
    arg: str = ""
    arg2: str = ""

    def pack(self) -> str:
        parts = [self.namespace, self.action]
        if self.arg:
            parts.append(self.arg)
        if self.arg2:
            parts.append(self.arg2)
        data = ":".join(parts)
        if len(data.encode()) > MAX_CALLBACK_BYTES:
            raise CallbackError(f"callback_data بیش از حد بلند است: {data!r}")
        return data

    @property
    def int_arg(self) -> int:
        try:
            return int(self.arg)
        except ValueError as exc:
            raise CallbackError(f"آرگومان عددی نیست: {self.arg!r}") from exc

    @property
    def int_arg2(self) -> int:
        try:
            return int(self.arg2)
        except ValueError as exc:
            raise CallbackError(f"آرگومان دوم عددی نیست: {self.arg2!r}") from exc


def pack(namespace: str, action: str, arg: object = "", arg2: object = "") -> str:
    return CB(namespace, action, str(arg), str(arg2)).pack()


def parse(data: str | None) -> CB:
    """پارس امن callback_data ورودی — همیشه اعتبارسنجی می‌شود."""
    if not data or not _PATTERN.match(data):
        raise CallbackError(f"callback نامعتبر: {data!r}")
    parts = data.split(":")
    while len(parts) < 4:
        parts.append("")
    return CB(parts[0], parts[1], parts[2], parts[3])


# ── فضای نام‌ها ────────────────────────────────────────────────
NS_MAIN = "main"
NS_ACCOUNT = "account"
NS_LINKDONI = "linkdoni"
NS_JOINER = "joiner"
NS_SENDER = "sender"
NS_JOB = "job"
NS_SETTINGS = "settings"
NS_EXPORT = "export"
NS_AI = "ai"
NS_NOOP = "noop"

NOOP = pack(NS_NOOP, "x")
HOME = pack(NS_MAIN, "home")
