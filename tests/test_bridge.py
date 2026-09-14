"""
تست Backend پل EitaaBun.

یک سرور HTTP واقعی (aiohttp) بالا می‌آید که دقیقاً شکل پاسخ‌های
مستندشدهٔ EitaaBun را برمی‌گرداند؛ پس قرارداد واقعی تست می‌شود، نه mock.
"""
from __future__ import annotations

import pytest
from aiohttp import web

from app.db.models import AccountKind
from app.eitaa.base import Capability, EitaaError
from app.eitaa.bridge_backend import (
    BridgeBackend,
    BridgeClient,
    _parse_peer,
    confirm_login_code,
    send_login_code,
)
from app.security import mask_phone


# ══════════════════════════════════════════════════════════════════
#  سرور ساختگی با قرارداد واقعی EitaaBun
# ══════════════════════════════════════════════════════════════════
@pytest.fixture
async def bridge():
    """سرور واقعی aiohttp روی یک پورت آزاد — بدون افزونهٔ اضافی."""
    state: dict = {"calls": []}

    async def root(request):
        return web.Response(text="Eitaa Manager")

    async def send_code(request):
        body = await request.json()
        state["calls"].append(("sendCode", body))
        if body.get("phone") == "+980000000000":
            return web.json_response({"error": "error in sending code"})
        return web.json_response(
            {"imei": "web_abc123", "phone_hash": "hash_xyz", "next": "auth.codeTypeSms"}
        )

    async def login(request):
        body = await request.json()
        state["calls"].append(("login", body))
        if body.get("code") == "00000":
            return web.json_response({"error": "Error. phone or code is wrong"})
        if body.get("code") == "22222":
            return web.json_response({"error": "PasswordRequired"})
        return web.json_response(
            {
                "token": "TOKEN_SECRET_VALUE",
                "imei": "web_abc123",
                "user_id": 777,
                "username": "ali",
                "access_hash": 999,
            }
        )

    async def load_session(request):
        body = await request.json()
        if body.get("phone") == "+989999999999":
            return web.json_response({"error": "no session"})
        return web.json_response({"user": {"username": "ali", "first_name": "Ali"}})

    async def send(request):
        body = await request.json()
        state["calls"].append(("send", body))
        return web.json_response({"result": "ok"})

    async def add_member(request):
        body = await request.json()
        state["calls"].append(("addMember", body))
        if body.get("id") == 111:
            return web.json_response({"error": "USER_ALREADY_PARTICIPANT"})
        if body.get("id") == 222:
            return web.json_response({"error": "CHANNEL_PRIVATE"})
        return web.json_response({"result": "ok"})

    async def dialogs(request):
        return web.json_response(
            {
                "chats": [
                    {"_": "channel", "id": 100, "access_hash": 55, "title": "گروه یک"},
                    {"_": "chat", "id": 200, "access_hash": 0, "title": "گروه دو"},
                ],
                "users": [
                    {"id": 300, "access_hash": 77, "first_name": "سارا"},
                ],
            }
        )

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/eitaa/auth/sendCode", send_code)
    app.router.add_post("/eitaa/auth/login", login)
    app.router.add_post("/eitaa/auth/loadSession", load_session)
    app.router.add_post("/eitaa/messages/send", send)
    app.router.add_post("/eitaa/messages/dialogs", dialogs)
    app.router.add_post("/eitaa/groups/addMember", add_member)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    try:
        yield f"http://127.0.0.1:{port}", state
    finally:
        await runner.cleanup()


