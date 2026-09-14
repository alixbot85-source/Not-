#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  راه‌اندازی سرویس پل ایتا (EitaaBun) روی Node.js
#
#  چرا Node و نه Bun؟
#      Bun برای glibc ساخته شده و اندروید از bionic استفاده می‌کند،
#      بنابراین Bun روی ترموکس اجرا نمی‌شود. هستهٔ MTProto این پروژه
#      هیچ API اختصاصی Bun ندارد؛ فقط چند فراخوانی Bun.write/Bun.file
#      در لایهٔ ذخیره‌سازی هست که با یک shim کوچک جایگزین می‌شود.
#
#  استفاده:  bash bridge-setup.sh
# ─────────────────────────────────────────────────────────────
set -u

RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; CYN=$'\033[36m'; OFF=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✅ %s%s\n' "$GRN" "$*" "$OFF"; }
warn() { printf '%s⚠️  %s%s\n' "$YLW" "$*" "$OFF"; }
die()  { printf '%s❌ %s%s\n' "$RED" "$*" "$OFF" >&2; exit 1; }

BRIDGE_DIR="${BRIDGE_DIR:-$HOME/EitaaBun}"
PORT="${PORT:-1234}"
LOG_FILE="$BRIDGE_DIR/bridge.log"
PID_FILE="$BRIDGE_DIR/bridge.pid"
MODE="run"

case "${1:-}" in
    --bg|-b)      MODE="bg" ;;
    --stop|-s)    MODE="stop" ;;
    --status|-st) MODE="status" ;;
    --log|-l)     MODE="log" ;;
    --help|-h)
        cat <<'USAGE'
راه‌اندازی سرویس پل ایتا

  bash bridge-setup.sh            اجرا در همین پنجره (پنجره باید باز بماند)
  bash bridge-setup.sh --bg       اجرا در پس‌زمینه (پنجره را می‌توانید ببندید)
  bash bridge-setup.sh --status   آیا در حال اجراست؟
  bash bridge-setup.sh --log      دیدن لاگ زنده
  bash bridge-setup.sh --stop     توقف سرویس
USAGE
        exit 0 ;;
esac

is_up() {
    [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null
}

# آیا پورت توسط پردازهٔ دیگری گرفته شده؟ (حتی اگر PID فایل نداشته باشیم)
port_busy() {
    if command -v curl >/dev/null 2>&1; then
        curl -s -m 3 "http://127.0.0.1:$PORT/" >/dev/null 2>&1 && return 0
    fi
    return 1
}

# کشتن کل گروه پردازه: npx یک فرزند node می‌سازد که پورت را نگه می‌دارد
kill_tree() {
    local pid="$1"
    [ -n "$pid" ] || return 0
    kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    for _ in 1 2 3 4 5; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 1
    done
    kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
    return 0
}

case "$MODE" in
    status)
        if is_up; then
            ok "سرویس پل در حال اجراست (PID $(cat "$PID_FILE"))"
            command -v curl >/dev/null 2>&1 && \
                curl -s -m 3 "http://127.0.0.1:$PORT/" >/dev/null 2>&1 && \
                ok "پورت $PORT پاسخ می‌دهد."
            exit 0
        fi
        if port_busy; then
            warn "پورت $PORT توسط یک پردازهٔ رهاشده اشغال است."
            say "پاک‌سازی:  bash bridge-setup.sh --stop"
            exit 1
        fi
        warn "سرویس پل در حال اجرا نیست."
        say "اجرا:  bash bridge-setup.sh --bg"
        exit 1 ;;
    stop)
        stopped=0
        if [ -f "$PID_FILE" ]; then
            kill_tree "$(cat "$PID_FILE" 2>/dev/null)"
            rm -f "$PID_FILE"
            stopped=1
        fi
        # پردازه‌های رهاشدهٔ همین پوشه را هم جمع کن
        if command -v pkill >/dev/null 2>&1; then
            pkill -f "tsx server.ts" 2>/dev/null && stopped=1
        fi
        sleep 1
        if port_busy; then
            warn "پورت $PORT هنوز اشغال است. پردازه‌های node را دستی ببندید:"
            say "  pkill -9 -f 'tsx server.ts'"
            exit 1
        fi
        [ "$stopped" = 1 ] && ok "سرویس پل متوقف شد." || warn "سرویس پل در حال اجرا نبود."
        exit 0 ;;
    log)
        [ -f "$LOG_FILE" ] || die "لاگی وجود ندارد: $LOG_FILE"
        exec tail -f "$LOG_FILE" ;;
esac

if is_up; then
    ok "سرویس پل از قبل در حال اجراست (PID $(cat "$PID_FILE"))."
    say "توقف:  bash bridge-setup.sh --stop"
    exit 0
fi
if port_busy; then
    warn "پورت $PORT از قبل اشغال است (پردازهٔ رهاشده از اجرای قبلی)."
    say "اول پاک‌سازی کنید:  bash bridge-setup.sh --stop"
    exit 1
fi

say ""
say "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${OFF}"
say "${CYN}  سرویس پل ایتا — ورود با شمارهٔ تلفن${OFF}"
say "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${OFF}"
say ""

# ── Node ────────────────────────────────────────────────────
if ! command -v node >/dev/null 2>&1; then
    warn "Node.js نصب نیست. در حال نصب..."
    if command -v pkg >/dev/null 2>&1; then
        pkg install -y nodejs || die "نصب Node.js ناموفق بود."
    elif command -v apt >/dev/null 2>&1; then
        sudo apt install -y nodejs npm || die "نصب Node.js ناموفق بود."
    else
        die "Node.js را دستی نصب کنید: https://nodejs.org"
    fi
