"""تست دیتابیس — اکانت، لینکدونی، Job، لاگ و Dedup."""
from __future__ import annotations

import pytest

from app.db.models import (
    AccountKind,
    AccountStatus,
    ItemStatus,
    JobStatus,
    JobType,
    LinkKind,
    LogLevel,
)

pytestmark = pytest.mark.asyncio


class TestAccounts:
    async def test_secret_is_encrypted_at_rest(self, db) -> None:
        token = "bot777:super-secret-uuid-value-1234"
        account_id = await db.add_account("تست", AccountKind.BOT_API, secret=token)

        cursor = await db.conn.execute(
            "SELECT secret_enc FROM accounts WHERE id=?", (account_id,)
        )
        stored = (await cursor.fetchone())["secret_enc"]
        assert token not in stored            # روی دیسک رمز است
        assert await db.get_account_secret(account_id) == token  # قابل بازیابی

    async def test_account_object_never_exposes_secret(self, db) -> None:
        """رکورد Account که به UI می‌رسد نباید هیچ ردی از راز داشته باشد."""
        account_id = await db.add_account("x", AccountKind.BOT_API, secret="bot1:abcSECRET")
        account = await db.get_account(account_id)
        exposed = " ".join(
            str(getattr(account, field, "")) for field in account.__slots__
        )
        assert "abcSECRET" not in exposed
        assert not hasattr(account, "secret_enc")

    async def test_capability_flags(self, db) -> None:
        bot_id = await db.add_account("bot", AccountKind.BOT_API, secret="t")
        ses_id = await db.add_account("ses", AccountKind.MTPROTO, session_name="s1")
        assert (await db.get_account(bot_id)).can_join is False
        assert (await db.get_account(ses_id)).can_join is True

    async def test_status_update_and_delete(self, db) -> None:
        account_id = await db.add_account("x", AccountKind.BOT_API, secret="t")
        await db.update_account_status(account_id, AccountStatus.ONLINE, "ok", "کانال")
        account = await db.get_account(account_id)
        assert account.status is AccountStatus.ONLINE
        assert account.identity == "کانال"
        assert await db.delete_account(account_id) is True
        assert await db.get_account(account_id) is None

    async def test_pagination(self, db) -> None:
        for i in range(12):
            await db.add_account(f"acc{i}", AccountKind.BOT_API, secret="t")
        assert await db.count_accounts() == 12
        assert len(await db.list_accounts(limit=5, offset=0)) == 5
        assert len(await db.list_accounts(limit=5, offset=10)) == 2


class TestLinkdoni:
    async def test_duplicates_rejected(self, db) -> None:
        url = "https://eitaa.com/sample"
        assert await db.add_linkdoni(url) is not None
        assert await db.add_linkdoni(url) is None      # تکراری ذخیره نمی‌شود
        assert await db.count_linkdoni() == 1

    async def test_selection(self, db) -> None:
        first = await db.add_linkdoni("https://eitaa.com/a")
        await db.add_linkdoni("https://eitaa.com/b")
        await db.toggle_linkdoni(first)
        assert await db.count_linkdoni(only_selected=True) == 1
        await db.set_all_linkdoni_selected(True)
        assert await db.count_linkdoni(only_selected=True) == 2
        await db.set_all_linkdoni_selected(False)
        assert await db.count_linkdoni(only_selected=True) == 0

    async def test_seed_is_idempotent(self, db) -> None:
        urls = ["https://eitaa.com/x", "https://eitaa.com/y"]
        assert await db.seed_default_linkdoni(urls) == 2
        assert await db.seed_default_linkdoni(urls) == 0


class TestJobs:
    async def test_lifecycle_and_counters(self, db) -> None:
        job_id = await db.create_job(JobType.JOINER, None, {"k": "v"})
        job = await db.get_job(job_id)
        assert job.status is JobStatus.PENDING
        assert job.params == {"k": "v"}

        await db.set_job_total(job_id, 10)
        await db.set_job_status(job_id, JobStatus.RUNNING)
        await db.bump_job_counters(job_id, processed=4, success=3, failed=1)

        job = await db.get_job(job_id)
        assert (job.processed, job.success, job.failed) == (4, 3, 1)
        assert job.percent == 40
        assert job.started_at is not None

        await db.set_job_status(job_id, JobStatus.COMPLETED)
        job = await db.get_job(job_id)
        assert job.status.is_final and job.finished_at is not None

    async def test_items_and_retry(self, db) -> None:
        job_id = await db.create_job(JobType.JOINER, None)
        await db.add_job_items(job_id, [("a", "A"), ("b", "B"), ("c", "C")])
        assert len(await db.pending_items(job_id)) == 3

        await db.set_item_status(job_id, "a", ItemStatus.SUCCESS)
        await db.set_item_status(job_id, "b", ItemStatus.FAILED, "خطا")
        assert len(await db.pending_items(job_id)) == 1

        assert await db.reset_failed_items(job_id) == 1   # Retry Failed
        assert len(await db.pending_items(job_id)) == 2

    async def test_running_jobs_for_recovery(self, db) -> None:
        job_id = await db.create_job(JobType.SENDER, None)
        await db.set_job_status(job_id, JobStatus.RUNNING)
        assert job_id in [j.id for j in await db.running_jobs()]


class TestLinksAndLogs:
    async def test_link_dedup_at_db_level(self, db) -> None:
        job_id = await db.create_job(JobType.EXTRACT, None)
        rows = [
            ("https://eitaa.com/g1", LinkKind.GROUP, "src"),
            ("https://eitaa.com/g1", LinkKind.GROUP, "src"),  # تکراری
            ("https://eitaa.com/g2", LinkKind.UNKNOWN, "src"),
        ]
        assert await db.add_links(job_id, rows) == 2
        assert await db.count_links(job_id) == 2
        assert await db.count_links(job_id, kind=LinkKind.GROUP) == 1

    async def test_logs_paginated(self, db) -> None:
        job_id = await db.create_job(JobType.JOINER, None)
        for i in range(25):
            await db.add_log(job_id, LogLevel.INFO, f"پیام {i}")
        assert await db.count_logs(job_id) == 25
        assert len(await db.list_logs(job_id, limit=10, offset=0)) == 10
        assert len(await db.list_logs(job_id, limit=10, offset=20)) == 5

    async def test_audit_log(self, db) -> None:
        await db.audit(42, "login", "detail")
        entries = await db.list_audit(10, 0)
        assert entries[0]["user_id"] == 42


class TestDrafts:
    async def test_draft_roundtrip(self, db) -> None:
        await db.save_draft(7, "متن اول", "HTML")
        assert (await db.get_draft(7))["text"] == "متن اول"
        await db.save_draft(7, "متن دوم", "HTML")
        assert (await db.get_draft(7))["text"] == "متن دوم"   # upsert
        await db.clear_draft(7)
        assert await db.get_draft(7) is None


class TestSqlInjection:
    async def test_malicious_input_is_parameterized(self, db) -> None:
        evil = "x'; DROP TABLE accounts; --"
        await db.add_account(evil, AccountKind.BOT_API, secret="t")
        assert await db.count_accounts() == 1      # جدول سالم است
        await db.add_linkdoni("https://eitaa.com/" + "a")
        assert await db.count_linkdoni() == 1
