"""
Backend مبتنی بر پل HTTP «EitaaBun».

EitaaBun یک کلاینت واقعی MTProto برای ایتا است که با Bun/TypeScript نوشته
شده و عملیات را روی یک HTTP API محلی (پیش‌فرض پورت ۱۲۳۴) در دسترس می‌گذارد.
منبع: https://github.com/ghaemifard/EitaaBun

چرا این مسیر؟
    ورود با شماره تلفن به پروتکل MTProto ایتا نیاز دارد. هیچ کتابخانهٔ
    پایتونی که این کار را انجام دهد روی PyPI موجود نیست (جزئیات در
    docs/AUDIT.md §2.4). EitaaBun این پروتکل را واقعاً پیاده کرده است،
    پس به‌جای بازنویسی MTProto، با آن گفتگو می‌کنیم.

نکات مهم:
    • این ماژول هیچ چیزی را شبیه‌سازی نمی‌کند. اگر سرویس بالا نباشد،
      وضعیت UNAVAILABLE گزارش می‌شود.
    • احراز هویت در EitaaBun بر پایهٔ «شمارهٔ تلفن» است؛ توکن و imei
      را خود سرویس به‌صورت محلی ذخیره می‌کند.
    • شمارهٔ تلفن یک شناسهٔ حساس است و هرگز در UI کامل نمایش داده نمی‌شود.
"""
from __future__ import annotations

import logging
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
from app.security import mask_phone, redact

log = logging.getLogger(__name__)

BRIDGE_HINT = (
    "ورود با شمارهٔ تلفن از طریق سرویس «EitaaBun» انجام می‌شود که یک کلاینت "
    "واقعی MTProto برای ایتا است.\n\n"
    "راه‌اندازی:\n"
    "۱) نصب Bun:  curl -fsSL https://bun.sh/install | bash\n"
    "۲) git clone https://github.com/ghaemifard/EitaaBun\n"
    "۳) cd EitaaBun && bun install && bun run index.ts\n\n"
    "سپس در فایل .env مقدار زیر را تنظیم کنید:\n"
    "EITAA_BRIDGE_URL=http://127.0.0.1:1234"
)


def _aiohttp() -> Any:
    try:
        import aiohttp
    except ImportError as exc:  # pragma: no cover - aiohttp همراه aiogram می‌آید
        raise EitaaUnavailable(f"کتابخانهٔ aiohttp در دسترس نیست: {exc}") from exc
    return aiohttp


