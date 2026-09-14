#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  نصب و اجرای خودکار پنل مدیریت ایتا
#  استفاده:  bash setup.sh
#  یا بدون پرسش:  bash setup.sh "<TOKEN>" "<ADMIN_ID>"
# ─────────────────────────────────────────────────────────────
set -u

RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; CYN=$'\033[36m'; OFF=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✅ %s%s\n' "$GRN" "$*" "$OFF"; }
warn() { printf '%s⚠️  %s%s\n' "$YLW" "$*" "$OFF"; }
die()  { printf '%s❌ %s%s\n' "$RED" "$*" "$OFF" >&2; exit 1; }

cd "$(dirname "$0")" || die "نمی‌توانم به پوشهٔ پروژه بروم."
[ -f run.py ] || die "فایل run.py پیدا نشد. آیا داخل پوشهٔ Not- هستید؟"

say ""
say "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${OFF}"
say "${CYN}  نصب و اجرای پنل مدیریت ایتا${OFF}"
say "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${OFF}"
say ""

# ── پیدا کردن پایتون ────────────────────────────────────────
PY=""
for c in python3 python python3.12 python3.11 python3.10; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
done
[ -n "$PY" ] || die "پایتون نصب نیست. بزنید:  pkg install python"
ok "پایتون: $("$PY" --version 2>&1)"

# ── گرفتن توکن و آیدی ───────────────────────────────────────
TOKEN="${1-}"
ADMIN="${2-}"

if [ -z "$TOKEN" ]; then
    say ""
    say "${CYN}توکن ربات را از @BotFather بگیرید و اینجا بچسبانید:${OFF}"
    printf '  BOT_TOKEN> '
    read -r TOKEN
fi
TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
[ -n "$TOKEN" ] || die "توکن خالی است."

case "$TOKEN" in
    *:*) : ;;
    *) die "قالب توکن درست نیست. باید شبیه این باشد:  123456789:AAF..." ;;
esac

if [ -z "$ADMIN" ]; then
    say ""
    say "${CYN}آیدی عددی خودتان (از ربات @userinfobot):${OFF}"
    printf '  ADMIN_IDS> '
    read -r ADMIN
fi
ADMIN="$(printf '%s' "$ADMIN" | tr -d '[:space:]')"
[ -n "$ADMIN" ] || die "آیدی ادمین خالی است. بدون آن هیچ‌کس به پنل راه ندارد."

case "$ADMIN" in
    *[!0-9,-]*) die "آیدی باید فقط عدد باشد (چند نفر با کاما جدا شوند)." ;;
esac

# نمایش ماسک‌شده برای اطمینان از درستی چسباندن
MASK="$(printf '%s' "$TOKEN" | cut -c1-8)...$(printf '%s' "$TOKEN" | tail -c 5)"
say ""
ok "توکن دریافت شد: $MASK"
ok "ادمین: $ADMIN"

# ── ساخت فایل .env ──────────────────────────────────────────
say ""
if [ -f .env ]; then
    cp .env ".env.backup.$(date +%s)"
    warn "فایل .env قبلی وجود داشت — نسخهٔ پشتیبان گرفته شد."
fi

[ -f .env.example ] || die ".env.example پیدا نشد."

# جای‌گذاری امن بدون sed (توکن کاراکترهای خاص دارد)
TOKEN="$TOKEN" ADMIN="$ADMIN" "$PY" - <<'PYEOF'
import os, pathlib
token = os.environ["TOKEN"]
admin = os.environ["ADMIN"]
src = pathlib.Path(".env.example").read_text(encoding="utf-8")
out = []
for line in src.splitlines():
    if line.startswith("BOT_TOKEN="):
        out.append(f"BOT_TOKEN={token}")
    elif line.startswith("ADMIN_IDS="):
        out.append(f"ADMIN_IDS={admin}")
    else:
        out.append(line)
pathlib.Path(".env").write_text("\n".join(out) + "\n", encoding="utf-8")
PYEOF

chmod 600 .env 2>/dev/null || true
ok "فایل .env ساخته و ذخیره شد (دسترسی ۶۰۰)."

# ── نصب کتابخانه‌ها ─────────────────────────────────────────
say ""
if "$PY" -c "import aiogram, aiosqlite, cryptography" >/dev/null 2>&1; then
    ok "کتابخانه‌ها از قبل نصب‌اند."
else
    warn "کتابخانه‌ها نصب نیستند. نصب شروع می‌شود..."
    say "   ${YLW}این مرحله روی گوشی ۱۰ تا ۳۰ دقیقه طول می‌کشد. صبور باشید.${OFF}"
    say ""

    command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

    if command -v rustc >/dev/null 2>&1; then
        CARGO_BUILD_TARGET="$(rustc -vV | sed -n 's|host: ||p')"
        export CARGO_BUILD_TARGET
    fi

    # بعضی توزیع‌ها (PEP 668) نصب سراسری را قفل می‌کنند
    PIPX=""
    if "$PY" -m pip install --help 2>/dev/null | grep -q "break-system-packages"; then
        if [ -f /usr/lib/python*/EXTERNALLY-MANAGED ] 2>/dev/null; then
            PIPX="--break-system-packages"
        fi
    fi

    # shellcheck disable=SC2086
    "$PY" -m pip install $PIPX --upgrade pip wheel setuptools 2>&1 | tail -2
    # shellcheck disable=SC2086
    if ! "$PY" -m pip install $PIPX -r requirements.txt; then
        say ""
        die "نصب کتابخانه‌ها شکست خورد.
   اگر خطا دربارهٔ Rust یا pydantic-core بود، اول بزنید:
       pkg install rust clang binutils make libffi openssl
   سپس دوباره:  bash setup.sh
   راه جایگزین در فایل docs/TERMUX.md آمده است."
    fi
    ok "کتابخانه‌ها نصب شدند."
fi

# ── اجرا ────────────────────────────────────────────────────
say ""
say "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${OFF}"
say "${GRN}  ربات در حال اجراست — برای توقف Ctrl+C${OFF}"
say "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${OFF}"
say ""

exec "$PY" run.py
