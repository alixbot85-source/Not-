"""
موتور Job — اجرای غیرمسدودکنندهٔ عملیات طولانی (بخش ۳۰).

ویژگی‌های واقعی:
  • هر Job یک Task مستقل asyncio است؛ حلقهٔ اصلی ربات مسدود نمی‌شود.
  • Stop تعاونی و **واقعی** است: پرچم بررسی می‌شود و Job در امن‌ترین نقطه می‌ایستد.
  • Pause/Resume واقعی است چون وضعیت هر آیتم در دیتابیس ذخیره می‌شود
    و اجرای بعدی فقط آیتم‌های PENDING را برمی‌دارد.
  • Retry با backoff نمایی و رعایت تأخیر بین عملیات.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.db.database import Database
from app.db.models import JobStatus, LogLevel
from app.security import redact

log = logging.getLogger(__name__)


@dataclass(slots=True)
class JobHandle:
    """کنترل زندهٔ یک Job در حال اجرا."""

    job_id: int
    task: asyncio.Task[Any] | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    current: str = ""
    started: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.pause_event.set()  # ست = در حال اجرا (pause نیست)

    @property
    def is_paused(self) -> bool:
        return not self.pause_event.is_set()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started


class JobManager:
    """رجیستری Jobهای فعال + بازیابی پس از restart (بخش ۳۱)."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._handles: dict[int, JobHandle] = {}

    # ───────────────────────── registry ─────────────────────────
    def get(self, job_id: int) -> JobHandle | None:
        return self._handles.get(job_id)

    def is_running(self, job_id: int) -> bool:
        handle = self._handles.get(job_id)
        return handle is not None and handle.task is not None and not handle.task.done()

    def active_ids(self) -> list[int]:
        return [jid for jid in self._handles if self.is_running(jid)]

    # ───────────────────────── control ──────────────────────────
    async def request_stop(self, job_id: int) -> bool:
        handle = self._handles.get(job_id)
        if handle is None:
            return False
        handle.stop_event.set()
        handle.pause_event.set()  # آزادسازی در صورت pause بودن
        await self.db.set_job_status(job_id, JobStatus.STOPPING)
        await self.db.add_log(job_id, LogLevel.WARNING, "درخواست توقف ثبت شد")
        return True

    async def pause(self, job_id: int) -> bool:
        handle = self._handles.get(job_id)
        if handle is None or handle.is_paused:
            return False
        handle.pause_event.clear()
        await self.db.add_log(job_id, LogLevel.INFO, "عملیات موقتاً متوقف شد")
        return True

    async def resume(self, job_id: int) -> bool:
        handle = self._handles.get(job_id)
        if handle is None or not handle.is_paused:
            return False
        handle.pause_event.set()
        await self.db.add_log(job_id, LogLevel.INFO, "عملیات از سر گرفته شد")
        return True

    # ───────────────────────── execution ────────────────────────
    def spawn(
        self,
        job_id: int,
        coro_factory: Callable[[JobHandle], Awaitable[None]],
    ) -> JobHandle:
        """اجرای Job در پس‌زمینه و بازگرداندن کنترل بلافاصله."""
        handle = JobHandle(job_id=job_id)
        self._handles[job_id] = handle

        async def runner() -> None:
            try:
                await self.db.set_job_status(job_id, JobStatus.RUNNING)
                await coro_factory(handle)
            except asyncio.CancelledError:
                await self.db.set_job_status(job_id, JobStatus.CANCELLED, recoverable=True)
                await self.db.add_log(job_id, LogLevel.WARNING, "عملیات لغو شد")
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("job %s failed", job_id)
                await self.db.set_job_status(
                    job_id, JobStatus.FAILED, error=redact(exc)[:300], recoverable=True
                )
                await self.db.add_log(job_id, LogLevel.ERROR, f"خطای اجرا: {redact(exc)[:150]}")
            finally:
                self._handles.pop(job_id, None)

        handle.task = asyncio.create_task(runner(), name=f"job-{job_id}")
        return handle

    async def shutdown(self) -> None:
        """خاموشی تمیز: Jobهای فعال به‌عنوان قابل‌بازیابی علامت می‌خورند."""
        for job_id, handle in list(self._handles.items()):
            handle.stop_event.set()
            if handle.task is not None:
                handle.task.cancel()
            await self.db.set_job_status(job_id, JobStatus.STOPPED, recoverable=True)

    # ───────────────────────── recovery ─────────────────────────
    async def recover_orphans(self) -> list[int]:
        """
        پس از restart، Jobهایی که در وضعیت RUNNING مانده‌اند را علامت‌گذاری می‌کند.

        صداقت فنی: اجرای خودکار از سر گرفته **نمی‌شود**. فقط وضعیت واقعی ثبت
        می‌شود و کاربر می‌تواند ادامه دهد، چون پیشرفت هر آیتم در دیتابیس است.
        Jobای که هیچ آیتم PENDING نداشته باشد NOT RECOVERABLE است.
        """
        recovered: list[int] = []
        for job in await self.db.running_jobs():
            pending = await self.db.pending_items(job.id)
            can_resume = bool(pending)
            await self.db.set_job_status(
                job.id, JobStatus.STOPPED, error="", recoverable=can_resume
            )
            await self.db.add_log(
                job.id,
                LogLevel.WARNING,
                f"بازیابی پس از راه‌اندازی مجدد — {job.processed}/{job.total} "
                + ("قابل ادامه" if can_resume else "غیرقابل ادامه"),
            )
            recovered.append(job.id)
        return recovered