# ══════════════════════════════════════════════════════════════════
class TestLoginFlow:
    async def test_send_code_returns_hash(self, bridge) -> None:
        url, state = bridge
        data = await send_login_code(url, "+989121234567")
        assert data["phone_hash"] == "hash_xyz"
        assert state["calls"][0][1]["phone"] == "+989121234567"

    async def test_send_code_failure_is_reported(self, bridge) -> None:
        url, _ = bridge
        with pytest.raises(EitaaError) as err:
            await send_login_code(url, "+980000000000")
        assert "کد تأیید" in err.value.message

    async def test_login_success(self, bridge) -> None:
        url, _ = bridge
        data = await confirm_login_code(url, "+989121234567", "12345")
        assert data["token"] == "TOKEN_SECRET_VALUE"
        assert data["user_id"] == 777

    async def test_wrong_code_rejected(self, bridge) -> None:
        url, _ = bridge
        with pytest.raises(EitaaError) as err:
            await confirm_login_code(url, "+989121234567", "00000")
        assert "ورود انجام نشد" in err.value.message

    async def test_two_factor_detected(self, bridge) -> None:
        """رمز دومرحله‌ای باید تشخیص داده شود، نه اینکه خطای عمومی بدهد."""
        url, _ = bridge
        with pytest.raises(EitaaError) as err:
            await confirm_login_code(url, "+989121234567", "22222")
        assert "SESSION_PASSWORD_NEEDED" in err.value.technical
        assert "دومرحله" in err.value.message

    async def test_bridge_down_is_honest(self) -> None:
        """اگر سرویس بالا نباشد، پیام واضح بدهد نه traceback."""
        with pytest.raises(EitaaError) as err:
            await send_login_code("http://127.0.0.1:9", "+989121234567")
        assert "برقرار نشد" in err.value.message or "پل" in err.value.message


class TestBridgeBackend:
    async def test_validate_returns_identity_without_phone(self, bridge) -> None:
        url, _ = bridge
        backend = BridgeBackend(url, "+989121234567")
        identity = await backend.validate()
        await backend.close()
        assert identity.name == "ali"
        # شمارهٔ کامل هرگز نباید در UI بیاید
        assert "989121234567" not in identity.detail
        assert "4567" in identity.detail

    async def test_validate_detects_dead_session(self, bridge) -> None:
        url, _ = bridge
        backend = BridgeBackend(url, "+989999999999")
        with pytest.raises(EitaaError) as err:
            await backend.validate()
        await backend.close()
        assert "معتبر نیست" in err.value.message

    async def test_send_text(self, bridge) -> None:
        url, state = bridge
        backend = BridgeBackend(url, "+989121234567")
        result = await backend.send_text("100:55:group", "سلام")
        await backend.close()
        assert result.ok
        sent = [c for c in state["calls"] if c[0] == "send"][0][1]
        assert sent["id"] == 100
        assert sent["access_hash"] == 55
        assert sent["message"] == "سلام"

    async def test_empty_text_rejected(self, bridge) -> None:
        url, _ = bridge
        backend = BridgeBackend(url, "+989121234567")
        result = await backend.send_text("100:55:group", "   ")
        await backend.close()
        assert not result.ok and result.invalid

    async def test_join_success(self, bridge) -> None:
        url, _ = bridge
        backend = BridgeBackend(url, "+989121234567")
        result = await backend.join("500:0:group")
        await backend.close()
        assert result.ok

    async def test_join_already_member(self, bridge) -> None:
        url, _ = bridge
        backend = BridgeBackend(url, "+989121234567")
        result = await backend.join("111:0:group")
        await backend.close()
        assert result.already and not result.ok

    async def test_join_private_channel_fails_cleanly(self, bridge) -> None:
        url, _ = bridge
        backend = BridgeBackend(url, "+989121234567")
        result = await backend.join("222:0:group")
        await backend.close()
        assert not result.ok and not result.already

    async def test_invite_link_honestly_rejected(self, bridge) -> None:
        """لینک دعوت خصوصی پشتیبانی نمی‌شود — نباید وانمود کند."""
        url, _ = bridge
        backend = BridgeBackend(url, "+989121234567")
        result = await backend.join("https://eitaa.com/joinchat/abc123")
        await backend.close()
        assert not result.ok
        assert "پشتیبانی نمی‌شود" in result.reason

    async def test_list_groups(self, bridge) -> None:
        url, _ = bridge
        backend = BridgeBackend(url, "+989121234567")
        groups = await backend.list_groups()
        await backend.close()
        assert len(groups) == 2
        assert groups[0].title == "گروه یک"
        assert groups[0].ref == "100:55:group"

    async def test_list_private(self, bridge) -> None:
        url, _ = bridge
        backend = BridgeBackend(url, "+989121234567")
        users = await backend.list_private()
        await backend.close()
        assert len(users) == 1
        assert users[0].title == "سارا"

    async def test_capabilities_are_real(self) -> None:
        """این Backend واقعاً join دارد، برخلاف توکن ایتایار."""
        assert BridgeBackend.can_join is Capability.AVAILABLE
        assert BridgeBackend.can_list_groups is Capability.AVAILABLE
        # چیزی که ندارد را ادعا نمی‌کند
        assert BridgeBackend.can_resolve is Capability.NOT_SUPPORTED

    def test_empty_base_url_rejected(self) -> None:
        with pytest.raises(EitaaError):
            BridgeBackend("", "+989121234567")

    def test_empty_phone_rejected(self) -> None:
        with pytest.raises(EitaaError):
            BridgeBackend("http://x", "")


