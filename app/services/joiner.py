"""
سرویس Joiner (بخش ششم).

جریان واقعی:
  مرحلهٔ ۱ — عضویت در لینکدونی‌های انتخاب‌شده (در صورت پشتیبانی Backend)
  مرحلهٔ ۲ — خواندن محتوای عمومی لینکدونی‌ها و استخراج لینک + Deduplication
  مرحلهٔ ۳ — گزارش آمار استخراج
  مرحلهٔ ۴ — عضویت در گروه‌ها با پیشرفت زنده و امکان توقف
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.config import config
from app.db.database import Database
from app.db.models import ItemStatus, LinkKind, LogLevel
from app.eitaa.base import EitaaBackend, EitaaError, OpResult
from app.eitaa.extractor import (
    ExtractionStats,
    LinkExtractor,
    classify,
    deduplicate,
)
from app.security import normalize_eitaa_url, redact
from app.services.jobs import JobHandle, cooperative_wait

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], Awaitable[None]]


async def run_extraction(
    db: Database,
    job_id: int,
    linkdoni_urls: list[tuple[int, str]],
    handle: JobHandle,
    extractor: LinkExtractor,
    backend: EitaaBackend | None = None,
    on_progress: ProgressCallback | None = None,
) -> ExtractionStats:
    """
    مراحل ۱ تا ۳: عضویت در لینکدونی (اگر ممکن باشد) و استخراج لینک.
    """
    stats = ExtractionStats()
    await db.set_job_total(job_id, len(linkdoni_urls))
    await db.add_log(job_id, LogLevel.INFO, f"شروع استخراج از {len(linkdoni_urls)} لینکدونی")

    collected: list[tuple[str, str]] = []  # (url, source)

    for index, (linkdoni_id, url) in enumerate(linkdoni_urls, start=1):
        if not await cooperative_wait(handle, 0):
            break
        handle.current = url

        # ── مرحلهٔ ۱: تلاش برای عضویت در خود لینکدونی ──
        if backend is not None:
            try:
                result = await backend.join(url)
                if result.ok:
                    await db.set_linkdoni_status(linkdoni_id, "JOINED")
                    await db.add_log(job_id, LogLevel.SUCCESS, f"عضویت در لینکدونی: {url}")
                elif result.already:
                    await db.set_linkdoni_status(linkdoni_id, "ALREADY")
                elif result.invalid:
                    await db.set_linkdoni_status(linkdoni_id, "INVALID")
                    await db.add_log(job_id, LogLevel.WARNING, f"لینکدونی نامعتبر: {url}")
                else:
                    await db.set_linkdoni_status(linkdoni_id, "FAILED")
            except EitaaError as exc:
                await db.add_log(
                    job_id, LogLevel.WARNING, f"عضویت در لینکدونی ممکن نشد: {exc.message}"
                )

        # ── مرحلهٔ ۲: استخراج لینک از محتوای عمومی ──
        links, error = await extractor.fetch_links(url)
        if error:
            await db.add_log(job_id, LogLevel.WARNING, f"{url} — {error}")
        else:
            collected.extend((link, url) for link in links)
            await db.add_log(
                job_id, LogLevel.INFO, f"{url} — {len(links)} لینک خام یافت شد"
            )

        stats.checked += 1
        await db.bump_job_counters(job_id, processed=1)
        if on_progress is not None:
            await on_progress(index, len(linkdoni_urls), url)
        if not await cooperative_wait(handle, 1.0):
            break

    # ── Deduplication و طبقه‌بندی ──
    raw_urls = [u for u, _ in collected]
    stats.found = len(raw_urls)
    unique, duplicates = deduplicate(raw_urls)
    stats.duplicates = duplicates

    source_map = dict(collected)
    rows: list[tuple[str, LinkKind, str]] = []
    for url in unique:
        normalized = normalize_eitaa_url(url)
        if normalized is None:
            stats.invalid += 1
            continue
        kind = classify(normalized)
        stats.by_kind[kind] = stats.by_kind.get(kind, 0) + 1
        rows.append((normalized, kind, source_map.get(url, "")))

    if rows:
        await db.add_links(job_id, rows)
    await db.add_log(
        job_id,
        LogLevel.SUCCESS,
        f"استخراج پایان یافت: {stats.found} یافت‌شده، {duplicates} تکراری، {stats.invalid} نامعتبر",
    )
    return stats


async def run_join(
    db: Database,
    job_id: int,
    backend: EitaaBackend,
    handle: JobHandle,
    on_progress: ProgressCallback | None = None,
) -> None:
    """
    مرحلهٔ ۴: عضویت در گروه‌ها.
    فقط آیتم‌های PENDING پردازش می‌شوند تا ادامه پس از توقف/restart درست کار کند.
    """
    items = await db.pending_items(job_id)
    job = await db.get_job(job_id)
    total = job.total if job else len(items)
    await db.add_log(job_id, LogLevel.INFO, f"شروع عضویت — {len(items)} مورد در صف")

    done = job.processed if job else 0
    for item in items:
        if not await cooperative_wait(handle, 0):
            break
        handle.current = item.title or item.ref

        try:
            result: OpResult = await backend.join(item.ref)
        except EitaaError as exc:
            result = OpResult.failure(exc.message)
        except Exception as exc:  # noqa: BLE001
            log.warning("join error: %s", redact(exc))
            result = OpResult.failure("خطای غیرمنتظره")

        if result.ok:
            await db.set_item_status(job_id, item.ref, ItemStatus.SUCCESS)
            await db.bump_job_counters(job_id, processed=1, success=1)
            await db.add_log(job_id, LogLevel.SUCCESS, f"عضویت: {item.ref}")
        elif result.already:
            await db.set_item_status(job_id, item.ref, ItemStatus.ALREADY, result.reason)
            await db.bump_job_counters(job_id, processed=1, already=1)
        elif result.invalid:
            await db.set_item_status(job_id, item.ref, ItemStatus.INVALID, result.reason)
            await db.bump_job_counters(job_id, processed=1, failed=1)
            await db.add_log(job_id, LogLevel.WARNING, f"نامعتبر: {item.ref}")
        else:
            await db.set_item_status(job_id, item.ref, ItemStatus.FAILED, result.reason)
            await db.bump_job_counters(job_id, processed=1, failed=1)
            await db.add_log(job_id, LogLevel.ERROR, f"ناموفق: {item.ref} — {result.reason}")

        done += 1
        if on_progress is not None:
            await on_progress(done, total, handle.current)

        if not await cooperative_wait(handle, config.join_delay):
            break


async def prepare_join_items(db: Database, job_id: int, source_job_id: int) -> int:
    """
    لینک‌های قابل عضویت را از نتیجهٔ استخراج به صف Job منتقل می‌کند.

    طبق بخش ۶: فقط لینک‌هایی که نوعشان قطعی است (GROUP یا INVITE) استفاده می‌شوند.
    موارد UNKNOWN عمداً کنار گذاشته می‌شوند — حدس زده نمی‌شود.
    """
    joinable: list[tuple[str, str]] = []
    for kind in (LinkKind.GROUP, LinkKind.INVITE):
        for link in await db.list_links(source_job_id, kind=kind):
            joinable.append((link.url, link.url.split("/")[-1]))
    if joinable:
        await db.add_job_items(job_id, joinable)
        await db.set_job_total(job_id, len(joinable))
    return len(joinable)


async def mark_unknown_skipped(db: Database, job_id: int) -> int:
    """تعداد لینک‌هایی که به‌دلیل نامشخص بودن نوع، پردازش نمی‌شوند."""
    return await db.count_links(job_id, kind=LinkKind.UNKNOWN)
