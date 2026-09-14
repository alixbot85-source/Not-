"""
تست لایهٔ سرویس ایتا.

نکتهٔ مهم: این تست‌ها رفتار کتابخانه را Mock **نمی‌کنند** تا وانمود کنند کار می‌کند.
آنچه بررسی می‌شود، صداقت گزارش قابلیت‌ها و مدیریت خطاست.
"""
from __future__ import annotations

import pytest

from app.db.models import AccountKind
from app.eitaa.base import Capability, EitaaBackend, EitaaError, EitaaUnavailable, OpResult
from app.eitaa.eitaayar_backend import EitaayarBackend, eitaapy_available
from app.eitaa.mtproto_backend import MTProtoBackend, mtproto_available
from app.eitaa.service import build_backend, capability_report

pytestmark = pytest.mark.asyncio


class TestOpResult:
    async def test_variants(self) -> None:
        assert OpResult.success(x=1).ok is True
        already = OpResult.already_done()
        assert already.ok is False and already.already is True
        bad = OpResult.bad("نامعتبر")
        assert bad.invalid is True and bad.ok is False
        fail = OpResult.failure("خطا")
        assert fail.ok is False and fail.invalid is False


class TestBaseContract:
    async def test_unimplemented_methods_raise_not_fake(self) -> None:
        """پایه هرگز موفقیت جعلی برنمی‌گرداند."""
        backend = EitaaBackend()
        for call in (
            backend.validate(),
            backend.send_text("a", "b"),
            backend.join("x"),
            backend.list_groups(),
            backend.list_contacts(),
            backend.list_private(),
        ):
            with pytest.raises(EitaaUnavailable):
                await call

    async def test_default_capabilities_are_not_supported(self) -> None:
        backend = EitaaBackend()
        assert backend.can_join is Capability.NOT_SUPPORTED
        assert backend.can_send_text is Capability.NOT_SUPPORTED


@pytest.mark.skipif(not eitaapy_available(), reason="eitaapy نصب نیست")
class TestEitaayarBackend:
    async def test_capabilities_reflect_real_api(self) -> None:
        """
        API واقعی eitaapy فقط get_me/send_message/send_file دارد.
        بنابراین join و dialogs باید NOT_SUPPORTED باشند.
        """
        backend = EitaayarBackend("bot1:test-token-value")
        assert backend.can_send_text is Capability.AVAILABLE
        assert backend.can_send_media is Capability.AVAILABLE
        assert backend.can_validate is Capability.AVAILABLE
        assert backend.can_join is Capability.NOT_SUPPORTED
        assert backend.can_list_groups is Capability.NOT_SUPPORTED
        assert backend.can_list_contacts is Capability.NOT_SUPPORTED

    async def test_join_raises_instead_of_faking(self) -> None:
        backend = EitaayarBackend("bot1:test-token-value")
        with pytest.raises(EitaaUnavailable):
            await backend.join("https://eitaa.com/group")

    async def test_empty_token_rejected(self) -> None:
        with pytest.raises(EitaaError):
            EitaayarBackend("")

    async def test_empty_text_rejected_without_network(self) -> None:
        backend = EitaayarBackend("bot1:test-token-value")
        result = await backend.send_text("chat", "   ")
        assert result.ok is False and result.invalid is True

    async def test_error_response_is_mapped(self) -> None:
        backend = EitaayarBackend("bot1:test")
        with pytest.raises(EitaaError):
            backend._check({"ok": False, "description": "توکن نامعتبر"})
        with pytest.raises(EitaaError):
            backend._check("not-a-dict")


class TestMTProtoHonesty:
    async def test_unavailable_raises_clear_error(self) -> None:
        """وقتی فریم‌ورک نصب نیست، باید صریح اعلام شود نه شبیه‌سازی."""
        if mtproto_available():
            pytest.skip("فریم‌ورک MTProto نصب است")
        with pytest.raises(EitaaUnavailable) as exc:
            MTProtoBackend("session", "/tmp")
        assert "pyeitaa" in str(exc.value)

    async def test_capability_matches_availability(self) -> None:
        expected = Capability.AVAILABLE if mtproto_available() else Capability.UNAVAILABLE
        assert MTProtoBackend.can_join is expected

    async def test_invite_hash_parsing(self) -> None:
        """پارس لینک دعوت منطق خالص است و نیاز به شبکه ندارد."""
        parse = MTProtoBackend._invite_hash
        assert parse("https://eitaa.com/joinchat/ABC123") == "ABC123"
        assert parse("https://eitaa.com/+XYZ789") == "XYZ789"
        assert parse("https://eitaa.com/publicname") is None

    async def test_username_parsing(self) -> None:
        extract = MTProtoBackend._username
        assert extract("https://eitaa.com/mygroup") == "mygroup"
        assert extract("@mygroup") == "mygroup"


class TestServiceFactory:
    async def test_missing_account_raises(self, db) -> None:
        with pytest.raises(EitaaError):
            await build_backend(db, 9999)

    async def test_mtproto_account_without_framework(self, db) -> None:
        account_id = await db.add_account("s", AccountKind.MTPROTO, session_name="x")
        if mtproto_available():
            pytest.skip("فریم‌ورک نصب است")
        with pytest.raises(EitaaUnavailable):
            await build_backend(db, account_id)

    async def test_bot_account_without_secret(self, db) -> None:
        account_id = await db.add_account("b", AccountKind.BOT_API, secret="")
        with pytest.raises(EitaaError):
            await build_backend(db, account_id)

    async def test_capability_report_is_truthful(self) -> None:
        report = capability_report()
        assert report
        for title, capability, detail in report:
            assert isinstance(capability, Capability)
            assert title and isinstance(detail, str)

        joiner = [r for r in report if "عضویت" in r[0]][0]
        expected = Capability.AVAILABLE if mtproto_available() else Capability.UNAVAILABLE
        assert joiner[1] is expected
