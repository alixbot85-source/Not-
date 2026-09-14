"""پیکربندی مرکزی — همهٔ مقادیر حساس از محیط خوانده می‌شوند، نه از کد."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """خوانندهٔ سادهٔ .env بدون وابستگی اضافه. متغیرهای محیطی موجود بازنویسی نمی‌شوند."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    return (os.getenv(name, "") or str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str = "") -> list[str]:
    return [p.strip() for p in (os.getenv(name, "") or default).split(",") if p.strip()]


@dataclass(frozen=True)
class Config:
    # --- Telegram ---
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", "").strip())
    admin_ids: frozenset[int] = field(
        default_factory=lambda: frozenset(
            int(x) for x in _csv("ADMIN_IDS") if x.lstrip("-").isdigit()
        )
    )

    # --- امنیت ---
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "").strip())

    # --- مسیرها ---
    data_dir: Path = field(default_factory=lambda: BASE_DIR / (os.getenv("DATA_DIR") or "data"))
    log_dir: Path = field(default_factory=lambda: BASE_DIR / (os.getenv("LOG_DIR") or "logs"))
    export_dir: Path = field(default_factory=lambda: BASE_DIR / (os.getenv("EXPORT_DIR") or "exports"))
    font_path: Path = field(
        default_factory=lambda: BASE_DIR
        / (os.getenv("PERSIAN_FONT_PATH") or "assets/fonts/Vazirmatn-Regular.ttf")
    )

    # --- رفتار عملیات ---
    join_delay: float = field(default_factory=lambda: _float("JOIN_DELAY", 4.0))
    send_delay: float = field(default_factory=lambda: _float("SEND_DELAY", 2.5))
    max_retries: int = field(default_factory=lambda: _int("MAX_RETRIES", 3))
    retry_backoff: float = field(default_factory=lambda: _float("RETRY_BACKOFF", 2.0))
    progress_edit_interval: float = field(
        default_factory=lambda: _float("PROGRESS_EDIT_INTERVAL", 3.0)
    )
    page_size: int = field(default_factory=lambda: max(3, _int("PAGE_SIZE", 8)))

    # --- rate limit پنل ---
    rate_limit_events: int = field(default_factory=lambda: _int("RATE_LIMIT_EVENTS", 20))
    rate_limit_window: float = field(default_factory=lambda: _float("RATE_LIMIT_WINDOW", 10.0))

    # --- لینکدونی پیش‌فرض ---
    default_linkdoni: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            _csv("DEFAULT_LINKDONI", "https://eitaa.com/linkdoni,https://eitaa.com/goroh_yab")
        )
    )

    # --- پراکسی برای دسترسی به api.telegram.org (اختیاری) ---
    proxy_url: str = field(
        default_factory=lambda: (os.getenv("TELEGRAM_PROXY") or "").strip()
    )

    # --- پل MTProto ایتا (اختیاری — سرویس بیرونی EitaaBun) ---
    bridge_url: str = field(
        default_factory=lambda: (os.getenv("EITAA_BRIDGE_URL") or "").strip().rstrip("/")
    )

    # --- AI (اختیاری) ---
    ai_enabled: bool = field(default_factory=lambda: _bool("AI_ENABLED", False))
    ai_base_url: str = field(
        default_factory=lambda: (os.getenv("AI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    )
    ai_api_key: str = field(default_factory=lambda: os.getenv("AI_API_KEY", "").strip())
    ai_model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "gpt-4o-mini").strip())

    # --- لاگ ---
    log_level: str = field(default_factory=lambda: (os.getenv("LOG_LEVEL") or "INFO").upper())

    # ------------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "panel.db"

    @property
    def session_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def media_dir(self) -> Path:
        """محل نگهداری فایل‌های پیوست‌شده به پیام‌های Sender."""
        return self.data_dir / "media"

    @property
    def bridge_ready(self) -> bool:
        """پل فقط وقتی فعال است که آدرسش تنظیم شده باشد."""
        return bool(self.bridge_url)

    @property
    def ai_ready(self) -> bool:
        """AI فقط وقتی فعال است که هم روشن باشد هم کلید واقعی داشته باشد."""
        return self.ai_enabled and bool(self.ai_api_key)

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.log_dir,
            self.export_dir,
            self.session_dir,
            self.media_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        try:  # نشست‌ها فقط برای مالک
            os.chmod(self.session_dir, 0o700)
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass

    def validate(self) -> list[str]:
        """خطاهای پیکربندی را برمی‌گرداند (خالی = سالم)."""
        errors: list[str] = []
        if not self.bot_token:
            errors.append("BOT_TOKEN تنظیم نشده است.")
        elif ":" not in self.bot_token:
            errors.append("BOT_TOKEN معتبر نیست (قالب مورد انتظار: <id>:<hash>).")
        if not self.admin_ids:
            errors.append("ADMIN_IDS تنظیم نشده است — پنل بدون ادمین قابل استفاده نیست.")
        return errors

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids


config = Config()
