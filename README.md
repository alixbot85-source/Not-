# Not-

پنل مدیریت اکانت‌های **ایتا** از طریق یک ربات **تلگرام**.

تلگرام فقط «پنل کنترل» است؛ تمام عملیات ایتا از لایهٔ سرویس مستقل
(`app/eitaa/`) انجام می‌شود و منطق رابط کاربری تلگرام هیچ وابستگی مستقیمی
به کتابخانه‌های ایتا ندارد.

---

## نصب و اجرا

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# BOT_TOKEN و ADMIN_IDS را پر کنید

python run.py
```

اگر پیکربندی ناقص باشد، ربات با پیام فارسی و فهرست دقیق موارد ناقص
خارج می‌شود و هیچ traceback خامی نشان نمی‌دهد.

### تست

```bash
pytest -q          # ۲۰۱ تست
```

---

## قابلیت‌های واقعی

| بخش | وضعیت | توضیح |
|---|---|---|
| مدیریت اکانت | ✅ کامل | افزودن، فهرست، بررسی وضعیت، حذف با تأیید |
| ارسال پیام و فایل | ✅ کامل | از طریق `eitaapy` (API رسمی ایتایار) |
| استخراج لینکدونی | ✅ کامل | از طریق `eitaa` (کانال‌های عمومی) |
| عضویت در گروه (Join) | ⚠️ نیازمند نصب دستی | فقط با نشست MTProto؛ `pyeitaa` روی PyPI نیست |
| فهرست گروه‌ها / مخاطبین | ⚠️ نیازمند نصب دستی | همان محدودیت بالا |
| Jobs با Stop/Pause/Resume | ✅ کامل | واقعی، نه تظاهری |
| خروجی TXT/CSV/JSON/XLSX/PDF | ✅ کامل | فارسی راست‌چین با فونت Vazirmatn |
| دستیار هوشمند (AI) | 🔌 سرویس بیرونی | با `AI_ENABLED` و `AI_API_KEY` فعال می‌شود |

هر قابلیتی که کتابخانه‌های ایتا واقعاً پشتیبانی نکنند، در رابط کاربری
با پیام صریح «پشتیبانی نمی‌شود» نمایش داده می‌شود و **هرگز شبیه‌سازی
نمی‌شود**. جزئیات کامل در `docs/AUDIT.md`.

---

## معماری

```
run.py                 نقطهٔ ورود
app/
  config.py            پیکربندی از .env + اعتبارسنجی
  security.py          رمزنگاری راز، حذف راز از لاگ، rate limit، مسیر امن
  logging_setup.py     لاگ سطح‌بندی‌شده در فایل (بدون راز)
  bot.py               ساخت Dispatcher و اتصال ۹ روتر
  middlewares.py       احراز هویت، محدودیت نرخ، تزریق وابستگی، خطای دوستانه
  db/                  models.py (enum + dataclass) و database.py (aiosqlite)
  eitaa/               ← لایهٔ ایتا، کاملاً مستقل از تلگرام
    base.py            رابط انتزاعی + Capability
    eitaayar_backend.py  پیاده‌سازی eitaapy
    mtproto_backend.py   پیاده‌سازی pyeitaa (در صورت نصب)
    extractor.py       استخراج، یکتاسازی و دسته‌بندی لینک
    service.py         کارخانهٔ Backend + گزارش صادقانهٔ قابلیت‌ها
  services/            jobs، joiner، sender، progress، exporter، ai
  ui/                  callbacks.py، keyboards.py، texts.py
  handlers/            ۹ روتر: accounts، linkdoni، joiner، sender،
                       jobs، exports، ai، settings، common
```

**قواعدی که در کد تضمین شده‌اند:**

- راز فقط در `Database.get_account_secret()` رمزگشایی می‌شود و تنها
  `build_backend()` آن را می‌خواند. هیچ مسیری آن را به رابط کاربری یا
  لاگ نمی‌رساند (تست سراسری این را بررسی می‌کند).
- هر عملیات طولانی یک Job با شناسه، وضعیت و لاگ سطح‌بندی‌شده است.
- توقف «تعاونی» است: هر حلقهٔ کارگر در هر تکرار `cooperative_wait()`
  را صدا می‌زند.
- پس از راه‌اندازی مجدد، Jobهای نیمه‌تمام به‌صورت
  **RECOVERABLE / NOT RECOVERABLE** علامت می‌خورند — Resume تظاهری وجود ندارد.

---

## مستندات

- `docs/AUDIT.md` — ممیزی پروژه، ممیزی کتابخانه‌های ایتا،
  ماتریس واقعی قابلیت‌های تلگرام (Bot API / Client / Mini App / سرویس بیرونی)
- `docs/REPORT.md` — گزارش نهایی پیاده‌سازی
- `.env.example` — تمام کلیدهای پیکربندی با توضیح

## مجوز فونت

`assets/fonts/Vazirmatn-Regular.ttf` — SIL Open Font License 1.1
(`assets/fonts/LICENSE-Vazirmatn.txt`).
