"""پیکربندی مشترک تست‌ها."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# محیط تست — پیش از ایمپورت app.config تنظیم می‌شود
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN_abcdefghijklmnopqrstuvwx")
os.environ.setdefault("ADMIN_IDS", "1001,1002")
os.environ.setdefault("SECRET_KEY", "")
os.environ.setdefault("LOG_LEVEL", "CRITICAL")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
async def db(tmp_path):
    """دیتابیس واقعی SQLite روی فایل موقت."""
    from app.db.database import Database

    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()
