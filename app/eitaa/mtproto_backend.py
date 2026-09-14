"""
Backend واقعی MTProto مبتنی بر فریم‌ورک «pyeitaa» (اثر MSDanesh، Layer 135).

╔══════════════════════════════════════════════════════════════════════════╗
║  وضعیت واقعی این وابستگی — بدون هیچ تعارفی                               ║
║                                                                          ║
║  • پکیج `pyeitaa` روی PyPI نسخهٔ ۰.۱.۲ است که **شکسته** است              ║
║    (ماژول‌های network/methods/storage در wheel وجود ندارند).             ║
║  • فریم‌ورک واقعی MTProto نسخهٔ ۰.۱.۰ اثر MSDanesh است که مخزن           ║
║    upstream آن حذف شده (`Repository not found`).                         ║
║                                                                          ║
║  بنابراین این ماژول در زمان اجرا وجود کتابخانه را **بررسی** می‌کند و     ║
║  اگر نبود، صادقانه UNAVAILABLE گزارش می‌دهد.                             ║
║  هیچ عملیاتی شبیه‌سازی (Fake) نمی‌شود.                                    ║
╚══════════════════════════════════════════════════════════════════════════╝

تمام RPCهای استفاده‌شده در زیر با بازرسی مستقیم سورس فریم‌ورک تأیید شده‌اند:

    channels.JoinChannel(channel: InputChannel)            # ID 0x24b524c5
    messages.ImportChatInvite(hash: str)                   # ID 0x6c50051c
    messages.CheckChatInvite(hash: str)
    contacts.ResolveUsername(username: str)
    messages.GetDialogs(offset_date, offset_id, offset_peer, limit, hash, ...)
    contacts.GetContacts(hash)
    messages.SendMessage(peer, message, random_id, ...)
"""
from __future__ import annotations

import logging
import random
from importlib import import_module
from typing import Any

from app.eitaa.base import (
    AccountIdentity,
    Capability,
    EitaaBackend,
    EitaaError,
    EitaaUnavailable,
    OpResult,
    Target,
)
from app.security import redact

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
#  تشخیص واقعی در دسترس بودن فریم‌ورک
# ══════════════════════════════════════════════════════════════════
def _probe() -> tuple[bool, str]:
    """
    بررسی می‌کند فریم‌ورک MTProto واقعی قابل ایمپورت است یا نه.
    فقط در صورتی True که کلاس Client و ماژول raw هر دو موجود باشند.
    """
    try:
        mod = import_module("pyeitaa")
    except Exception as exc:  # noqa: BLE001
        return False, f"pyeitaa قابل ایمپورت نیست: {exc}"

    if not hasattr(mod, "Client"):
        return False, (
            "نسخهٔ نصب‌شدهٔ pyeitaa فریم‌ورک MTProto نیست "
            "(کلاس Client ندارد). نسخهٔ PyPI با این پروژه سازگار نیست."
        )
    try:
        import_module("pyeitaa.raw.functions.channels")
    except Exception as exc:  # noqa: BLE001
        return False, f"ماژول raw در نسخهٔ نصب‌شده ناقص است: {exc}"
    return True, ""


_MTPROTO_READY, _PROBE_ERROR = _probe()

INSTALL_HINT = (
    "قابلیت‌های نشست کاربری (Join / گروه‌ها / مخاطبین) به فریم‌ورک MTProto ایتا "
    "به نام pyeitaa (اثر MSDanesh، Layer 135) نیاز دارند.\n"
    "این پکیج روی PyPI در دسترس نیست و باید دستی نصب شود.\n"
    "جزئیات کامل در docs/AUDIT.md بخش ۲.۴ آمده است."
)


def mtproto_available() -> bool:
    return _MTPROTO_READY


def mtproto_error() -> str:
    return _PROBE_ERROR


def mtproto_status() -> Capability:
    return Capability.AVAILABLE if _MTPROTO_READY else Capability.UNAVAILABLE


