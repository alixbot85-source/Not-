"""تست لایهٔ امنیت (بخش ۲۸)."""
from __future__ import annotations

import pytest

from app.security import (
    RateLimiter,
    clean_text,
    mask_tail,
    normalize_eitaa_url,
    redact,
    resolve_inside,
    safe_filename,
    secret_box,
)


class TestRedaction:
    """هیچ رازی نباید به لاگ یا UI برسد."""

    @pytest.mark.parametrize(
        "secret",
        [
            "bot12345:9f8e7d6c-1234-5678-9abc-def012345678",
            "7712345678:AAHfakeTokenValueForTestingPurposes12345",
            "token=supersecretvalue",
            "api_key: abcdef123456",
            "9f8e7d6c-1234-5678-9abc-def012345678",
        ],
    )
    def test_secrets_are_redacted(self, secret: str) -> None:
        out = redact(f"prefix {secret} suffix")
        assert "[REDACTED]" in out
        assert secret not in out

    def test_normal_text_survives(self) -> None:
        assert redact("عضویت در گروه انجام شد") == "عضویت در گروه انجام شد"

    def test_mask_tail_hides_body(self) -> None:
        masked = mask_tail("bot12345:abcdefghijkl")
        assert "bot12345" not in masked
        assert masked.endswith("ijkl")


class TestEncryption:
    def test_roundtrip(self) -> None:
        plain = "bot999:secret-token-value"
        encrypted = secret_box.encrypt(plain)
        assert encrypted != plain
        assert plain not in encrypted
        assert secret_box.decrypt(encrypted) == plain

    def test_empty(self) -> None:
        assert secret_box.encrypt("") == ""
        assert secret_box.decrypt("") == ""

    def test_corrupt_returns_empty(self) -> None:
        assert secret_box.decrypt("not-a-valid-token") == ""


class TestUrlValidation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://eitaa.com/example", "https://eitaa.com/example"),
            ("eitaa.com/example", "https://eitaa.com/example"),
            ("@example", "https://eitaa.com/example"),
            ("example", "https://eitaa.com/example"),
            ("https://eitaa.com/joinchat/ABC123", "https://eitaa.com/joinchat/ABC123"),
            ("https://www.eitaa.com/test/", "https://eitaa.com/test"),
        ],
    )
    def test_valid(self, raw: str, expected: str) -> None:
        assert normalize_eitaa_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "https://evil.com/eitaa.com/x",   # دامنهٔ بیگانه
            "https://t.me/example",            # پیام‌رسان دیگر
            "https://127.0.0.1/x",             # SSRF
            "ftp://eitaa.com/x",               # پروتکل غیرمجاز
            "https://eitaa.com",               # بدون مسیر
            "x" * 400,                         # طول غیرعادی
        ],
    )
    def test_invalid(self, raw: str) -> None:
        assert normalize_eitaa_url(raw) is None


class TestPathSafety:
    @pytest.mark.parametrize(
        "name", ["../../etc/passwd", "/etc/passwd", "..\\..\\win.ini", "a/b/c.txt"]
    )
    def test_traversal_blocked(self, name: str, tmp_path) -> None:
        resolved = resolve_inside(tmp_path, name)
        assert tmp_path.resolve() in resolved.parents
        assert ".." not in resolved.name

    def test_safe_filename(self) -> None:
        assert safe_filename("گزارش job#1.csv") != ""
        assert "/" not in safe_filename("a/b")
        assert safe_filename("") == "export"


class TestInputCleaning:
    def test_control_chars_removed(self) -> None:
        assert "\x00" not in clean_text("ab\x00cd")

    def test_newline_kept(self) -> None:
        assert clean_text("a\nb") == "a\nb"

    def test_limit(self) -> None:
        assert len(clean_text("x" * 9000, 100)) == 100


class TestRateLimiter:
    def test_blocks_after_limit(self) -> None:
        limiter = RateLimiter(max_events=3, window=60)
        assert all(limiter.allow(1) for _ in range(3))
        assert limiter.allow(1) is False

    def test_users_are_independent(self) -> None:
        limiter = RateLimiter(max_events=1, window=60)
        assert limiter.allow(1) is True
        assert limiter.allow(2) is True
        assert limiter.allow(1) is False
