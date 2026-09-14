"""
سرویس Sender (بخش نهم و دوازدهم).

ارسال به مقصدها با پیشرفت زنده، تأخیر قابل تنظیم، توقف تعاونی و ثبت نتیجهٔ هر مورد.
Media فقط در صورتی ارسال می‌شود که Backend واقعاً از آن پشتیبانی کند.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.config import config
from app.db.database import Database
from app.db.models import ItemStatus, LogLevel
from app.eitaa.base import Capability, EitaaBackend, EitaaError, OpResult
from app.security import redact
from app.services.jobs import JobHandle, cooperative_wait

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], Awaitable[None]]


async def run_send(
    db: Database,
    job_id: int,
    backend: EitaaBackend,
    handle: JobHandle,
    text: str,
    media_path: str = "",
    on_progress: ProgressCallback | None = None,
) -> None:
    """ارسال پیام به تمام آیتم‌های PENDING این Job."""
    items = await db.pending_items(job_id)
    job = await db.get_job(job_id)
    total = job.total if job else len(items)
    done = job.processed if job else 0

    use_media = bool(media_path) and backend.can_send_media is Capability.AVAILABLE
    if media_path and not use_media:
        await db.add_log(
            job_id,
            LogLevel.WARNING,
            "این اکانت از ارسال فایل پشتیبانی نمی‌کند؛ فقط متن ارسال می‌شود.",
        )

    await db.add_log(job_id, LogLevel.INFO, f"شروع ارسال — {len(items)} مقصد در صف")

    for item in items:
        if not await cooperative_wait(handle, 0):
            break
        handle.current = item.title or item.ref

        try:
            if use_media:
                result: OpResult = await backend.send_media(item.ref, media_path, text)
            else:
                result = await backend.send_text(item.ref, text)
        except EitaaError as exc:
            result = OpResult.failure(exc.message)
        except Exception as exc:  # noqa: BLE001
            log.warning("send error: %s", redact(exc))
            result = OpResult.failure("خطای غیرمنتظره")

        if result.ok:
            await db.set_item_status(job_id, item.ref, ItemStatus.SUCCESS)
            await db.bump_job_counters(job_id, processed=1, success=1)
            await db.add_log(job_id, LogLevel.SUCCESS, f"ارسال شد: {item.ref}")
        elif result.invalid:
            await db.set_item_status(job_id, item.ref, ItemStatus.INVALID, result.reason)
            await db.bump_job_counters(job_id, processed=1, failed=1)
            await db.add_log(job_id, LogLevel.WARNING, f"مقصد نامعتبر: {item.ref}")
        else:
            await db.set_item_status(job_id, item.ref, ItemStatus.FAILED, result.reason)
            await db.bump_job_counters(job_id, processed=1, failed=1)
            await db.add_log(job_id, LogLevel.ERROR, f"ناموفق: {item.ref} — {result.reason}")

        done += 1
        if on_progress is not None:
            await on_progress(done, total, handle.current)

        if not await cooperative_wait(handle, config.send_delay):
            break


async def load_targets(
    backend: EitaaBackend, kind: str, limit: int = 300
) -> tuple[list[tuple[str, str]], str]:
    """
    بارگذاری مقصدها از Backend.
    خروجی: (آیتم‌ها، پیام خطا). خطای غیرخالی یعنی قابلیت در دسترس نیست.
    """
    mapping = {
        "GROUPS": (backend.can_list_groups, backend.list_groups),
        "CONTACTS": (backend.can_list_contacts, backend.list_contacts),
        "PRIVATE": (backend.can_list_private, backend.list_private),
    }
    if kind not in mapping:
        return [], "نوع مقصد پشتیبانی نمی‌شود."

    capability, loader = mapping[kind]
    if capability is not Capability.AVAILABLE:
        return [], (
            "این قابلیت برای نوع اکانت انتخاب‌شده در دسترس نیست.\n"
            "برای دریافت فهرست گروه‌ها/مخاطبین، اکانت از نوع نشست کاربری لازم است."
        )
    try:
        targets = await loader(limit)
    except EitaaError as exc:
        return [], exc.message
    except Exception as exc:  # noqa: BLE001
        log.warning("load targets failed: %s", redact(exc))
        return [], "دریافت فهرست مقصدها انجام نشد."
    return [(t.ref, t.title) for t in targets], ""


def parse_manual_targets(raw: str) -> list[tuple[str, str]]:
    """
    تبدیل ورودی دستی کاربر به فهرست مقصد.
    هر خط یا هر مقدار جداشده با کاما یک مقصد است.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for chunk in raw.replace(",", "\n").splitlines():
        value = chunk.strip().lstrip("@")
        if "eitaa.com/" in value:
            value = value.split("eitaa.com/", 1)[1].strip("/")
        if not value or value in seen or len(value) > 100:
            continue
        seen.add(value)
        out.append((value, value))
    return out
