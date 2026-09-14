# گزارش نهایی — پنل مدیریت ایتا از طریق ربات تلگرام

تاریخ: ۲۰۲۶-۰۹-۱۴ · شاخه: `arena/01a09ee4-not`
مخزن پایه: `alixbot85-source/Not-` (قبل از شروع فقط شامل `README.md` بود)

> این گزارش فقط چیزهایی را «پیاده‌سازی‌شده» می‌نامد که واقعاً اجرا می‌شوند.
> هر جا کتابخانه یا API واقعی وجود نداشت، صراحتاً اعلام شده است.
> ممیزی کامل کتابخانه‌ها و ماتریس قابلیت‌های تلگرام در `docs/AUDIT.md`.

---

## IMPLEMENTED

پیاده‌سازی‌شده و با تست تأییدشده (۲۰۱ تست، همگی سبز):

**۱. اسکلت و پیکربندی**
- `run.py` + `app/bot.py` — راه‌اندازی، اعتبارسنجی پیکربندی پیش از اجرا،
  بررسی توکن با `get_me()`، خاموشی تمیز (بستن Jobها، دیتابیس و نشست).
- `app/config.py` — خواندن از `.env`، اعتبارسنجی، ساخت پوشه‌ها با مجوز `0700`
  برای `data/` و `data/sessions/`.
- خطای پیکربندی و خطای شبکه با پیام فارسی خارج می‌شوند؛ **هیچ traceback خامی
  به کاربر نمایش داده نمی‌شود** (تأیید عملی: اجرای واقعی `python run.py`).

**۲. امنیت (`app/security.py`، ۳۳ تست)**
- رمزنگاری راز با `Fernet`؛ کلید از `SECRET_KEY` یا فایل `data/secret.key` با مجوز `0600`.
- `redact()` — حذف توکن/شمارهٔ تلفن/کلید از هر متنی پیش از لاگ.
- `safe_filename()` + `resolve_inside()` — ضد Path Traversal (`../`، مسیر مطلق، nullbyte).
- `clean_text()` — حذف کاراکترهای کنترلی و محدودسازی طول.
- Rate limit پنجرهٔ لغزان per-user.
- ضد CSV Injection در خروجی‌ها (`=`، `+`، `-`، `@`، tab، CR).

**۳. دیتابیس (`app/db/`، ۱۶ تست)** — `aiosqlite` با WAL و
۱۱ جدول: `users`, `accounts`, `linkdoni`, `jobs`, `job_items`, `job_logs`,
`extracted_links`, `drafts`, `settings`, `audit_logs`, `exports`.
یکتاسازی در سطح دیتابیس: `UNIQUE(linkdoni.url)` و `UNIQUE(extracted_links.job_id, url)`.

**۴. لایهٔ ایتا (`app/eitaa/`، ۱۶ تست)** — کاملاً مستقل از تلگرام.
- `base.py` — رابط انتزاعی `EitaaBackend` + `Capability`
  (`AVAILABLE` / `UNAVAILABLE` / `NOT_SUPPORTED`). پیش‌فرض هر عملیات
  «پشتیبانی نمی‌شود» است تا هیچ قابلیتی سهواً وانمود نشود.
- `eitaayar_backend.py` — روی `eitaapy 1.2.0` (API واقعی `eitaayar.ir`):
  `get_me`، `send_message`، `send_file`.
- `extractor.py` — روی `eitaa 2.3.1`: استخراج لینک از کانال عمومی،
  یکتاسازی، دسته‌بندی Group/Channel/User/Invite/Unknown.
- `service.py` — تنها نقطه‌ای که راز از دیتابیس خارج می‌شود.

**۵. موتور Jobs (`app/services/jobs.py`، ۱۰ تست)**
- وضعیت‌ها: PENDING / RUNNING / PAUSED / STOPPING / STOPPED / COMPLETED / FAILED / CANCELLED.
- Stop و Pause/Resume **واقعی** هستند (تست شمارندهٔ متوقف‌شده و سپس پیش‌رونده را می‌بیند).
- Retry با backoff نمایی.
- بازیابی پس از راه‌اندازی مجدد: Jobهای یتیم با
  `recoverable=True/False` بر اساس وجود آیتم PENDING علامت می‌خورند.

