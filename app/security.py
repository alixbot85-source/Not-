"""لایهٔ امنیت: رمزنگاری اسرار، پاک‌سازی لاگ، اعتبارسنجی ورودی و مسیر، Rate limit."""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from app.config import config

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
#  ۱) رمزنگاری اسرار (Token / Session) پیش از ذخیره در دیتابیس
# ══════════════════════════════════════════════════════════════════
_KEY_FILE = "secret.key"


def _load_or_create_key() -> bytes:
    if config.secret_key:
        key = config.secret_key.encode()
        try:
            Fernet(key)
            return key
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "SECRET_KEY معتبر نیست. یک کلید Fernet بسازید:\n"
                '  python -c "from cryptography.fernet import Fernet;'
                'print(Fernet.generate_key().decode())"'
            ) from exc

    config.data_dir.mkdir(parents=True, exist_ok=True)
    path = config.data_dir / _KEY_FILE
    if path.is_file():
        return path.read_bytes().strip()

    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)  # فقط مالک
    except OSError:
        pass
    log.warning("کلید رمزنگاری جدید ساخته شد: %s (آن را از دست ندهید)", path)
    return key


class SecretBox:
    """رمزگذاری/رمزگشایی متقارن با Fernet (AES-128-CBC + HMAC)."""

    def __init__(self) -> None:
        self._fernet: Fernet | None = None

    @property
    def fernet(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(_load_or_create_key())
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        return self.fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            return self.fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, ValueError):
            log.error("رمزگشایی ناموفق بود — کلید عوض شده یا داده خراب است.")
            return ""


secret_box = SecretBox()


# ══════════════════════════════════════════════════════════════════
#  ۲) پاک‌سازی اسرار از لاگ و UI  (بخش ۱۹ و ۲۸)
# ══════════════════════════════════════════════════════════════════
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bbot\d+:[A-Za-z0-9_\-]{6,}", re.I),             # توکن eitaayar
    re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{30,}"),                   # توکن ربات تلگرام
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I),  # UUID
    re.compile(r"(?i)\b(token|api[_-]?key|secret|password|session|auth_key)\b\s*[=:]\s*\S+"),
    re.compile(r"\bgAAAAA[0-9A-Za-z_\-=]{10,}"),                   # Fernet
)


def redact(text: object) -> str:
    """هر رشته‌ای که شبیه توکن/سشن/کلید است را با [REDACTED] جایگزین می‌کند."""
    out = str(text)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def _redact_arg(value: object) -> object:
    """
    فقط رشته‌ها پاک‌سازی می‌شوند.

    عدد و بقیهٔ انواع دست‌نخورده می‌مانند، وگرنه قالب‌هایی مثل
    «%d» و «%f» در پیام‌های کتابخانه‌ها می‌شکنند
    (TypeError: must be real number, not str).
    """
    if isinstance(value, str):
        return redact(value)
    return value


class RedactingFilter(logging.Filter):
    """فیلتر logging — تضمین می‌کند هیچ رازی وارد فایل لاگ نشود."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: _redact_arg(v) for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(_redact_arg(a) for a in record.args)
        except Exception:  # noqa: BLE001 — لاگ هرگز نباید برنامه را بشکند
            pass
        return True


def mask_tail(secret: str, keep: int = 4) -> str:
    """نمایش امن برای UI: فقط چند کاراکتر پایانی."""
    if not secret:
        return "—"
    if len(secret) <= keep:
        return "•" * len(secret)
    return "•" * 6 + secret[-keep:]


# ══════════════════════════════════════════════════════════════════
#  ۳) اعتبارسنجی ورودی و لینک
# ══════════════════════════════════════════════════════════════════
_ALLOWED_LINK_HOSTS = {"eitaa.com", "www.eitaa.com", "eitaa.ir", "www.eitaa.ir"}

# نام کاربری واقعی ایتا: حروف/عدد/زیرخط
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,63}$")


def normalize_eitaa_url(raw: str) -> str | None:
    """
    نرمال‌سازی لینک ایتا. در صورت نامعتبر بودن None برمی‌گرداند.
    فقط دامنه‌های واقعی ایتا پذیرفته می‌شوند (جلوگیری از SSRF و لینک بی‌ربط).
    """
    if not raw:
        return None
    value = raw.strip()
    if not value or len(value) > 300:
        return None

    if value.startswith("@"):  # @username
        name = value[1:]
        return f"https://eitaa.com/{name}" if USERNAME_RE.match(name) else None

    if not value.startswith(("http://", "https://")):
        if "/" not in value and USERNAME_RE.match(value):
            return f"https://eitaa.com/{value}"
        value = "https://" + value

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    host = parsed.netloc.split("@")[-1].split(":")[0].lower()
    if host not in _ALLOWED_LINK_HOSTS:
        return None
    try:  # IP خام مجاز نیست
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass

    path = parsed.path.rstrip("/")
    if not path or path == "":
        return None
    return f"https://eitaa.com{path}"


def safe_filename(name: str, default: str = "export") -> str:
    """
    جلوگیری از Path Traversal — فقط نام فایل ساده.

    هر کاراکتر غیرمجاز به «_» تبدیل می‌شود و سپس تمام نقطه/زیرخط‌های ابتدایی
    به‌صورت تکراری حذف می‌شوند تا دنباله‌هایی مثل «..» در ابتدای نام باقی نماند.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._\-]", "_", (name or "").strip())
    cleaned = re.sub(r"\.{2,}", ".", cleaned)   # هیچ «..» باقی نماند
    cleaned = cleaned.lstrip("._")              # نقطه/زیرخط ابتدایی حذف شود
    cleaned = cleaned.rstrip("_")[:80]
    return cleaned or default


def resolve_inside(base: Path, filename: str) -> Path:
    """مسیر را داخل base محدود می‌کند؛ در صورت فرار، خطا می‌دهد."""
    base = base.resolve()
    target = (base / safe_filename(filename)).resolve()
    if base != target and base not in target.parents:
        raise ValueError("مسیر فایل خارج از پوشهٔ مجاز است.")
    return target


def clean_text(value: str, limit: int = 4096) -> str:
    """حذف کاراکترهای کنترلی و محدودسازی طول."""
    if not value:
        return ""
    text = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return text[:limit]


# ══════════════════════════════════════════════════════════════════
#  ۴) Rate limit ورودی پنل  (بخش ۲۸)
# ══════════════════════════════════════════════════════════════════
class RateLimiter:
    """پنجرهٔ کشویی ساده به ازای هر کاربر."""

    def __init__(self, max_events: int, window: float) -> None:
        self.max_events = max(1, max_events)
        self.window = max(1.0, window)
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        bucket = self._hits[user_id]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.max_events:
            return False
        bucket.append(now)
        return True

    def retry_after(self, user_id: int) -> float:
        bucket = self._hits.get(user_id)
        if not bucket:
            return 0.0
        return max(0.0, self.window - (time.monotonic() - bucket[0]))
