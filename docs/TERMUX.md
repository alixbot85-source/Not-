# اجرای ربات روی ترموکس (Termux)

> ⚠️ **قبل از هر چیز:** اگر توکن‌تان را جایی در گیت‌هاب قرار داده‌اید،
> از `@BotFather` دستور `/revoke` بزنید و توکن تازه بگیرید.
> توکن فقط در فایل `.env` می‌رود که هرگز commit نمی‌شود.

---

## چرا ترموکس دردسر دارد؟

`aiogram` به `pydantic-core` وابسته است و آن با زبان **Rust** نوشته شده.
برای اندروید wheel آمادهٔ رسمی وجود ندارد، پس pip می‌خواهد از سورس بسازد
و اگر Rust نباشد شکست می‌خورد. راه‌حل زیر این را حل می‌کند.

---

## مرحله ۱ — آماده‌سازی ترموکس

```bash
pkg update -y && pkg upgrade -y
pkg install -y python git rust binutils clang make libffi openssl libjpeg-turbo freetype
```

`rust` و `clang` برای ساخت `pydantic-core` و `cryptography` لازم‌اند.

## مرحله ۲ — گرفتن پروژه

```bash
cd ~
git clone -b arena/01a09ee4-not https://github.com/alixbot85-source/Not-.git
cd Not-
```

اگر قبلاً clone کرده‌اید:

```bash
cd ~/Not- && git pull
```

## مرحله ۳ — نصب کتابخانه‌ها

```bash
pip install --upgrade pip wheel setuptools

export CARGO_BUILD_TARGET="$(rustc -vV | sed -n 's|host: ||p')"
export CRYPTOGRAPHY_DONT_BUILD_RUST=0

pip install -r requirements.txt
```

⏳ این مرحله روی گوشی می‌تواند **۱۰ تا ۳۰ دقیقه** طول بکشد چون
`pydantic-core` کامپایل می‌شود. اگر ترموکس وسط کار بسته شد، دوباره
همین دستور را بزنید — ادامه می‌دهد.

برای اینکه اندروید ترموکس را نکشد:

```bash
termux-wake-lock
```

## مرحله ۴ — گذاشتن توکن

```bash
cp .env.example .env
nano .env
```

در `nano` این دو خط را پر کنید:

```
BOT_TOKEN=توکن‌تان‌از‑BotFather
ADMIN_IDS=آیدی‌عددی‌خودتان
```

ذخیره: `Ctrl + O` → `Enter` → خروج: `Ctrl + X`

> آیدی عددی‌تان را از ربات `@userinfobot` بگیرید.
> اگر `ADMIN_IDS` را نگذارید، هیچ‌کس حتی خودتان به پنل راه ندارد.

## مرحله ۵ — اجرا

```bash
python run.py
```

اگر درست باشد، این را می‌بینید:

```
اتصال برقرار شد: @YourBotName
ربات شروع شد. تعداد ادمین‌ها: 1
```

حالا در تلگرام به ربات‌تان `/start` بدهید.

---

## اجرای دائم در پس‌زمینه

```bash
termux-wake-lock
nohup python run.py > bot.out 2>&1 &
```

دیدن لاگ زنده:

```bash
tail -f logs/bot.log
```

متوقف کردن:

```bash
pkill -f "python run.py"
```

---

## اگر خطا گرفتید

| پیام خطا | علت و راه‌حل |
|---|---|
| `Cargo, the Rust package manager, is not installed` | `pkg install rust` را نزده‌اید |
| `can't find Rust compiler` | `export CARGO_BUILD_TARGET=$(rustc -vV \| sed -n 's\|host: \|\|p')` را اجرا کنید و دوباره pip بزنید |
| `Could not build wheels for cryptography` | `pkg install openssl libffi clang` سپس `pip install cryptography` |
| `ERROR: Installing pip is forbidden` | به‌جای `pip install --upgrade pip` بزنید `pkg upgrade python-pip` |
| `❌ ارتباط با سرور تلگرام برقرار نشد` | تلگرام در ایران فیلتر است — نیاز به فیلترشکن روی گوشی دارید |
| `توکن ربات معتبر نیست` | توکن در `.env` غلط است یا `/revoke` شده |
| `no such file: .env` | `cp .env.example .env` را نزده‌اید |

### اگر `pydantic-core` به هیچ صورت ساخته نشد

روش جایگزین با proot (کندتر ولی مطمئن‌تر):

```bash
pkg install proot-distro
proot-distro install debian
proot-distro login debian

apt update && apt install -y python3 python3-pip git
git clone -b arena/01a09ee4-not https://github.com/alixbot85-source/Not-.git
cd Not- && pip3 install -r requirements.txt --break-system-packages
cp .env.example .env && nano .env
python3 run.py
```