**۶. Joiner** — انتخاب اکانت → انتخاب لینکدونی → استخراج → یکتاسازی →
دسته‌بندی → گزارش استخراج → صف عضویت. فقط GROUP و INVITE وارد صف می‌شوند.

**۷. Sender (`app/handlers/sender.py`، ۵۴۹ خط)** — انتخاب اکانت،
ویرایشگر متن با قالب‌بندی HTML، **پیوست فایل**، انتخاب مقصد
(گروه‌ها / مخاطبین / چت خصوصی / ورود دستی)، پیش‌نمایش با تأیید-ویرایش-انصراف،
پیشرفت زنده، توقف، آمار.

**۸. پیشرفت زنده (`app/services/progress.py`)** — با **ویرایش همان پیام**
و فاصلهٔ زمانی قابل تنظیم (پیش‌فرض ۳ ثانیه)؛ هیچ اسپمی وجود ندارد.

**۹. خروجی‌ها (`app/services/exporter.py`، ۱۵ تست)** — هر ۵ قالب واقعی:

| قالب | تأیید عملی |
|---|---|
| TXT | UTF-8 |
| CSV | با BOM برای Excel + ضد CSV Injection |
| JSON | `ensure_ascii=False` |
| XLSX | zip واقعی، `sheet_view.rightToLeft = True` |
| PDF | `%PDF-1.4` واقعی، فونت Vazirmatn جاسازی‌شده، RTL با `arabic_reshaper` + `python-bidi` |

**۱۰. رابط کاربری (`app/ui/`، ۴۳ تست)** — طرح callback استاندارد
`<ns>:<action>[:<arg>]` با اعتبارسنجی regex و سقف ۶۴ بایت،
صفحه‌بندی همهٔ فهرست‌ها، دکمهٔ 🏠/🔙 در همه‌جا، تأیید برای عملیات مخرب،
و حالت‌های خالی / در حال بارگذاری / خطا / موفقیت.

**۱۱. `validate_telegram_html()`** — اعتبارسنجی محلی قالب‌بندی طبق
فهرست واقعی تگ‌های Bot API (۱۵ تگ). **جایگزین روش قبلی شد** که یک پیام
آزمایشی می‌فرستاد و حذف می‌کرد (هم چشمک‌زدن در UI بود، هم غیرقابل تست).

**۱۲. Middlewareها** — احراز هویت (فقط `ADMIN_IDS`)، محدودیت نرخ،
تزریق وابستگی، و گرفتن خطای مدیریت‌نشده و تبدیل آن به پیام فارسی.

**۱۳. لاگ** — پنج سطح INFO/SUCCESS/WARNING/ERROR/DEBUG در دیتابیس
(به ازای هر Job) و دو فایل `logs/bot.log` و `logs/error.log` با چرخش،
هر دو از `redact()` عبور می‌کنند.

---

## PARTIALLY IMPLEMENTED

| قابلیت | وضعیت | دلیل دقیق |
|---|---|---|
| **عضویت در گروه/کانال (Join)** | کد کامل، غیرفعال | نیازمند نشست MTProto. پیاده‌سازی در `mtproto_backend.py` روی TLهای واقعی `channels.JoinChannel` و `messages.ImportChatInvite` نوشته شده، اما `pyeitaa` روی PyPI نیست و upstream آن حذف شده. تا نصب دستی، وضعیت `UNAVAILABLE` گزارش می‌شود. |
| **فهرست گروه‌ها / چت‌های خصوصی** | همان | `messages.GetDialogs` |
| **فهرست مخاطبین** | همان | `contacts.GetContacts` |
| **ورود با شماره تلفن** | همان | `auth.SendCode` / `auth.SignIn` |
| **دستیار هوشمند (AI)** | کد کامل، خاموش | نیازمند کلید API بیرونی؛ با `AI_ENABLED=true` و `AI_API_KEY` فعال می‌شود. تا آن زمان دکمه‌ها اصلاً نمایش داده نمی‌شوند. |