fi
ok "Node.js: $(node --version)"

# ── گرفتن سورس ──────────────────────────────────────────────
if [ ! -d "$BRIDGE_DIR/.git" ]; then
    say ""
    warn "در حال دریافت EitaaBun..."
    command -v git >/dev/null 2>&1 || die "git نصب نیست:  pkg install git"
    git clone --depth 1 https://github.com/ghaemifard/EitaaBun "$BRIDGE_DIR" \
        || die "دریافت سورس ناموفق بود."
fi
cd "$BRIDGE_DIR" || die "ورود به $BRIDGE_DIR ناموفق بود."
ok "سورس: $BRIDGE_DIR"

# ── shim سازگاری Bun → Node ─────────────────────────────────
cat > bun-shim.ts <<'SHIM'
// جایگزین حداقلی APIهای Bun با معادل Node — بدون تغییر منطق MTProto
import * as fs from 'fs';
import * as path from 'path';

const g: any = globalThis as any;
if (!g.Bun) {
  g.Bun = {
    write: async (p: string, data: any) => {
      fs.mkdirSync(path.dirname(p), { recursive: true });
      fs.writeFileSync(p, typeof data === 'string' ? data : Buffer.from(data));
      return 0;
    },
    file: (p: string) => ({
      text: async () => fs.promises.readFile(p, 'utf8'),
      json: async () => JSON.parse(await fs.promises.readFile(p, 'utf8')),
      exists: async () => fs.existsSync(p),
      arrayBuffer: async () => (await fs.promises.readFile(p)).buffer,
    }),
    sleep: (ms: number) => new Promise((r) => setTimeout(r, ms)),
  };
}
export const file = g.Bun.file;
export const write = g.Bun.write;
export const sleep = g.Bun.sleep;
SHIM

# ارجاع‌های "bun" را به shim برگردان (idempotent)
if grep -rlq 'from "bun"' src/ 2>/dev/null; then
    grep -rl 'from "bun"' src/ | while read -r f; do
        sed -i 's|from "bun"|from "../../bun-shim.js"|g' "$f"
    done
fi
if grep -rlq "from 'bun'" src/ 2>/dev/null; then
    grep -rl "from 'bun'" src/ | while read -r f; do
        sed -i "s|from 'bun'|from \"../../bun-shim.js\"|g" "$f"
    done
fi

# require() کنار top-level await در Node مجاز نیست
sed -i "s|private args = require('args-parser')(process.argv);|private args: any = {};|" \
    src/MainExpress.ts 2>/dev/null || true

# پورت قابل تنظیم
sed -i "s|const port = 1234;|const port = Number(process.env.PORT) \|\| 1234;|" \
    src/MainExpress.ts 2>/dev/null || true

cat > server.ts <<'ENTRY'
import "./bun-shim";
import Main from "./src/MainExpress";
Main.getMe().run();
ENTRY

ok "لایهٔ سازگاری Node آماده شد."

# ── وابستگی‌ها ──────────────────────────────────────────────
if [ ! -d node_modules ]; then
    say ""
    warn "در حال نصب وابستگی‌ها (چند دقیقه)..."
    npm install --silent --omit=optional express args-parser 2>&1 | tail -3
    npm install --silent -D tsx typescript @types/express @types/node 2>&1 | tail -3
fi
[ -x node_modules/.bin/tsx ] || die "نصب وابستگی‌ها کامل نشد. دوباره اجرا کنید."
ok "وابستگی‌ها نصب‌اند."

# ── اجرا ────────────────────────────────────────────────────
say ""
say "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${OFF}"
say "${GRN}  سرویس پل روی پورت $PORT${OFF}"
say "${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${OFF}"
say ""
say "در فایل .env پنل این خط باید باشد:"
say "${CYN}  EITAA_BRIDGE_URL=http://127.0.0.1:$PORT${OFF}"
say ""

command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

if [ "$MODE" = "bg" ]; then
    : > "$LOG_FILE"
    if command -v setsid >/dev/null 2>&1; then
        PORT="$PORT" setsid npx tsx server.ts >>"$LOG_FILE" 2>&1 &
    else
        PORT="$PORT" nohup npx tsx server.ts >>"$LOG_FILE" 2>&1 &
    fi
    echo $! > "$PID_FILE"
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        grep -q "Server is running" "$LOG_FILE" 2>/dev/null && break
        is_up || break
        sleep 1
    done
    if is_up && grep -q "Server is running" "$LOG_FILE" 2>/dev/null; then
        ok "سرویس پل در پس‌زمینه اجرا شد (PID $(cat "$PID_FILE"))."
        say ""
        say "این پنجره را می‌توانید ببندید."
        if ! command -v termux-wake-lock >/dev/null 2>&1; then
            say ""
            warn "termux-wake-lock نصب نیست."
            say "بدون آن اندروید ممکن است سرویس را در حالت خاموشی صفحه ببندد:"
            say "${CYN}  pkg install termux-api${OFF}"
        fi
        say "وضعیت:  bash bridge-setup.sh --status"
        say "لاگ:    bash bridge-setup.sh --log"
        say "توقف:   bash bridge-setup.sh --stop"
        exit 0
    fi
    rm -f "$PID_FILE"
    if grep -q "EADDRINUSE" "$LOG_FILE" 2>/dev/null; then
        die "پورت $PORT اشغال است. اول:  bash bridge-setup.sh --stop"
    fi
    warn "اجرای پس‌زمینه ناموفق بود. ۲۰ خط آخر لاگ:"
    tail -20 "$LOG_FILE" 2>/dev/null
    exit 1
fi

say "این پنجره را باز بگذارید."
PORT="$PORT" exec npx tsx server.ts