---

## نکتهٔ مهم دربارهٔ ایتا

قابلیت **عضویت در گروه (Joiner)** به کتابخانهٔ `pyeitaa` نیاز دارد که
روی PyPI نیست. بدون آن، ربات اجرا می‌شود و بخش‌های
**ارسال پیام، مدیریت اکانت، لینکدونی، خروجی‌ها** کار می‌کنند،
اما Joiner با وضعیت «در دسترس نیست» نمایش داده می‌شود.
جزئیات: `docs/AUDIT.md` §2.4

---

## ورود با شمارهٔ تلفن (بدون توکن)

ورود با شماره به یک کلاینت واقعی MTProto نیاز دارد. هیچ کتابخانهٔ
پایتونی روی PyPI این کار را نمی‌کند، اما پروژهٔ **EitaaBun** آن را
پیاده کرده است: https://github.com/ghaemifard/EitaaBun

### ⚠️ نکتهٔ مهم: Bun روی ترموکس اجرا نمی‌شود

مستندات خود EitaaBun می‌گوید با Bun اجرا شود، اما **Bun روی اندروید
کار نمی‌کند** — برای glibc ساخته شده و اندروید از bionic libc استفاده
می‌کند. اگر `curl ... bun.sh/install` را اجرا کنید، یا نصب نمی‌شود یا
هنگام اجرا می‌شکند.

**راه‌حل:** هستهٔ MTProto این پروژه هیچ API اختصاصی Bun ندارد؛ فقط چند
فراخوانی `Bun.write`/`Bun.file` در لایهٔ ذخیره‌سازی. اسکریپت زیر آن‌ها
را با معادل Node جایگزین می‌کند و سرویس را روی **Node.js** بالا می‌آورد.

### راه‌اندازی — یک دستور

در یک **پنجرهٔ ترموکس جدا** (منوی کناری → `New session`):

```bash
cd ~/Not- && bash bridge-setup.sh --bg
```

مدیریت سرویس پل:

| دستور | کار |
|---|---|
| `bash bridge-setup.sh --bg` | اجرا در پس‌زمینه (پنجره را می‌توانید ببندید) |
| `bash bridge-setup.sh --status` | آیا در حال اجراست؟ |
| `bash bridge-setup.sh --log` | دیدن لاگ زنده |
| `bash bridge-setup.sh --stop` | توقف کامل (فرزندهای رهاشده را هم می‌بندد) |

> اگر ترموکس را ببندید یا اندروید آن را بکُشد، سرویس هم متوقف می‌شود.
> با `--status` بررسی کنید و در صورت نیاز دوباره `--bg` بزنید.

اسکریپت خودش Node را نصب می‌کند، سورس را می‌گیرد، لایهٔ سازگاری را
می‌سازد، وابستگی‌ها را نصب می‌کند و سرویس را اجرا می‌کند. این پنجره
را **باز بگذارید**.

وقتی این را دیدید آماده است:

```
Server is running on http://localhost:1234
```

### اتصال پنل

در پنجرهٔ اصلی:

```bash
cd ~/Not-
echo "EITAA_BRIDGE_URL=http://127.0.0.1:1234" >> .env
python run.py
```

حالا در «مدیریت اکانت‌ها» گزینهٔ **📱 ورود با شمارهٔ تلفن** فعال است:

۱. شماره را می‌فرستید → کد به ایتای شما می‌آید
۲. کد را می‌فرستید → نشست ساخته می‌شود
۳. اگر رمز دومرحله‌ای دارید، پرسیده می‌شود

بعد از آن **Joiner، فهرست گروه‌ها، مخاطبین و چت‌های خصوصی** فعال می‌شوند.

### خطاهای این بخش

| پیام | معنی |
|---|---|
| «سرویس پل در حال اجرا نیست» | پنجرهٔ `bridge-setup.sh` بسته شده یا بالا نیامده |
| «سرویس پل به سرور ایتا وصل نشد» | پل سالم است ولی اینترنت/دسترسی به ایتا ندارد |
| «نشست معتبر نیست» | باید دوباره با شماره وارد شوید |

### محدودیت واقعی

عضویت با **لینک دعوت خصوصی** (`joinchat`) از این مسیر ممکن نیست، چون
EitaaBun متد `importChatInvite` را ندارد. فقط عضویت با شناسهٔ عددی
کانال/گروه کار می‌کند. پنل این را صریح اعلام می‌کند و وانمود نمی‌کند.
