"""
لایهٔ دیتابیس — SQLite غیرهمزمان.

نکات امنیتی:
  • تمام کوئری‌ها پارامتری‌اند (SQL Injection Protection).
  • اسرار (توکن/نشست) پیش از ذخیره با Fernet رمز می‌شوند و هرگز خام برنمی‌گردند.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import aiosqlite

from app.db.models import (
    Account,
    AccountKind,
    AccountStatus,
    ExtractedLink,
    ItemStatus,
    Job,
    JobItem,
    JobLog,
    JobStatus,
    JobType,
    Linkdoni,
    LinkKind,
    LogLevel,
)
from app.security import secret_box

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,          -- telegram user id
    username    TEXT    DEFAULT '',
    is_admin    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    last_seen   TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    secret_enc    TEXT    NOT NULL DEFAULT '',  -- رمزشده
    session_name  TEXT    NOT NULL DEFAULT '',
    identity      TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL DEFAULT 'UNKNOWN',
    status_note   TEXT    NOT NULL DEFAULT '',
    last_checked  TEXT,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS linkdoni (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT    NOT NULL UNIQUE,       -- تکراری ذخیره نمی‌شود
    title       TEXT    NOT NULL DEFAULT '',
    selected    INTEGER NOT NULL DEFAULT 0,
    is_default  INTEGER NOT NULL DEFAULT 0,
    last_status TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT    NOT NULL,
    account_id   INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    status       TEXT    NOT NULL,
    total        INTEGER NOT NULL DEFAULT 0,
    processed    INTEGER NOT NULL DEFAULT 0,
    success      INTEGER NOT NULL DEFAULT 0,
    already      INTEGER NOT NULL DEFAULT 0,
    failed       INTEGER NOT NULL DEFAULT 0,
    params       TEXT    NOT NULL DEFAULT '{}',
    error        TEXT    NOT NULL DEFAULT '',
    recoverable  INTEGER NOT NULL DEFAULT 0,
    started_at   TEXT,
    finished_at  TEXT,
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS job_items (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id  INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ref     TEXT    NOT NULL,
    title   TEXT    NOT NULL DEFAULT '',
    status  TEXT    NOT NULL DEFAULT 'PENDING',
    reason  TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_items_job ON job_items(job_id, status);

CREATE TABLE IF NOT EXISTS job_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    level       TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_job ON job_logs(job_id, id);

CREATE TABLE IF NOT EXISTS extracted_links (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id  INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    url     TEXT    NOT NULL,
    kind    TEXT    NOT NULL DEFAULT 'UNKNOWN',
    source  TEXT    NOT NULL DEFAULT '',
    UNIQUE(job_id, url)                         -- Deduplication در سطح دیتابیس
);

CREATE TABLE IF NOT EXISTS drafts (
    user_id     INTEGER PRIMARY KEY,
    text        TEXT    NOT NULL DEFAULT '',
    parse_mode  TEXT    NOT NULL DEFAULT 'HTML',
    media_path  TEXT    NOT NULL DEFAULT '',
    media_type  TEXT    NOT NULL DEFAULT '',
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    action      TEXT    NOT NULL,
    detail      TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id, id);

CREATE TABLE IF NOT EXISTS exports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    fmt         TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    # ───────────────────────── lifecycle ─────────────────────────
    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        log.info("دیتابیس آماده است: %s", self.path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("دیتابیس متصل نیست. ابتدا connect() را صدا بزنید.")
        return self._conn

    async def _commit(self) -> None:
        await self.conn.commit()

    # ═════════════════════════ users ═════════════════════════
    async def upsert_user(self, user_id: int, username: str, is_admin: bool) -> None:
        await self.conn.execute(
            """INSERT INTO users(id, username, is_admin, created_at, last_seen)
               VALUES(?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   username=excluded.username,
                   is_admin=excluded.is_admin,
                   last_seen=excluded.last_seen""",
            (user_id, username or "", int(is_admin), _now(), _now()),
        )
        await self._commit()

    # ═════════════════════════ audit ═════════════════════════
    async def audit(self, user_id: int, action: str, detail: str = "") -> None:
        await self.conn.execute(
            "INSERT INTO audit_logs(user_id, action, detail, created_at) VALUES(?,?,?,?)",
            (user_id, action[:80], detail[:400], _now()),
        )
        await self._commit()

    async def list_audit(self, limit: int, offset: int) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def count_audit(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) c FROM audit_logs")
        return int((await cur.fetchone())["c"])

    # ═════════════════════════ accounts ═════════════════════════
    async def add_account(
        self, label: str, kind: AccountKind, secret: str = "", session_name: str = ""
    ) -> int:
        cur = await self.conn.execute(
            """INSERT INTO accounts(label, kind, secret_enc, session_name, created_at)
               VALUES(?,?,?,?,?)""",
            (label[:60], kind.value, secret_box.encrypt(secret), session_name[:80], _now()),
        )
        await self._commit()
        return int(cur.lastrowid or 0)

    @staticmethod
    def _row_to_account(row: aiosqlite.Row) -> Account:
        return Account(
            id=row["id"],
            label=row["label"],
            kind=AccountKind(row["kind"]),
            status=AccountStatus(row["status"]),
            identity=row["identity"],
            status_note=row["status_note"],
            last_checked=row["last_checked"],
            created_at=row["created_at"],
        )

    async def list_accounts(
        self, limit: int | None = None, offset: int = 0, kind: AccountKind | None = None
    ) -> list[Account]:
        sql = "SELECT * FROM accounts"
        args: list[Any] = []
        if kind is not None:
            sql += " WHERE kind = ?"
            args.append(kind.value)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            args += [limit, offset]
        cur = await self.conn.execute(sql, args)
        return [self._row_to_account(r) for r in await cur.fetchall()]

    async def count_accounts(self, kind: AccountKind | None = None) -> int:
        if kind is None:
            cur = await self.conn.execute("SELECT COUNT(*) c FROM accounts")
        else:
            cur = await self.conn.execute(
                "SELECT COUNT(*) c FROM accounts WHERE kind=?", (kind.value,)
            )
        return int((await cur.fetchone())["c"])

    async def get_account(self, account_id: int) -> Account | None:
        cur = await self.conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,))
        row = await cur.fetchone()
        return self._row_to_account(row) if row else None

    async def get_account_secret(self, account_id: int) -> str:
        """تنها نقطهٔ خروج راز — فقط برای لایهٔ سرویس، هرگز برای UI."""
        cur = await self.conn.execute("SELECT secret_enc FROM accounts WHERE id=?", (account_id,))
        row = await cur.fetchone()
        return secret_box.decrypt(row["secret_enc"]) if row else ""

    async def get_account_session_name(self, account_id: int) -> str:
        cur = await self.conn.execute("SELECT session_name FROM accounts WHERE id=?", (account_id,))
        row = await cur.fetchone()
        return row["session_name"] if row else ""

    async def update_account_status(
        self, account_id: int, status: AccountStatus, note: str = "", identity: str = ""
    ) -> None:
        await self.conn.execute(
            """UPDATE accounts
               SET status=?, status_note=?, last_checked=?,
                   identity = CASE WHEN ?<>'' THEN ? ELSE identity END
               WHERE id=?""",
            (status.value, note[:200], _now(), identity, identity, account_id),
        )
        await self._commit()

    async def delete_account(self, account_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        await self._commit()
        return cur.rowcount > 0

    # ═════════════════════════ linkdoni ═════════════════════════
    async def add_linkdoni(self, url: str, title: str = "", is_default: bool = False) -> int | None:
        """در صورت تکراری بودن None برمی‌گرداند (بخش ۵)."""
        try:
            cur = await self.conn.execute(
                "INSERT INTO linkdoni(url, title, is_default, created_at) VALUES(?,?,?,?)",
                (url, title[:80], int(is_default), _now()),
            )
            await self._commit()
            return int(cur.lastrowid or 0)
        except aiosqlite.IntegrityError:
            return None

    @staticmethod
    def _row_to_linkdoni(row: aiosqlite.Row) -> Linkdoni:
        return Linkdoni(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            selected=bool(row["selected"]),
            is_default=bool(row["is_default"]),
            last_status=row["last_status"],
            created_at=row["created_at"],
        )

    async def list_linkdoni(
        self, limit: int | None = None, offset: int = 0, only_selected: bool = False
    ) -> list[Linkdoni]:
        sql = "SELECT * FROM linkdoni"
        args: list[Any] = []
        if only_selected:
            sql += " WHERE selected=1"
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            args += [limit, offset]
        cur = await self.conn.execute(sql, args)
        return [self._row_to_linkdoni(r) for r in await cur.fetchall()]

    async def count_linkdoni(self, only_selected: bool = False) -> int:
        sql = "SELECT COUNT(*) c FROM linkdoni" + (" WHERE selected=1" if only_selected else "")
        cur = await self.conn.execute(sql)
        return int((await cur.fetchone())["c"])

    async def get_linkdoni(self, item_id: int) -> Linkdoni | None:
        cur = await self.conn.execute("SELECT * FROM linkdoni WHERE id=?", (item_id,))
        row = await cur.fetchone()
        return self._row_to_linkdoni(row) if row else None

    async def toggle_linkdoni(self, item_id: int) -> None:
        await self.conn.execute(
            "UPDATE linkdoni SET selected = 1 - selected WHERE id=?", (item_id,)
        )
        await self._commit()

    async def set_all_linkdoni_selected(self, selected: bool) -> None:
        await self.conn.execute("UPDATE linkdoni SET selected=?", (int(selected),))
        await self._commit()

    async def set_linkdoni_status(self, item_id: int, status: str) -> None:
        await self.conn.execute(
            "UPDATE linkdoni SET last_status=? WHERE id=?", (status[:40], item_id)
        )
        await self._commit()

    async def delete_linkdoni(self, item_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM linkdoni WHERE id=?", (item_id,))
        await self._commit()
        return cur.rowcount > 0

    async def seed_default_linkdoni(self, urls: Iterable[str]) -> int:
        added = 0
        for url in urls:
            if await self.add_linkdoni(url, title="پیش‌فرض", is_default=True) is not None:
                added += 1
        return added

    # ═════════════════════════ jobs ═════════════════════════
    async def create_job(
        self, job_type: JobType, account_id: int | None, params: dict[str, Any] | None = None
    ) -> int:
        cur = await self.conn.execute(
            """INSERT INTO jobs(type, account_id, status, params, created_at)
               VALUES(?,?,?,?,?)""",
            (
                job_type.value,
                account_id,
                JobStatus.PENDING.value,
                json.dumps(params or {}, ensure_ascii=False),
                _now(),
            ),
        )
        await self._commit()
        return int(cur.lastrowid or 0)

    @staticmethod
    def _row_to_job(row: aiosqlite.Row) -> Job:
        try:
            params = json.loads(row["params"])
        except (json.JSONDecodeError, TypeError):
            params = {}
        return Job(
            id=row["id"],
            type=JobType(row["type"]),
            account_id=row["account_id"],
            status=JobStatus(row["status"]),
            total=row["total"],
            processed=row["processed"],
            success=row["success"],
            already=row["already"],
            failed=row["failed"],
            params=params,
            error=row["error"],
            recoverable=bool(row["recoverable"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            created_at=row["created_at"],
        )

    async def get_job(self, job_id: int) -> Job | None:
        cur = await self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        row = await cur.fetchone()
        return self._row_to_job(row) if row else None

    async def list_jobs(self, limit: int, offset: int = 0) -> list[Job]:
        cur = await self.conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        )
        return [self._row_to_job(r) for r in await cur.fetchall()]

    async def count_jobs(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) c FROM jobs")
        return int((await cur.fetchone())["c"])

    async def set_job_status(
        self,
        job_id: int,
        status: JobStatus,
        error: str = "",
        recoverable: bool | None = None,
    ) -> None:
        fields = ["status=?"]
        args: list[Any] = [status.value]
        if status is JobStatus.RUNNING:
            fields.append("started_at=COALESCE(started_at, ?)")
            args.append(_now())
        if status.is_final:
            fields.append("finished_at=?")
            args.append(_now())
        if error:
            fields.append("error=?")
            args.append(error[:400])
        if recoverable is not None:
            fields.append("recoverable=?")
            args.append(int(recoverable))
        args.append(job_id)
        await self.conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", args)
        await self._commit()

    async def set_job_total(self, job_id: int, total: int) -> None:
        await self.conn.execute("UPDATE jobs SET total=? WHERE id=?", (total, job_id))
        await self._commit()

    async def bump_job_counters(
        self, job_id: int, *, processed: int = 0, success: int = 0, already: int = 0, failed: int = 0
    ) -> None:
        await self.conn.execute(
            """UPDATE jobs SET processed=processed+?, success=success+?,
                               already=already+?, failed=failed+? WHERE id=?""",
            (processed, success, already, failed, job_id),
        )
        await self._commit()

    async def running_jobs(self) -> list[Job]:
        cur = await self.conn.execute(
            "SELECT * FROM jobs WHERE status IN (?,?,?) ORDER BY id",
            (JobStatus.RUNNING.value, JobStatus.PENDING.value, JobStatus.STOPPING.value),
        )
        return [self._row_to_job(r) for r in await cur.fetchall()]

    # ═════════════════════════ job items ═════════════════════════
    async def add_job_items(self, job_id: int, items: Sequence[tuple[str, str]]) -> None:
        await self.conn.executemany(
            "INSERT INTO job_items(job_id, ref, title) VALUES(?,?,?)",
            [(job_id, ref[:300], title[:120]) for ref, title in items],
        )
        await self._commit()

    async def set_item_status(
        self, job_id: int, ref: str, status: ItemStatus, reason: str = ""
    ) -> None:
        await self.conn.execute(
            "UPDATE job_items SET status=?, reason=? WHERE job_id=? AND ref=?",
            (status.value, reason[:200], job_id, ref),
        )
        await self._commit()

    async def list_job_items(
        self,
        job_id: int,
        status: ItemStatus | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[JobItem]:
        sql = "SELECT * FROM job_items WHERE job_id=?"
        args: list[Any] = [job_id]
        if status is not None:
            sql += " AND status=?"
            args.append(status.value)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            args += [limit, offset]
        cur = await self.conn.execute(sql, args)
        return [
            JobItem(
                id=r["id"],
                job_id=r["job_id"],
                ref=r["ref"],
                title=r["title"],
                status=ItemStatus(r["status"]),
                reason=r["reason"],
            )
            for r in await cur.fetchall()
        ]

    async def pending_items(self, job_id: int) -> list[JobItem]:
        return await self.list_job_items(job_id, status=ItemStatus.PENDING)

    async def reset_failed_items(self, job_id: int) -> int:
        """برای «Retry Failed» — آیتم‌های ناموفق به PENDING برمی‌گردند."""
        cur = await self.conn.execute(
            "UPDATE job_items SET status=?, reason='' WHERE job_id=? AND status=?",
            (ItemStatus.PENDING.value, job_id, ItemStatus.FAILED.value),
        )
        await self._commit()
        return cur.rowcount

    # ═════════════════════════ logs ═════════════════════════
    async def add_log(self, job_id: int, level: LogLevel, message: str) -> None:
        await self.conn.execute(
            "INSERT INTO job_logs(job_id, level, message, created_at) VALUES(?,?,?,?)",
            (job_id, level.value, message[:500], _now()),
        )
        await self._commit()

    async def list_logs(self, job_id: int, limit: int, offset: int = 0) -> list[JobLog]:
        cur = await self.conn.execute(
            "SELECT * FROM job_logs WHERE job_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (job_id, limit, offset),
        )
        return [
            JobLog(
                id=r["id"],
                job_id=r["job_id"],
                level=LogLevel(r["level"]),
                message=r["message"],
                created_at=r["created_at"],
            )
            for r in await cur.fetchall()
        ]

    async def count_logs(self, job_id: int) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) c FROM job_logs WHERE job_id=?", (job_id,))
        return int((await cur.fetchone())["c"])

    # ═════════════════════ extracted links ═════════════════════
    async def add_links(self, job_id: int, links: Sequence[tuple[str, LinkKind, str]]) -> int:
        """درج با Deduplication (UNIQUE). تعداد واقعاً درج‌شده را برمی‌گرداند."""
        added = 0
        for url, kind, source in links:
            try:
                await self.conn.execute(
                    "INSERT INTO extracted_links(job_id, url, kind, source) VALUES(?,?,?,?)",
                    (job_id, url, kind.value, source[:120]),
                )
                added += 1
            except aiosqlite.IntegrityError:
                continue
        await self._commit()
        return added

    async def list_links(
        self, job_id: int, kind: LinkKind | None = None, limit: int | None = None, offset: int = 0
    ) -> list[ExtractedLink]:
        sql = "SELECT * FROM extracted_links WHERE job_id=?"
        args: list[Any] = [job_id]
        if kind is not None:
            sql += " AND kind=?"
            args.append(kind.value)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            args += [limit, offset]
        cur = await self.conn.execute(sql, args)
        return [
            ExtractedLink(
                id=r["id"],
                job_id=r["job_id"],
                url=r["url"],
                kind=LinkKind(r["kind"]),
                source=r["source"],
            )
            for r in await cur.fetchall()
        ]

    async def count_links(self, job_id: int, kind: LinkKind | None = None) -> int:
        if kind is None:
            cur = await self.conn.execute(
                "SELECT COUNT(*) c FROM extracted_links WHERE job_id=?", (job_id,)
            )
        else:
            cur = await self.conn.execute(
                "SELECT COUNT(*) c FROM extracted_links WHERE job_id=? AND kind=?",
                (job_id, kind.value),
            )
        return int((await cur.fetchone())["c"])

    # ═════════════════════════ drafts ═════════════════════════
    async def save_draft(
        self,
        user_id: int,
        text: str,
        parse_mode: str = "HTML",
        media_path: str = "",
        media_type: str = "",
    ) -> None:
        await self.conn.execute(
            """INSERT INTO drafts(user_id, text, parse_mode, media_path, media_type, updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 text=excluded.text, parse_mode=excluded.parse_mode,
                 media_path=excluded.media_path, media_type=excluded.media_type,
                 updated_at=excluded.updated_at""",
            (user_id, text, parse_mode, media_path, media_type, _now()),
        )
        await self._commit()

    async def get_draft(self, user_id: int) -> dict[str, Any] | None:
        cur = await self.conn.execute("SELECT * FROM drafts WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def clear_draft(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM drafts WHERE user_id=?", (user_id,))
        await self._commit()

    # ═════════════════════════ settings ═════════════════════════
    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            """INSERT INTO settings(key, value) VALUES(?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value),
        )
        await self._commit()

    async def get_setting(self, key: str, default: str = "") -> str:
        cur = await self.conn.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    # ═════════════════════════ exports ═════════════════════════
    async def record_export(self, job_id: int | None, fmt: str, path: str) -> None:
        await self.conn.execute(
            "INSERT INTO exports(job_id, fmt, path, created_at) VALUES(?,?,?,?)",
            (job_id, fmt, path, _now()),
        )
        await self._commit()
