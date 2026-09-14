#!/usr/bin/env python3
"""
عیب‌یاب پنل — بررسی گام‌به‌گام اینکه چرا ربات جواب نمی‌دهد.

اجرا:  python doctor.py
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

GRN = "\033[32m"
RED = "\033[31m"
YLW = "\033[33m"
CYN = "\033[36m"
OFF = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GRN}✅ {msg}{OFF}")


def bad(msg: str, fix: str = "") -> None:
    print(f"{RED}❌ {msg}{OFF}")
    if fix:
        for line in fix.splitlines():
            print(f"   {CYN}{line}{OFF}")


def warn(msg: str) -> None:
    print(f"{YLW}⚠️  {msg}{OFF}")


def head(msg: str) -> None:
    print(f"\n{CYN}━━━ {msg} ━━━{OFF}")


async def main() -> int:  # noqa: C901 - خطی و خوانا
    problems = 0

    # ── ۱. فایل .env ────────────────────────────────────────
    head("۱. فایل پیکربندی")
    env = Path(".env")
    if not env.is_file():
        bad(".env وجود ندارد.", "cp .env.example .env  سپس آن را پر کنید")
        return 1
    ok(".env موجود است")

    from app.config import config

    # ── ۲. توکن و ادمین ─────────────────────────────────────
    head("۲. توکن و ادمین")
    errors = config.validate()
    if errors:
        for e in errors:
            bad(e)
        return 1
    ok(f"توکن ثبت شده (شناسهٔ ربات: {config.bot_token.split(':')[0]})")
    ok(f"ادمین‌ها: {sorted(config.admin_ids)}")

    if any(a in {11111111, 22222222} for a in config.admin_ids):
        bad(
            "ADMIN_IDS هنوز مقدار نمونه است!",
            "آیدی عددی خودتان را از @userinfobot بگیرید\n"
            "و در .env جایگزین کنید. تا آن موقع ربات به شما جواب نمی‌دهد.",
        )
        problems += 1

    # ── ۳. اتصال به تلگرام ──────────────────────────────────
    head("۳. اتصال به تلگرام")
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

    session = AiohttpSession(proxy=config.proxy_url) if config.proxy_url else None
    if config.proxy_url:
        ok(f"پراکسی تنظیم شده: {config.proxy_url}")
    else:
        warn("پراکسی تنظیم نشده (اگر تلگرام فیلتر است، لازم می‌شود)")

    bot = Bot(token=config.bot_token, session=session) if session else Bot(
        token=config.bot_token
    )
    me = None
    try:
        me = await bot.get_me()
        ok(f"اتصال برقرار شد: @{me.username}")
    except TelegramUnauthorizedError:
        bad(
            "توکن معتبر نیست یا باطل شده.",
            "از @BotFather توکن تازه بگیرید و در .env بگذارید.",
        )
        await bot.session.close()
        return 1
    except TelegramNetworkError as exc:
        bad(
            "به api.telegram.org نمی‌رسیم.",
            "تلگرام روی شبکهٔ شما مسدود است.\n"
            "فیلترشکن را روشن کنید، یا در .env بگذارید:\n"
            "  TELEGRAM_PROXY=socks5://127.0.0.1:10808",
        )
        print(f"   جزئیات: {str(exc)[:120]}")
        await bot.session.close()
        return 1

    # ── ۴. وب‌هوک (علت رایج بی‌جواب ماندن) ──────────────────
    head("۴. وب‌هوک")
    try:
        info = await bot.get_webhook_info()
        if info.url:
            bad(
                f"وب‌هوک فعال است: {info.url}",
                "تا وب‌هوک فعال باشد، polling هیچ پیامی نمی‌گیرد.\n"
                "برای حذف آن این را اجرا کنید:\n"
                "  python doctor.py --fix-webhook",
            )
            problems += 1
        else:
            ok("وب‌هوک فعال نیست (درست است)")
        if info.pending_update_count:
            warn(f"{info.pending_update_count} آپدیت در صف مانده است")
    except Exception as exc:  # noqa: BLE001
        warn(f"بررسی وب‌هوک ناموفق: {str(exc)[:80]}")

    # ── ۵. نمونهٔ همزمان ────────────────────────────────────
    head("۵. اجرای همزمان")
    try:
        updates = await bot.get_updates(limit=100, timeout=0)
        ok(f"getUpdates کار می‌کند ({len(updates)} آپدیت در صف)")

        # مهم‌ترین بررسی: آیا فرستندهٔ واقعی پیام‌ها جزو ادمین‌هاست؟
        senders: dict[int, str] = {}
        for upd in updates:
            src = upd.message or upd.callback_query
            frm = getattr(src, "from_user", None)
            if frm:
                senders[frm.id] = frm.username or frm.full_name or "?"

        if senders:
            print()
            for uid, uname in senders.items():
                if uid in config.admin_ids:
                    ok(f"پیام از {uid} (@{uname}) — این آیدی ادمین است ✔")
                else:
                    bad(
                        f"پیام از {uid} (@{uname}) — این آیدی ادمین نیست!",
                        "ربات به این آیدی فقط «دسترسی مجاز نیست» می‌دهد.\n"
                        "این خط را در .env بگذارید:\n"
                        f"  ADMIN_IDS={uid}\n"
                        "سپس ربات را دوباره اجرا کنید.",
                    )
                    problems += 1
        elif updates:
            warn("آپدیت‌ها فرستندهٔ قابل تشخیص ندارند")
        else:
            warn(
                "هیچ پیامی در صف نیست. اگر ربات جواب نمی‌دهد، اول در تلگرام\n"
                "   به @"
                + (me.username or "?")
                + " یک /start بفرستید، بعد دوباره این ابزار را اجرا کنید."
            )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "terminated by other getUpdates" in msg or "Conflict" in msg:
            bad(
                "یک نسخهٔ دیگر از ربات همزمان در حال اجراست!",
                "این باعث می‌شود پیام‌ها به نسخهٔ دیگر برود.\n"
                "همه را ببندید:\n"
                "  pkill -f 'python run.py'\n"
                "سپس دوباره اجرا کنید.",
            )
            problems += 1
        else:
            warn(f"getUpdates: {msg[:100]}")

    await bot.session.close()

    # ── ۵.۵ آیا خود ربات اصلاً در حال اجراست؟ ───────────────
    head("۶. اجرا بودن ربات")
    try:
        out = subprocess.run(
            ["pgrep", "-af", "run.py"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        out = ""
    mine = [ln for ln in out.splitlines() if "doctor" not in ln]
    if mine:
        ok(f"ربات در حال اجراست ({len(mine)} نمونه)")
        for ln in mine:
            print(f"   {ln}")
        if len(mine) > 1:
            bad(
                "بیش از یک نمونه اجراست — با هم تداخل دارند!",
                "همه را ببندید:  pkill -f 'python run.py'",
            )
            problems += 1
    else:
        bad(
            "ربات در حال اجرا نیست!",
            "هیچ پردازش run.py پیدا نشد. یعنی چیزی پیام‌ها را نمی‌خواند.\n"
            "در یک پنجرهٔ جدا اجرا کنید و خروجی را ببینید:\n"
            "  cd ~/Not- && python run.py\n"
            "اگر بلافاصله بسته شد، متن خطا را بفرستید.",
        )
        problems += 1

    # ── ۶.۵ آخرین خطاهای ثبت‌شده ────────────────────────────
    head("۷. آخرین خطاها در لاگ")
    err_log = Path("logs/error.log")
    if err_log.exists() and err_log.stat().st_size:
        lines = err_log.read_text(encoding="utf-8", errors="replace").splitlines()
        warn(f"{err_log} — {len(lines)} خط. ۱۵ خط آخر:")
        for ln in lines[-15:]:
            print(f"   {ln[:160]}")
    else:
        ok("خطای ثبت‌شده‌ای وجود ندارد")

    # ── ۸. سرویس پل ─────────────────────────────────────────
    head("۸. سرویس پل ایتا (اختیاری)")
    if not config.bridge_ready:
        warn("EITAA_BRIDGE_URL تنظیم نشده — «ورود با شماره» غیرفعال است")
    else:
        from app.eitaa.bridge_backend import BridgeClient

        client = BridgeClient(config.bridge_url, timeout=5)
        if await client.ping():
            ok(f"سرویس پل پاسخ می‌دهد: {config.bridge_url}")
        else:
            bad(
                f"سرویس پل پاسخ نمی‌دهد: {config.bridge_url}",
                "اجرا در پس‌زمینه:  bash bridge-setup.sh --bg\n"
                "دیدن خطا:         bash bridge-setup.sh --log",
            )
            problems += 1
        await client.close()

    # ── نتیجه ───────────────────────────────────────────────
    print()
    if problems:
        print(f"{RED}━━━ {problems} مشکل پیدا شد — موارد بالا را برطرف کنید ━━━{OFF}\n")
        return 1

    print(f"{GRN}━━━ همه‌چیز سالم است ━━━{OFF}")
    print(f"\nربات @{me.username} آمادهٔ کار است.")
    print("اگر باز هم جواب نمی‌دهد:")
    print("  ۱) مطمئن شوید به ربات درست پیام می‌دهید (همین یوزرنیم بالا)")
    print("  ۲) در تلگرام دستور /start را بفرستید")
    print(f"  ۳) با همان حسابی پیام دهید که آیدی‌اش {sorted(config.admin_ids)} است")
    print("  ۴) لاگ را ببینید:  tail -f logs/bot.log\n")
    return 0


async def fix_webhook() -> int:
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession

    from app.config import config

    session = AiohttpSession(proxy=config.proxy_url) if config.proxy_url else None
    bot = Bot(token=config.bot_token, session=session) if session else Bot(
        token=config.bot_token
    )
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        ok("وب‌هوک حذف شد و صف پاک شد. حالا python run.py را اجرا کنید.")
        return 0
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        if "--fix-webhook" in sys.argv:
            raise SystemExit(asyncio.run(fix_webhook()))
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