# ══════════════════════════════════════════════════════════════════
class MTProtoBackend(EitaaBackend):
    """اکانت از نوع «نشست کاربری» — تنها مسیر واقعی برای Join."""

    name = "mtproto"

    can_validate = mtproto_status()
    can_send_text = mtproto_status()
    can_send_media = Capability.UNAVAILABLE if not _MTPROTO_READY else Capability.AVAILABLE
    can_join = mtproto_status()
    can_list_groups = mtproto_status()
    can_list_contacts = mtproto_status()
    can_list_private = mtproto_status()
    can_resolve = mtproto_status()

    def __init__(self, session_name: str, workdir: str) -> None:
        if not _MTPROTO_READY:
            raise EitaaUnavailable(INSTALL_HINT)
        self._session_name = session_name
        self._workdir = workdir
        self._client: Any = None
        self._started = False

    # ---------------------------------------------------------- client
    async def _ensure(self) -> Any:
        if self._started and self._client is not None:
            return self._client
        pyeitaa = import_module("pyeitaa")
        try:
            self._client = pyeitaa.Client(self._session_name, workdir=self._workdir)
            await self._client.start()
            self._started = True
        except Exception as exc:  # noqa: BLE001
            log.error("MTProto start failed: %s", redact(exc))
            raise EitaaError(
                "اتصال نشست کاربری برقرار نشد. نشست ممکن است منقضی شده باشد.",
                retryable=True,
                technical=repr(exc),
            ) from exc
        return self._client

    async def close(self) -> None:
        if self._client is not None and self._started:
            try:
                await self._client.stop()
            except Exception as exc:  # noqa: BLE001
                log.debug("stop error: %s", redact(exc))
            finally:
                self._started = False

    # ---------------------------------------------------------- helpers
    @staticmethod
    def _map_error(exc: Exception) -> OpResult:
        """نگاشت خطاهای واقعی فریم‌ورک به نتیجهٔ قابل‌فهم کاربر."""
        cls = type(exc).__name__
        msg = str(exc)
        if cls == "UserAlreadyParticipant" or "ALREADY_PARTICIPANT" in msg.upper():
            return OpResult.already_done("قبلاً عضو شده‌اید")
        if cls in {"InviteHashExpired", "InviteHashInvalid"} or "INVITE_HASH" in msg.upper():
            return OpResult.bad("لینک دعوت نامعتبر یا منقضی است")
        if cls == "UsernameNotOccupied" or "USERNAME_NOT_OCCUPIED" in msg.upper():
            return OpResult.bad("این شناسه وجود ندارد")
        if cls == "ChannelPrivate" or "CHANNEL_PRIVATE" in msg.upper():
            return OpResult.failure("دسترسی به این گروه وجود ندارد")
        if cls == "ChannelsTooMuch" or "TOO_MUCH" in msg.upper():
            return OpResult.failure("سقف تعداد گروه‌های این اکانت پر شده است")
        if cls in {"FloodWait", "SlowmodeWait"}:
            seconds = getattr(exc, "value", None) or getattr(exc, "x", "")
            return OpResult.failure(f"محدودیت سرعت ایتا — لازم است {seconds} ثانیه صبر شود")
        return OpResult.failure("عملیات انجام نشد")

    @staticmethod
    def _invite_hash(ref: str) -> str | None:
        """استخراج hash از لینک دعوت واقعی ایتا (`/joinchat/<hash>` یا `/+<hash>`)."""
        value = ref.strip().rstrip("/")
        for marker in ("/joinchat/", "/+"):
            if marker in value:
                return value.split(marker, 1)[1].split("?")[0] or None
        return None

    @staticmethod
    def _username(ref: str) -> str:
        value = ref.strip().rstrip("/")
        if "//" in value:
            value = value.split("//", 1)[1]
            value = value.split("/", 1)[1] if "/" in value else ""
        return value.lstrip("@").split("?")[0]

    # ---------------------------------------------------------- API
    async def validate(self) -> AccountIdentity:
        client = await self._ensure()
        try:
            me = await client.get_me()
        except Exception as exc:  # noqa: BLE001
            raise EitaaError(
                "نشست معتبر نیست یا منقضی شده است.", retryable=False, technical=repr(exc)
            ) from exc
        name = " ".join(
            str(p) for p in (getattr(me, "first_name", ""), getattr(me, "last_name", "")) if p
        ).strip()
        return AccountIdentity(
            name=(name or getattr(me, "username", "") or "نشست کاربری")[:60],
            detail=str(getattr(me, "username", "") or "")[:60],
        )

    async def join(self, ref: str) -> OpResult:
        """
        عضویت واقعی:
          • لینک دعوت → messages.ImportChatInvite(hash)
          • شناسهٔ عمومی → contacts.ResolveUsername ➜ channels.JoinChannel
        """
        client = await self._ensure()
        raw = import_module("pyeitaa.raw")

        invite = self._invite_hash(ref)
        if invite:
            try:
                await client.invoke(raw.functions.messages.ImportChatInvite(hash=invite))
                return OpResult.success(mode="invite")
            except Exception as exc:  # noqa: BLE001
                log.info("join invite failed: %s", redact(exc))
                return self._map_error(exc)

        username = self._username(ref)
        if not username:
            return OpResult.bad("لینک قابل تشخیص نیست")

        try:
            resolved = await client.invoke(
                raw.functions.contacts.ResolveUsername(username=username)
            )
        except Exception as exc:  # noqa: BLE001
            log.info("resolve failed: %s", redact(exc))
            return self._map_error(exc)

        chats = list(getattr(resolved, "chats", []) or [])
        if not chats:
            # کاربر است نه گروه — طبق بخش ۶ برای Join استفاده نمی‌شود
            return OpResult.bad("این لینک گروه/کانال نیست")

        chat = chats[0]
        try:
            input_channel = raw.types.InputChannel(
                channel_id=chat.id, access_hash=getattr(chat, "access_hash", 0) or 0
            )
            await client.invoke(raw.functions.channels.JoinChannel(channel=input_channel))
            return OpResult.success(title=getattr(chat, "title", "") or username)
        except Exception as exc:  # noqa: BLE001
            log.info("join channel failed: %s", redact(exc))
            return self._map_error(exc)

    async def resolve_kind(self, ref: str) -> str:
        """
        تشخیص قطعی نوع لینک با contacts.ResolveUsername.
        در صورت عدم قطعیت «UNKNOWN» برمی‌گرداند — حدس زده نمی‌شود (بخش ۶).
        """
        client = await self._ensure()
        raw = import_module("pyeitaa.raw")
        username = self._username(ref)
        if not username:
            return "UNKNOWN"
        try:
            res = await client.invoke(raw.functions.contacts.ResolveUsername(username=username))
        except Exception:  # noqa: BLE001
            return "UNKNOWN"

        for chat in getattr(res, "chats", []) or []:
            # در Layer 135، فیلد `megagroup` گروه را از کانال جدا می‌کند.
            if getattr(chat, "megagroup", False):
                return "GROUP"
            if type(chat).__name__ in {"Channel", "ChannelForbidden"}:
                return "CHANNEL"
            if type(chat).__name__ in {"Chat", "ChatForbidden"}:
                return "GROUP"
        if getattr(res, "users", None):
            return "USER"
        return "UNKNOWN"

    async def send_text(self, chat: str, text: str) -> OpResult:
        client = await self._ensure()
        raw = import_module("pyeitaa.raw")
        username = self._username(chat)
        try:
            resolved = await client.invoke(
                raw.functions.contacts.ResolveUsername(username=username)
            )
            peer = self._peer_from_resolved(raw, resolved)
            if peer is None:
                return OpResult.bad("مقصد پیدا نشد")
            await client.invoke(
                raw.functions.messages.SendMessage(
                    peer=peer, message=text, random_id=random.getrandbits(63)
                )
            )
            return OpResult.success()
        except Exception as exc:  # noqa: BLE001
            log.info("send_text failed: %s", redact(exc))
            return self._map_error(exc)

    @staticmethod
    def _peer_from_resolved(raw: Any, resolved: Any) -> Any:
        for chat in getattr(resolved, "chats", []) or []:
            return raw.types.InputPeerChannel(
                channel_id=chat.id, access_hash=getattr(chat, "access_hash", 0) or 0
            )
        for user in getattr(resolved, "users", []) or []:
            return raw.types.InputPeerUser(
                user_id=user.id, access_hash=getattr(user, "access_hash", 0) or 0
            )
        return None

    # ---------------------------------------------------------- targets
    async def _dialogs(self, limit: int) -> tuple[list[Any], list[Any]]:
        client = await self._ensure()
        raw = import_module("pyeitaa.raw")
        res = await client.invoke(
            raw.functions.messages.GetDialogs(
                offset_date=0,
                offset_id=0,
                offset_peer=raw.types.InputPeerEmpty(),
                limit=limit,
                hash=0,
            )
        )
        return list(getattr(res, "chats", []) or []), list(getattr(res, "users", []) or [])

    async def list_groups(self, limit: int = 200) -> list[Target]:
        try:
            chats, _ = await self._dialogs(limit)
        except Exception as exc:  # noqa: BLE001
            raise EitaaError("دریافت فهرست گروه‌ها انجام نشد.", technical=repr(exc)) from exc
        out: list[Target] = []
        for chat in chats:
            name = type(chat).__name__
            if name in {"Chat", "Channel"} and (
                getattr(chat, "megagroup", False) or name == "Chat"
            ):
                out.append(
                    Target(
                        ref=str(getattr(chat, "username", "") or chat.id),
                        title=getattr(chat, "title", "") or "بدون نام",
                        kind="GROUPS",
                    )
                )
        return out

    async def list_private(self, limit: int = 200) -> list[Target]:
        try:
            _, users = await self._dialogs(limit)
        except Exception as exc:  # noqa: BLE001
            raise EitaaError("دریافت چت‌های خصوصی انجام نشد.", technical=repr(exc)) from exc
        return [
            Target(
                ref=str(getattr(u, "username", "") or u.id),
                title=" ".join(
                    str(p)
                    for p in (getattr(u, "first_name", ""), getattr(u, "last_name", ""))
                    if p
                ).strip()
                or "بدون نام",
                kind="PRIVATE",
            )
            for u in users
        ]

    async def list_contacts(self, limit: int = 200) -> list[Target]:
        client = await self._ensure()
        raw = import_module("pyeitaa.raw")
        try:
            res = await client.invoke(raw.functions.contacts.GetContacts(hash=0))
        except Exception as exc:  # noqa: BLE001
            raise EitaaError("دریافت مخاطبین انجام نشد.", technical=repr(exc)) from exc
        return [
            Target(
                ref=str(getattr(u, "username", "") or u.id),
                title=" ".join(
                    str(p)
                    for p in (getattr(u, "first_name", ""), getattr(u, "last_name", ""))
                    if p
                ).strip()
                or "بدون نام",
                kind="CONTACTS",
            )
            for u in (getattr(res, "users", []) or [])[:limit]
        ]
