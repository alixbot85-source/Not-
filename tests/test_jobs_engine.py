"""تست موتور Job — Stop/Pause/Resume واقعی و بازیابی پس از restart."""
from __future__ import annotations

import asyncio

import pytest

from app.db.models import ItemStatus, JobStatus, JobType
from app.services.jobs import (
    JobManager,
    cooperative_wait,
    format_duration,
    run_with_retry,
)

pytestmark = pytest.mark.asyncio


class TestStop:
    async def test_stop_actually_halts_processing(self, db) -> None:
        """Stop واقعی است: پردازش باید قبل از اتمام همهٔ آیتم‌ها بایستد."""
        job_id = await db.create_job(JobType.JOINER, None)
        await db.add_job_items(job_id, [(f"item{i}", f"T{i}") for i in range(50)])
        await db.set_job_total(job_id, 50)

        manager = JobManager(db)
        processed: list[str] = []

        async def worker(handle) -> None:
            for item in await db.pending_items(job_id):
                if not await cooperative_wait(handle, 0):
                    break
                processed.append(item.ref)
                await db.set_item_status(job_id, item.ref, ItemStatus.SUCCESS)
                await db.bump_job_counters(job_id, processed=1, success=1)
                if not await cooperative_wait(handle, 0.02):
                    break

        handle = manager.spawn(job_id, worker)
        await asyncio.sleep(0.12)
        await manager.request_stop(job_id)
        await asyncio.wait_for(handle.task, timeout=5)

        assert 0 < len(processed) < 50               # واقعاً وسط کار ایستاد
        assert (await db.get_job(job_id)).status is JobStatus.STOPPING

    async def test_stop_on_unknown_job(self, db) -> None:
        assert await JobManager(db).request_stop(9999) is False


class TestPauseResume:
    async def test_pause_blocks_then_resume_continues(self, db) -> None:
        """Pause/Resume واقعی است چون روی asyncio.Event پیاده شده."""
        job_id = await db.create_job(JobType.SENDER, None)
        await db.add_job_items(job_id, [(f"i{i}", "") for i in range(40)])

        manager = JobManager(db)
        counter = {"n": 0}

        async def worker(handle) -> None:
            for item in await db.pending_items(job_id):
                if not await cooperative_wait(handle, 0):
                    break
                counter["n"] += 1
                await db.set_item_status(job_id, item.ref, ItemStatus.SUCCESS)
                if not await cooperative_wait(handle, 0.02):
                    break

        handle = manager.spawn(job_id, worker)
        await asyncio.sleep(0.08)
        assert await manager.pause(job_id) is True

        paused_at = counter["n"]
        await asyncio.sleep(0.15)
        assert counter["n"] == paused_at            # واقعاً متوقف مانده

        assert await manager.resume(job_id) is True
        await asyncio.sleep(0.12)
        assert counter["n"] > paused_at             # واقعاً ادامه یافت

        await manager.request_stop(job_id)
        await asyncio.wait_for(handle.task, timeout=5)

    async def test_double_pause_rejected(self, db) -> None:
        job_id = await db.create_job(JobType.JOINER, None)
        manager = JobManager(db)

        async def worker(handle) -> None:
            await handle.stop_event.wait()

        handle = manager.spawn(job_id, worker)
        await asyncio.sleep(0.02)
        assert await manager.pause(job_id) is True
        assert await manager.pause(job_id) is False
        await manager.request_stop(job_id)
        await asyncio.wait_for(handle.task, timeout=5)


class TestRecovery:
    async def test_orphan_with_pending_is_recoverable(self, db) -> None:
        """بخش ۳۱: Job نیمه‌کاره باید RECOVERABLE شود."""
        job_id = await db.create_job(JobType.JOINER, None)
        await db.add_job_items(job_id, [("a", ""), ("b", "")])
        await db.set_job_total(job_id, 2)
        await db.set_item_status(job_id, "a", ItemStatus.SUCCESS)
        await db.set_job_status(job_id, JobStatus.RUNNING)

        recovered = await JobManager(db).recover_orphans()
        assert job_id in recovered
        job = await db.get_job(job_id)
        assert job.status is JobStatus.STOPPED
        assert job.recoverable is True

    async def test_orphan_without_pending_is_not_recoverable(self, db) -> None:
        """اگر چیزی برای ادامه نباشد، NOT RECOVERABLE — بدون تظاهر."""
        job_id = await db.create_job(JobType.SENDER, None)
        await db.add_job_items(job_id, [("a", "")])
        await db.set_item_status(job_id, "a", ItemStatus.SUCCESS)
        await db.set_job_status(job_id, JobStatus.RUNNING)

        await JobManager(db).recover_orphans()
        assert (await db.get_job(job_id)).recoverable is False


class TestRetry:
    async def test_succeeds_after_transient_failures(self) -> None:
        attempts = {"n": 0}

        async def flaky() -> str:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("موقت")
            return "ok"

        result = await run_with_retry(flaky, retries=3, backoff=0.01)
        assert result == "ok" and attempts["n"] == 3

    async def test_raises_after_exhausting_retries(self) -> None:
        async def always_fail() -> None:
            raise ValueError("همیشه خطا")

        with pytest.raises(ValueError):
            await run_with_retry(always_fail, retries=2, backoff=0.01)


class TestFailureIsolation:
    async def test_worker_exception_marks_job_failed(self, db) -> None:
        """خطای Worker نباید بی‌صدا گم شود."""
        job_id = await db.create_job(JobType.JOINER, None)
        manager = JobManager(db)

        async def broken(handle) -> None:
            raise RuntimeError("خرابی عمدی")

        handle = manager.spawn(job_id, broken)
        await asyncio.wait_for(handle.task, timeout=5)

        job = await db.get_job(job_id)
        assert job.status is JobStatus.FAILED
        assert job.error


@pytest.mark.filterwarnings("ignore")
class TestHelpers:
    async def test_format_duration(self) -> None:
        assert format_duration(0) == "00:00"
        assert format_duration(65) == "01:05"
        assert format_duration(192) == "03:12"
        assert format_duration(-5) == "00:00"