class BridgeClient:
    """گفتگوی خام با HTTP API سرویس EitaaBun."""

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._session: Any = None

    async def _ensure(self) -> Any:
        aiohttp = _aiohttp()
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def ping(self) -> bool:
        """آیا سرویس پل بالا است؟"""
        aiohttp = _aiohttp()
        try:
            session = await self._ensure()
            async with session.get(f"{self._base}/") as resp:
                return resp.status == 200
        except (aiohttp.ClientError, OSError, TimeoutError):
            return False

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        فراخوانی یک endpoint.

        EitaaBun در خطا شکل {"error": "..."} برمی‌گرداند و در موفقیت
        بدنهٔ واقعی عملیات را.
        """
        aiohttp = _aiohttp()
        session = await self._ensure()
        url = f"{self._base}/eitaa/{path.lstrip('/')}"
        try:
            async with session.post(url, json=payload) as resp:
                try:
                    data = await resp.json(content_type=None)
                except Exception:  # noqa: BLE001
                    text = await resp.text()
                    raise EitaaError(
                        "پاسخ سرویس پل قابل خواندن نبود.",
                        technical=f"{resp.status}: {text[:200]}",
                    ) from None
        except EitaaError:
            raise
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            raise EitaaError(
                "ارتباط با سرویس پل ایتا برقرار نشد. آیا EitaaBun در حال اجراست؟",
                retryable=True,
                technical=repr(exc),
            ) from exc

        if not isinstance(data, dict):
            raise EitaaError("پاسخ نامعتبر از سرویس پل.", technical=str(data)[:200])
        return data

    @staticmethod
    def error_of(data: dict[str, Any]) -> str:
        """اگر پاسخ خطا بود، متن آن را برمی‌گرداند؛ وگرنه رشتهٔ خالی."""
        for key in ("error", "message", "err"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""


# ══════════════════════════════════════════════════════════════════
#  جریان ورود با شماره تلفن (بیرون از Backend، چون حالت‌دار است)
# ══════════════════════════════════════════════════════════════════
async def send_login_code(base_url: str, phone: str) -> dict[str, Any]:
    """
    مرحلهٔ یک: درخواست ارسال کد تأیید به شمارهٔ تلفن.

    خروجی واقعی EitaaBun: {"imei": ..., "phone_hash": ..., "next": ...}
    """
    client = BridgeClient(base_url)
    try:
        data = await client.post("auth/sendCode", {"phone": phone})
        err = BridgeClient.error_of(data)
        if err:
            raise EitaaError("ارسال کد تأیید انجام نشد.", technical=err)
        if not data.get("phone_hash"):
            raise EitaaError(
                "سرویس پل کد تأیید را تأیید نکرد.", technical=str(data)[:200]
            )
        return data
    finally:
        await client.close()


async def confirm_login_code(base_url: str, phone: str, code: str) -> dict[str, Any]:
    """
    مرحلهٔ دو: تأیید کد و ساخت نشست.

    خروجی واقعی: {"token", "imei", "user_id", "username", "access_hash"}
    خطای دو مرحله‌ای: {"error": "PasswordRequired"}
    """
    client = BridgeClient(base_url)
    try:
        data = await client.post("auth/login", {"phone": phone, "code": code})
        err = BridgeClient.error_of(data)
        if err:
            if "PasswordRequired" in err:
                raise EitaaError(
                    "این حساب رمز دومرحله‌ای دارد.",
                    technical="SESSION_PASSWORD_NEEDED",
                )
            raise EitaaError("ورود انجام نشد.", technical=err)
        if not data.get("token"):
            raise EitaaError("نشست ساخته نشد.", technical=str(data)[:200])
        return data
    finally:
        await client.close()


async def confirm_login_password(
    base_url: str, phone: str, password: str
) -> dict[str, Any]:
    """مرحلهٔ سه (فقط برای حساب‌های دومرحله‌ای)."""
    client = BridgeClient(base_url)
    try:
        data = await client.post(
            "auth/loginByPass", {"phone": phone, "password": password}
        )
        err = BridgeClient.error_of(data)
        if err:
            raise EitaaError("رمز دومرحله‌ای پذیرفته نشد.", technical=err)
        return data
    finally:
        await client.close()


# ══════════════════════════════════════════════════════════════════
class BridgeBackend(EitaaBackend):
    """اکانت واقعی کاربری ایتا از طریق پل EitaaBun."""

    name = "bridge"

    can_validate = Capability.AVAILABLE
    can_send_text = Capability.AVAILABLE
    can_send_media = Capability.AVAILABLE
    can_join = Capability.AVAILABLE
    can_list_groups = Capability.AVAILABLE
    can_list_contacts = Capability.AVAILABLE
    can_list_private = Capability.AVAILABLE
    can_resolve = Capability.NOT_SUPPORTED  # EitaaBun متد resolveUsername ندارد

    def __init__(self, base_url: str, phone: str) -> None:
        if not base_url:
            raise EitaaUnavailable(BRIDGE_HINT)
        if not phone:
            raise EitaaError("شمارهٔ تلفن این اکانت ثبت نشده است.")
        self._client = BridgeClient(base_url)
        self._phone = phone

    async def close(self) -> None:
        await self._client.close()

    # ---------------------------------------------------------- hello
    async def validate(self) -> AccountIdentity:
        """بررسی اینکه نشست هنوز معتبر است."""
        if not await self._client.ping():
            raise EitaaError(
                "سرویس پل ایتا در دسترس نیست.", retryable=True, technical="bridge down"
            )
        data = await self._client.post("auth/loadSession", {"phone": self._phone})
        err = BridgeClient.error_of(data)
        if err:
            raise EitaaError("نشست معتبر نیست؛ دوباره وارد شوید.", technical=err)

        user = data.get("user") if isinstance(data.get("user"), dict) else data
        name = str(
            user.get("username")
            or user.get("first_name")
            or "اکانت کاربری ایتا"
        )
        # شماره هرگز کامل نمایش داده نمی‌شود
        return AccountIdentity(name=name, detail=f"نشست کاربری • {mask_phone(self._phone)}")

    # ---------------------------------------------------------- send
    async def send_text(self, chat: str, text: str) -> OpResult:
        if not text.strip():
            return OpResult.bad("متن پیام خالی است.")
        try:
            peer_id, access_hash, peer_type = _parse_peer(chat)
        except ValueError as exc:
            return OpResult.bad(str(exc))

        try:
            data = await self._client.post(
                "messages/send",
                {
                    "phone": self._phone,
                    "message": text,
                    "id": peer_id,
                    "access_hash": access_hash,
                    "type": peer_type,
                    "replyTo": 0,
                },
            )
        except EitaaError as exc:
            return OpResult.failure(exc.message)

        err = BridgeClient.error_of(data)
        if err:
            return OpResult.failure(err[:120])
        return OpResult.success(raw=data)

    async def send_media(self, chat: str, file_path: str, caption: str = "") -> OpResult:
        try:
            peer_id, access_hash, peer_type = _parse_peer(chat)
        except ValueError as exc:
            return OpResult.bad(str(exc))

        try:
            data = await self._client.post(
                "messages/sendMedia",
                {
                    "phone": self._phone,
                    "id": peer_id,
                    "access_hash": access_hash,
                    "path": file_path,
                    "message": caption,
                    "type": peer_type,
                    "media_type": "file",
                },
            )
        except EitaaError as exc:
            return OpResult.failure(exc.message)

        err = BridgeClient.error_of(data)
        if err:
            return OpResult.failure(err[:120])
        return OpResult.success(raw=data)

    # ---------------------------------------------------------- join
    async def join(self, ref: str) -> OpResult:
        """
        عضویت در کانال/گروه.

        EitaaBun متد channels.joinChannel را با شناسهٔ عددی می‌پذیرد.
        برای لینک‌های دعوت (joinchat) این سرویس متدی ندارد، پس صادقانه
        اعلام می‌کنیم به‌جای اینکه وانمود کنیم.
        """
        if "joinchat" in ref or "/+" in ref:
            return OpResult.bad(
                "لینک دعوت خصوصی از این مسیر پشتیبانی نمی‌شود؛ فقط شناسهٔ عددی."
            )
        try:
            peer_id, access_hash, _ = _parse_peer(ref)
        except ValueError as exc:
            return OpResult.bad(str(exc))

        try:
            data = await self._client.post(
                "groups/addMember",
                {
                    "phone": self._phone,
                    "id": peer_id,
                    "access_hash": access_hash,
                },
            )
        except EitaaError as exc:
            return OpResult.failure(exc.message)

        err = BridgeClient.error_of(data)
        if err:
            low = err.lower()
            if "already" in low or "participant" in low:
                return OpResult.already_done("قبلاً عضو بوده است")
            return OpResult.failure(err[:120])
        return OpResult.success(raw=data)

    # ---------------------------------------------------------- lists
    async def _dialogs(self) -> list[dict[str, Any]]:
        data = await self._client.post("messages/dialogs", {"phone": self._phone})
        err = BridgeClient.error_of(data)
        if err:
            raise EitaaError("دریافت فهرست گفتگوها انجام نشد.", technical=err)
        chats = data.get("chats") or data.get("dialogs") or []
        return [c for c in chats if isinstance(c, dict)]

    async def list_groups(self, limit: int = 200) -> list[Target]:
        try:
            chats = await self._dialogs()
        except EitaaError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EitaaError(
                "دریافت فهرست گروه‌ها انجام نشد.", technical=redact(exc)
            ) from exc

        out: list[Target] = []
        for chat in chats:
            kind = str(chat.get("_", ""))
            if "channel" in kind.lower() or "chat" in kind.lower():
                ident = chat.get("id")
                if ident is None:
                    continue
                out.append(
                    Target(
                        ref=_pack_peer(ident, chat.get("access_hash", 0), "group"),
                        title=str(chat.get("title") or "بدون نام"),
                        kind="GROUPS",
                    )
                )
            if len(out) >= limit:
                break
        return out

    async def list_private(self, limit: int = 200) -> list[Target]:
        try:
            data = await self._client.post("messages/dialogs", {"phone": self._phone})
        except EitaaError:
            raise
        err = BridgeClient.error_of(data)
        if err:
            raise EitaaError("دریافت چت‌های خصوصی انجام نشد.", technical=err)

        users = data.get("users") or []
        out: list[Target] = []
        for user in users:
            if not isinstance(user, dict):
                continue
            ident = user.get("id")
            if ident is None:
                continue
            name = " ".join(
                str(user.get(k))
                for k in ("first_name", "last_name")
                if user.get(k)
            ).strip()
            out.append(
                Target(
                    ref=_pack_peer(ident, user.get("access_hash", 0), "user"),
                    title=name or str(user.get("username") or "بدون نام"),
                    kind="PRIVATE",
                )
            )
            if len(out) >= limit:
                break
        return out

    async def list_contacts(self, limit: int = 200) -> list[Target]:
        aiohttp = _aiohttp()
        session = await self._client._ensure()  # noqa: SLF001 — همان کلاینت
        url = f"{self._client._base}/eitaa/contacts/getAll/{self._phone}"  # noqa: SLF001
        try:
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            raise EitaaError(
                "دریافت مخاطبین انجام نشد.", retryable=True, technical=repr(exc)
            ) from exc

        if isinstance(data, dict):
            err = BridgeClient.error_of(data)
            if err:
                raise EitaaError("دریافت مخاطبین انجام نشد.", technical=err)
            items = data.get("contacts") or data.get("users") or []
        else:
            items = data if isinstance(data, list) else []

        out: list[Target] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ident = item.get("id")
            if ident is None:
                continue
            name = " ".join(
                str(item.get(k)) for k in ("first_name", "last_name") if item.get(k)
            ).strip()
            out.append(
                Target(
                    ref=_pack_peer(ident, item.get("access_hash", 0), "user"),
                    title=name or "بدون نام",
                    kind="CONTACTS",
                )
            )
            if len(out) >= limit:
                break
        return out


# ══════════════════════════════════════════════════════════════════
#  ابزار: بسته‌بندی peer در یک رشتهٔ قابل ذخیره
# ══════════════════════════════════════════════════════════════════
def _pack_peer(peer_id: Any, access_hash: Any, peer_type: str) -> str:
    """EitaaBun به سه مقدار نیاز دارد، ولی مدل ما یک رشته ذخیره می‌کند."""
    return f"{peer_id}:{access_hash or 0}:{peer_type}"


def _parse_peer(ref: str) -> tuple[int, int, str]:
    """
    باز کردن رشتهٔ peer.

    قالب‌های پذیرفته‌شده:
        «12345:678:group»   → کامل
        «12345»             → فقط شناسه، access_hash صفر، نوع group
    """
    raw = (ref or "").strip()
    if not raw:
        raise ValueError("مقصد خالی است.")

    parts = raw.split(":")
    try:
        peer_id = int(parts[0])
    except ValueError:
        raise ValueError(
            "این مقصد شناسهٔ عددی ندارد. سرویس پل فقط شناسهٔ عددی می‌پذیرد."
        ) from None

    access_hash = 0
    peer_type = "group"
    if len(parts) >= 2:
        try:
            access_hash = int(parts[1])
        except ValueError:
            access_hash = 0
    if len(parts) >= 3 and parts[2] in {"group", "user", "channel"}:
        peer_type = parts[2]
    return peer_id, access_hash, peer_type
