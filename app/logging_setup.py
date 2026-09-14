"""پیکربندی لاگ (بخش ۱۹) — با تضمین حذف اسرار از خروجی."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from app.security import RedactingFilter

FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    redactor = RedactingFilter()
    formatter = logging.Formatter(FORMAT, DATE_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redactor)
    root.addHandler(console)

    # فایل چرخشی — جزئیات کامل اینجا ذخیره می‌شود
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redactor)
    root.addHandler(file_handler)

    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler.addFilter(redactor)
    root.addHandler(error_handler)

    # کاهش نویز کتابخانه‌ها
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
