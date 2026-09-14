"""
Backend واقعی مبتنی بر کتابخانهٔ «eitaapy» (نسخهٔ 1.2.0، تأییدشده).

سطح API واقعی این کتابخانه — با بازرسی سورس تأیید شده است:

    Robot(token)                                      → https://eitaayar.ir/api/{token}
    await Robot.get_me()                              → dict
    await Robot.send_message(chat_id, text, title=None, notification_disable=None,
                             id_message_to_reply=None, date=None, pin=None,
                             view_count_for_delete=None)
    await Robot.send_file(chat_id, file, caption=None)

هیچ متد دیگری در این کتابخانه وجود ندارد.
بنابراین Join / Dialogs / Contacts در اینجا NOT_SUPPORTED گزارش می‌شوند — و جعل نمی‌شوند.
"""
from __future__ import annotations

import logging
from typing import Any

from app.eitaa.base import (
    AccountIdentity,
    Capability,
    EitaaBackend,
    EitaaError,
    OpResult,
)
from app.security import redact

log = logging.getLogger(__name__)

try:  # وابستگی واقعی
    from eitaapy import Robot as _Robot

    _EITAAPY_READY = True
    _IMPORT_ERROR = ""
except Exception as exc:  # noqa: BLE001
    _Robot = None  # type: ignore[assignment]
    _EITAAPY_READY = False
    _IMPORT_ERROR = str(exc)


def eitaapy_available() -> bool:
    return _EITAAPY_READY


def eitaapy_import_error() -> str:
    return _IMPORT_ERROR


class EitaayarBackend(EitaaBackend):
    """اکانت از نوع «توکن ایتایار» — فقط ارسال (واقعی و کارکردی)."""

    name = "eitaayar"

    can_validate = Capability.AVAILABLE if _EITAAPY_READY else Capability.UNAVAILABLE
    can_send_text = Capability.AVAILABLE if _EITAAPY_READY else Capability.UNAVAILABLE
    can_send_media = Capability.AVAILABLE if _EITAAPY_READY else Capability.UNAVAILABLE
    # موارد زیر در API واقعی این کتابخانه وجود ندارند:
    can_join = Capability.NOT_SUPPORTED
    can_list_groups = Capability.NOT_SUPPORTED
    can_list_contacts = Capability.NOT_SUPPORTED
    can_list_private = Capability.NOT_SUPPORTED
    can_resolve = Capability.NOT_SUPPORTED

    def __init__(self, token: str) -> None:
        if not _EITAAPY_READY:
            raise EitaaError(
                "کتابخانهٔ eitaapy نصب نیست. دستور نصب: pip install eitaapy==1.2.0",
                technical=_IMPORT_ERROR,
            )
        if not token:
            raise EitaaError("توکن اکانت خالی است.")
        self._robot = _Robot(token)

    # ------------------------------------------------------------------
    @staticmethod
    def _check(response: Any) -> dict[str, Any]:
        """
        پاسخ خام API را بررسی می‌کند.
        قالب پاسخ eitaayar در مستندات رسمی منتشرشده‌ای تأیید نشده،
        بنابراین فقط کلیدهایی که واقعاً دیده می‌شوند بررسی می‌شوند و
        در غیر این صورت پاسخ بدون تفسیرِ حدسی برگردانده می‌شود.
        """
        if isinstance(response, dict):
            if response.get("ok") is False:
                raise EitaaError(
                    str(response.get("description") or "درخواست از سوی سرور ایتا رد شد."),
                    retryable=False,
                )
            if "error" in response:
                raise EitaaError(str(response["error"]), retryable=True)
            return response
        raise EitaaError("پاسخ نامعتبر از سرور ایتا دریافت شد.")

    async def validate(self) -> AccountIdentity:
        try:
            data = self._check(await self._robot.get_me())
        except EitaaError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("validate failed: %s", redact(exc))
            raise EitaaError(
                "ارتباط با سرور ایتا برقرار نشد.", retryable=True, technical=repr(exc)
            ) from exc

        result = data.get("result") if isinstance(data.get("result"), dict) else data
        name = str(
            result.get("title")
            or result.get("first_name")
            or result.get("username")
            or "اکانت ایتایار"
        )
        detail = str(result.get("username") or "")
        return AccountIdentity(name=name[:60], detail=detail[:60])

    async def send_text(self, chat: str, text: str) -> OpResult:
        if not text.strip():
            return OpResult.bad("متن پیام خالی است.")
        try:
            data = self._check(await self._robot.send_message(chat_id=chat, text=text))
            return OpResult.success(raw=data)
        except EitaaError as exc:
            return OpResult.failure(exc.message)
        except Exception as exc:  # noqa: BLE001
            log.error("send_text failed: %s", redact(exc))
            return OpResult.failure("ارسال پیام انجام نشد.")

    async def send_media(self, chat: str, file_path: str, caption: str = "") -> OpResult:
        try:
            data = self._check(
                await self._robot.send_file(chat_id=chat, file=file_path, caption=caption or None)
            )
            return OpResult.success(raw=data)
        except EitaaError as exc:
            return OpResult.failure(exc.message)
        except Exception as exc:  # noqa: BLE001
            log.error("send_media failed: %s", redact(exc))
            return OpResult.failure("ارسال فایل انجام نشد.")