کاربر به‌جای خطای مبهم، پیام نصب دقیق می‌بیند و **هیچ عملیات جعلی انجام نمی‌شود**.

---

## NOT AVAILABLE

- **آلبوم / Media Group در ایتا** — نه `eitaapy` و نه API ایتایار چنین
  چیزی ندارند. پیاده‌سازی نشد.
- **ویرایش یا حذف پیام ارسال‌شده در ایتا** — در API موجود نیست.
- **دریافت پیام‌های ورودی ایتا (Webhook/Polling)** — ایتایار فقط ارسال دارد.
- **Pause/Resume پس از راه‌اندازی مجدد فرآیند** — عمداً پیاده نشد؛
  به‌جای آن Job با برچسب صادقانهٔ RECOVERABLE / NOT RECOVERABLE ذخیره می‌شود.

---

## CLIENT ONLY

قابلیت‌هایی که فقط با Client (MTProto) ممکن‌اند و **ربات هرگز نمی‌تواند**:

| قابلیت | توضیح |
|---|---|
| عضویت در گروه با لینک دعوت | ربات‌ها فقط با افزوده‌شدن توسط ادمین وارد می‌شوند |
| خواندن فهرست دیالوگ‌ها | ربات دیالوگ ندارد |
| خواندن دفترچهٔ مخاطبین | مختص حساب کاربری |
| شروع گفتگو با کاربری که ربات را استارت نکرده | ممنوع در Bot API |
| خواندن تاریخچهٔ پیام‌های قدیمی | `messages.GetHistory` مختص Client |

---

## MINI APP REQUIRED

مواردی که با پیام و دکمه ممکن نیستند. **هیچ‌کدام پیاده نشد**، چون هیچ‌یک
برای عملکرد اصلی پنل ضروری نبود و افزودن Mini App برای فرم ساده،
خلاف درخواست صریح شما بود:

| قابلیت | چرا Mini App |
|---|---|
| جدول واقعی با ستون‌های قابل مرتب‌سازی | Bot API جدول ندارد |
| نمودار و گراف آماری | فقط HTML/Canvas |
| انتخاب چندتایی با drag & drop | خارج از توان صفحه‌کلید اینلاین |
| ویرایشگر متن WYSIWYG | فقط HTML |
| نقشه، LaTeX، Task-list | Bot API پشتیبانی نمی‌کند |

جایگزین‌های پیاده‌شده: صفحه‌بندی، انتخاب همه/هیچ‌کدام، تغییر وضعیت تکی،
و خروجی XLSX/PDF برای جدول و گزارش.

---

## EXTERNAL SERVICE REQUIRED

| سرویس | مصرف | وضعیت |
|---|---|---|
| API سازگار با OpenAI | بازنویسی، ترجمه، خلاصه، کوتاه/بلندسازی، اصلاح نگارش، عنوان، کپشن، تغییر لحن | کد نوشته شده (`app/services/ai.py`)، با کلید فعال می‌شود |
| `eitaayar.ir` | ارسال پیام و فایل ایتا | فعال |
| سرور MTProto ایتا | Join و Dialogs | نیازمند `pyeitaa` |

---

## FILES CREATED

**مستندات (۳)** — `docs/AUDIT.md` (۱۸۵)، `docs/REPORT.md` (همین فایل)،
`.env.example` (۴۵)

**پیکربندی (۴)** — `requirements.txt`, `.gitignore`, `pytest.ini`, `run.py` (۱۲)

**هستهٔ برنامه (۹)**

| فایل | خط | نقش |
|---|---|---|
| `app/config.py` | ۱۵۴ | پیکربندی و اعتبارسنجی |
| `app/security.py` | ۲۳۷ | رمزنگاری، redaction، مسیر امن، rate limit |
| `app/logging_setup.py` | ۴۷ | لاگ چرخشی بدون راز |
| `app/bot.py` | ۱۶۷ | Dispatcher و اتصال روترها |
| `app/middlewares.py` | ۱۰۶ | authz، rate limit، DI، خطای دوستانه |
| `app/db/models.py` | ۲۵۸ | enumها و dataclassها |
| `app/db/database.py` | ۶۶۴ | مخزن aiosqlite |
| `app/__init__.py`, `app/db/__init__.py` | — | بسته |