class TestPeerParsing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("100:55:group", (100, 55, "group")),
            ("100:55:user", (100, 55, "user")),
            ("100", (100, 0, "group")),
            ("100:7", (100, 7, "group")),
            ("100:bad:group", (100, 0, "group")),
        ],
    )
    def test_valid(self, raw, expected) -> None:
        assert _parse_peer(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "@channel", "https://eitaa.com/x"])
    def test_invalid(self, raw) -> None:
        with pytest.raises(ValueError):
            _parse_peer(raw)


class TestPhoneMasking:
    @pytest.mark.parametrize(
        "phone,expected_tail,forbidden",
        [
            ("+989121234567", "4567", "989121234567"),
            ("09121234567", "4567", "09121234"),
        ],
    )
    def test_only_last_four_shown(self, phone, expected_tail, forbidden) -> None:
        masked = mask_phone(phone)
        assert masked.endswith(expected_tail)
        assert forbidden not in masked

    def test_short_input_fully_masked(self) -> None:
        assert set(mask_phone("123")) == {"•"}

    def test_empty(self) -> None:
        assert mask_phone("") == "—"


class TestAccountKindIntegration:
    def test_bridge_account_can_join(self) -> None:
        """اکانت شماره‌ای باید مجاز به Join باشد، برخلاف اکانت توکنی."""
        from app.db.models import Account, AccountStatus

        bridge = Account(
            id=1, label="x", kind=AccountKind.BRIDGE, status=AccountStatus.ONLINE
        )
        token = Account(
            id=2, label="y", kind=AccountKind.BOT_API, status=AccountStatus.ONLINE
        )
        assert bridge.can_join is True
        assert token.can_join is False

    def test_bridge_kind_has_label(self) -> None:
        assert AccountKind.BRIDGE.label
        assert "شماره" in AccountKind.BRIDGE.label


class TestErrorExtraction:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"error": "boom"}, "boom"),
            ({"message": "bad"}, "bad"),
            ({"result": "ok"}, ""),
            ({}, ""),
        ],
    )
    def test_error_of(self, payload, expected) -> None:
        assert BridgeClient.error_of(payload) == expected


class TestDiagnosticMessages:
    """پیام خطا باید بگوید «چطور درستش کنم»، نه فقط «خراب شد»."""

    async def test_bridge_down_tells_user_what_to_run(self) -> None:
        with pytest.raises(EitaaError) as err:
            await send_login_code("http://127.0.0.1:9", "+989121234567")
        msg = err.value.message
        # باید دستور دقیق اجرا را بدهد، نه فقط بگوید «خراب است»
        assert "bridge-setup.sh --bg" in msg
        # و راه دیدن علت واقعی خرابی را نشان دهد
        assert "--log" in msg or "--status" in msg

    async def test_bridge_up_but_eitaa_unreachable(self, aiohttp_like_bridge) -> None:
        """
        حالت واقعی: پل بالاست ولی خودش به ایتا نمی‌رسد.
        نباید بگوید «پل اجرا نیست» — گمراه‌کننده است.
        """
        url = aiohttp_like_bridge
        with pytest.raises(EitaaError) as err:
            await send_login_code(url, "+989121234567")
        msg = err.value.message
        assert "سرور ایتا" in msg
        assert "bridge-setup.sh" not in msg


@pytest.fixture
async def aiohttp_like_bridge():
    """پلی که بالاست ولی به ایتا وصل نمی‌شود — پاسخ واقعی EitaaBun."""
    async def send_code(request):
        return web.json_response({"msg": "error in connection"})

    app = web.Application()
    app.router.add_post("/eitaa/auth/sendCode", send_code)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()
