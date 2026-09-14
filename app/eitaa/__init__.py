"""لایهٔ سرویس ایتا — کاملاً مستقل از Telegram UI."""
from app.eitaa.base import (
    AccountIdentity,
    Capability,
    EitaaBackend,
    EitaaError,
    EitaaUnavailable,
    OpResult,
    Target,
)
from app.eitaa.service import build_backend, capability_report

__all__ = [
    "AccountIdentity",
    "Capability",
    "EitaaBackend",
    "EitaaError",
    "EitaaUnavailable",
    "OpResult",
    "Target",
    "build_backend",
    "capability_report",
]