**لایهٔ ایتا (۶)** — `base.py` (۱۳۵)، `eitaayar_backend.py` (۱۳۹)،
`mtproto_backend.py` (۳۷۹)، `extractor.py` (۱۶۱)، `service.py` (۱۲۱)، `__init__.py` (۲۳)

**سرویس‌ها (۷)** — `jobs.py` (۲۲۶)، `joiner.py` (۱۹۲)، `sender.py` (۱۳۲)،
`progress.py` (۹۱)، `exporter.py` (۲۶۴)، `ai.py` (۱۲۲)، `__init__.py`

**رابط کاربری (۴)** — `callbacks.py` (۸۶)، `keyboards.py` (۴۵۵)، `texts.py` (۴۱۸)، `__init__.py`

**Handlerها (۱۰)** — `accounts.py` (۳۳۶)، `linkdoni.py` (۱۸۳)، `joiner.py` (۳۳۸)،
`sender.py` (۵۴۹)، `jobs.py` (۲۴۳)، `exports.py` (۱۵۳)، `ai.py` (۱۱۲)،
`settings.py` (۱۱۲)، `common.py` (۱۲۳)، `__init__.py` (۱)

**تست‌ها (۱۰)** — `conftest.py` (۳۶)، `test_security.py` (۱۲۸)،
`test_database.py` (۱۶۷)، `test_extractor.py` (۸۷)، `test_callbacks.py` (۱۴۰)،
`test_exporter.py` (۱۲۷)، `test_jobs_engine.py` (۱۶۹)، `test_backends.py` (۱۴۱)،
`test_ui_texts.py` (۲۷۵)، `test_flows.py` (۵۰۹)

**دارایی‌ها (۲)** — `assets/fonts/Vazirmatn-Regular.ttf` (۱۲۲٬۷۵۲ بایت)،
`assets/fonts/LICENSE-Vazirmatn.txt` (SIL OFL 1.1)

**جمع: ۵۵ فایل، حدود ۸٬۵۰۰ خط کد پایتون.**

## FILES MODIFIED

- `README.md` — از یک خط (`# Not-`) به راهنمای کامل نصب، معماری و قابلیت‌ها
  گسترش یافت. محتوای قبلی حذف نشد.

---

## DEPENDENCIES ADDED

همگی نصب و ایمپورت آن‌ها در Python 3.11 **عملاً تأیید شد**:

| بسته | نسخهٔ نصب‌شده | چرا |
|---|---|---|
| `aiogram` | 3.31.0 | فریم‌ورک Bot API |
| `aiosqlite` | 0.22.1 | درایور async SQLite |
| `aiofiles` | 25.1.0 | IO فایل async |
| `cryptography` | 50.0.1 | Fernet برای رمزنگاری راز |
| `eitaapy` | 1.2.0 | API ایتایار (ارسال) |
| `eitaa` | 2.3.1 | استخراج عمومی لینکدونی |
| `openpyxl` | 3.1.5 | XLSX |
| `reportlab` | 5.0.1 | PDF |
| `arabic-reshaper` | 3.0.1 | شکل‌دهی فارسی |
| `python-bidi` | 0.6.11 | الگوریتم BiDi |
| `pytest` / `pytest-asyncio` | 9.1.1 / 1.4.0 | تست |

**عمداً pin نشده:** `pyeitaa` — روی PyPI نیست (`docs/AUDIT.md` §2.4).

---

## DATABASE CHANGES

پروژه قبلاً دیتابیسی نداشت؛ کل شِما جدید است. ۱۱ جدول با ایندکس روی
`jobs.status`, `job_items.job_id`, `job_logs.job_id`, `extracted_links.job_id`,
`audit_logs.created_at`.

انحراف آگاهانه از فهرست درخواستی:

| جدول درخواستی | پیاده‌سازی |
|---|---|
| `sessions` | در `accounts` ادغام شد (`secret_enc`, `session_name`) — جدول جدا مزیتی نداشت و سطح افشای راز را زیاد می‌کرد |
| `sender_settings` | در `settings` (کلید-مقدار) و `drafts` |
| `targets` | `job_items` — مقصدها همیشه متعلق به یک Job هستند |
| `permissions` | `users.role` + `audit_logs` |

## MIGRATION REQUIRED

**خیر.** شِما با `CREATE TABLE IF NOT EXISTS` در هر بار اجرا ساخته می‌شود.
دیتابیس قبلی‌ای وجود ندارد که مهاجرت لازم باشد. برای شروع تازه کافی است
`data/panel.db` حذف شود.

---

## KNOWN LIMITATIONS

1. **آزمون زنده انجام نشده.** محیط توسعه به `api.telegram.org`،
   `eitaa.com` و `eitaayar.ir` دسترسی شبکه‌ای ندارد (تأیید شد: TLS EOF).
   بنابراین ۲۰۱ تست، منطق را با یک لایهٔ شبکهٔ جایگزین تست می‌کنند —
   **جریان‌ها در برابر سرور واقعی تأیید نشده‌اند.** اولین اجرای واقعی
   باید با یک اکانت آزمایشی انجام شود.
2. **Joiner بدون `pyeitaa` کار نمی‌کند** (بالا توضیح داده شد).
3. **استخراج لینکدونی فقط از کانال عمومی** ممکن است؛ لینکدونی خصوصی
   نیازمند نشست است.
4. **دسته‌بندی لینک محافظه‌کارانه است.** هر لینکی که ساختارش قطعی نباشد
   `UNKNOWN` می‌ماند و وارد صف عضویت نمی‌شود — ترجیح دادیم چیزی از قلم بیفتد
   تا اینکه ادعای نادرست شود.
5. **فقط وزن Regular فونت** ارسال شده است؛ PDF هیچ‌جا Bold فرض نمی‌کند.
6. **سقف ۸۰۰ ردیف در PDF** برای کنترل حجم فایل؛ CSV/XLSX کامل‌اند.
7. **پیوست فایل حداکثر ۲۰ مگابایت** — محدودیت واقعی دانلود فایل در Bot API.
8. **SQLite تک‌نویسنده** است. برای این بار کاری کافی است؛ برای چند نمونهٔ
   همزمان باید به PostgreSQL مهاجرت کرد.
9. **Rate limit در حافظه** است و با راه‌اندازی مجدد صفر می‌شود.
10. **قالب‌بندی HTML فقط برای نمایش در تلگرام** است؛ متنی که به ایتا
    می‌رسد متن ساده است. این موضوع در خود ویرایشگر به کاربر گفته می‌شود.

---

## RUN COMMAND

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# BOT_TOKEN و ADMIN_IDS را پر کنید

python run.py
```

تست:

```bash
pytest -q          # ۲۰۱ passed
```

---

## پیوست: نتیجهٔ تست‌ها

```
tests/test_security.py      ۳۳   رمزنگاری، redaction، مسیر امن، rate limit
tests/test_ui_texts.py      ۴۳   ایمنی HTML، XSS، نوار پیشرفت، برچسب enumها
tests/test_flows.py         ۳۵   جریان کامل کاربر از طریق Dispatcher واقعی
tests/test_callbacks.py     ۲۲   طرح callback، سقف ۶۴ بایت، ورودی مخرب
tests/test_backends.py      ۱۶   صداقت Capability، عدم تظاهر
tests/test_database.py      ۱۶   CRUD، یکتاسازی، شمارنده‌ها
tests/test_exporter.py      ۱۵   BOM، ضد injection، RTL، PDF واقعی
tests/test_extractor.py     ۱۱   استخراج، یکتاسازی، دسته‌بندی
tests/test_jobs_engine.py   ۱۰   Stop/Pause/Resume واقعی، بازیابی، retry
────────────────────────────────
جمع                        ۲۰۱   همگی سبز
```
