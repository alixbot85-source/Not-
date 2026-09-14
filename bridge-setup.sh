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
say "این پنجره را باز بگذارید."
say "در فایل .env پنل این خط باید باشد:"
say "${CYN}  EITAA_BRIDGE_URL=http://127.0.0.1:$PORT${OFF}"
say ""

command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
PORT="$PORT" exec npx tsx server.ts