# ══════════════════════════════════════════════════════════════════
#  کمک‌کننده‌های اجرا
# ══════════════════════════════════════════════════════════════════
async def cooperative_wait(handle: JobHandle, delay: float) -> bool:
    """
    تأخیر بین عملیات با احترام به Stop/Pause.
    خروجی False یعنی باید متوقف شویم.
    """
    await handle.pause_event.wait()
    if handle.stop_event.is_set():
        return False
    if delay > 0:
        try:
            await asyncio.wait_for(handle.stop_event.wait(), timeout=delay)
            return False  # در طول انتظار Stop رسید
        except asyncio.TimeoutError:
            pass
    return not handle.stop_event.is_set()


async def run_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    retries: int,
    backoff: float,
    handle: JobHandle | None = None,
) -> Any:
    """اجرای یک عملیات با تلاش مجدد و backoff نمایی."""
    attempt = 0
    last_error: Exception | None = None
    while attempt <= retries:
        if handle is not None and handle.stop_event.is_set():
            break
        try:
            return await operation()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            attempt += 1
            if attempt > retries:
                break
            wait = backoff * (2 ** (attempt - 1))
            log.info("retry %s/%s after %.1fs: %s", attempt, retries, wait, redact(exc))
            if handle is not None:
                if not await cooperative_wait(handle, wait):
                    break
            else:
                await asyncio.sleep(wait)
    if last_error is not None:
        raise last_error
    return None


async def finalize_job(db: Database, handle: JobHandle, job_id: int) -> JobStatus:
    """تعیین وضعیت نهایی بر اساس اینکه Stop خورده یا کامل شده."""
    status = JobStatus.STOPPED if handle.stop_event.is_set() else JobStatus.COMPLETED
    remaining = await db.pending_items(job_id)
    await db.set_job_status(job_id, status, recoverable=bool(remaining))
    await db.add_log(
        job_id,
        LogLevel.SUCCESS if status is JobStatus.COMPLETED else LogLevel.WARNING,
        "عملیات کامل شد" if status is JobStatus.COMPLETED else "عملیات متوقف شد",
    )
    return status


def format_duration(seconds: float) -> str:
    total = int(max(0, seconds))
    return f"{total // 60:02d}:{total % 60:02d}"
