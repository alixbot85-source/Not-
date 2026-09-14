# AUDIT — بررسی واقعی پیش از پیاده‌سازی

> تمام یافته‌های این سند با اجرای واقعی `pip`، دانلود پکیج و بازرسی سورس به‌دست آمده‌اند.
> هیچ موردی حدس زده نشده است. هرجا اطلاعات در دسترس نبوده، صریحاً «اطلاعات موجود نیست» ثبت شده.

## 1. AUDIT پروژه موجود

مخزن `alixbot85-source/Not-` در commit `66f3db0` بررسی شد:

```
.
└── README.md      (۷ بایت، محتوا: «# Not-»)
```

| مورد | یافته |
|---|---|
| Project structure | وجود ندارد — فقط README |
| Framework / Python version | وجود ندارد (سندباکس: Python 3.11.2) |
| Dependencies / Database / Models | وجود ندارد |
| Handlers / Routers / Middlewares / FSM | وجود ندارد |
| Services / Workers / Queues | وجود ندارد |
| Session management / Logging / Config | وجود ندارد |
| Existing Sender / Joiner / Account mgmt | وجود ندارد |

**نتیجه:** قانون «Rewrite ممنوع» موضوعیت پیدا نکرد چون کد قبلی‌ای وجود ندارد.
`README.md` حفظ و فقط توسعه داده شد. هیچ فایل موجودی حذف یا بازنویسی نشد.

---

## 2. EITAAPY AUDIT — بررسی واقعی کتابخانه‌های ایتا

نام «EitaaPy / eitapy» به چند پکیج متفاوت اشاره دارد. همه بررسی شدند:

### 2.1 `eitapy` — موجود نیست
```
$ pip download eitapy
ERROR: Could not find a version that satisfies the requirement eitapy (from versions: none)
```
**اطلاعات موجود نیست — چنین پکیجی روی PyPI وجود ندارد.**

### 2.2 `eitaapy` 1.2.0 (PyPI) — ✅ واقعی، نصب و تأیید شد
سورس کامل بازرسی شد (`eitaapy/__init__.py`). کل سطح API:

| متد واقعی | امضای واقعی | Async |
|---|---|---|
| `Robot.__init__` | `(token)` → `https://eitaayar.ir/api/{token}` | — |
| `Robot.get_me` | `()` | ✅ |
| `Robot.send_message` | `(chat_id, text, title=None, notification_disable=None, id_message_to_reply=None, date=None, pin=None, view_count_for_delete=None)` | ✅ |
| `Robot.send_file` | `(chat_id, file, caption=None)` | ✅ |

**ماهیت واقعی:** یک wrapper نازک روی **HTTP API توکن‌محورِ eitaayar.ir** است.

> ⚠️ یافتهٔ حیاتی: `eitaapy` **کتابخانهٔ Session/Client نیست**.
> هیچ متدی برای `join`، `dialogs`، `contacts`، `login با شماره` یا `session` **ندارد**.
> ساختن Joiner روی این کتابخانه غیرممکن است — و جعل آن ممنوع.

### 2.3 `eitaa` 2.3.1 / EitaaPyKit — ✅ واقعی، نصب و تأیید شد
متدهای واقعی تأییدشده با `inspect`:

| متد | امضا | ماهیت |
|---|---|---|
| `get_info(channel_or_user_id)` | static | Scraping صفحهٔ عمومی eitaa.com |
| `get_latest_messages(channel_id)` | static | Scraping پیام‌های عمومی کانال |
| `get_message(username, message_id)` | static | Scraping یک پیام |
| `get_trends()` | static | Scraping trends.eitaa.com |
| `send_message(chat_id, text, pin, date, view_to_delete, disable_notification, reply_to_message_id)` | instance | eitaayar token API |
| `send_file(chat_id, caption, file, ...)` | instance | eitaayar token API |

**کاربرد واقعی در این پروژه:** استخراج لینک از لینکدونی‌های **عمومی** بدون نیاز به Session.

### 2.4 `pyeitaa` — دو پکیج کاملاً متفاوت با یک نام

**الف) `pyeitaa` 0.1.2 روی PyPI — ❌ شکسته**
```
$ python -c "import pyeitaa"
ModuleNotFoundError: No module named 'pyeitaa.network'
```
فایل `RECORD` تأیید می‌کند که فقط ۳ فایل منتشر شده؛ ماژول‌های `network/`, `methods/`, `storage/`
که `client.py` ایمپورت می‌کند **در wheel وجود ندارند**. این پکیج قابل استفاده نیست.

**ب) `pyeitaa` 0.1.0 اثر MSDanesh — ✅ فریم‌ورک واقعی MTProto ایتا**
- Upstream (`github.com/MSDanesh/pyeitaa`): **`Repository not found` (حذف شده)**
- تنها نسخهٔ موجود: کپی vendor شده داخل `github.com/khosravisj/eitaa-fetcher3`
- ۱۹۱۳ فایل پایتون، ۸.۲MB، **Layer 135**

RPCهای خام واقعی که مستقیماً در سورس تأیید شدند:

| RPC واقعی | ID / امضای تأییدشده | کاربرد |
|---|---|---|
| `channels.JoinChannel` | `0x24b524c5`, `(channel: InputChannel)` | Join کانال/گروه عمومی |
| `messages.ImportChatInvite` | `0x6c50051c`, `(hash: str)` | Join با لینک دعوت |
| `messages.CheckChatInvite` | `(hash: str)` | اعتبارسنجی لینک قبل از Join |
| `contacts.ResolveUsername` | `(username: str)` | تشخیص نوع لینک (Group/Channel/User) |
| `messages.GetDialogs` | `(offset_date, offset_id, offset_peer, limit, hash, ...)` | Target: Groups / Private Chats |
| `contacts.GetContacts` | — | Target: Contacts |
| `messages.SendMessage` | `(peer, message, random_id, entities=..., ...)` | Sender |
| `messages.SendMedia` / `SendMultiMedia` | — | Media / Album |
| `messages.GetHistory` | — | استخراج لینک از لینکدونی |
| `auth.SendCode` / `auth.SignIn` | `send_code(phone_number,...)` / `sign_in(phone_number, phone_code_hash, phone_code)` | ورود با شماره |

خطاهای واقعی تأییدشده در `errors/exceptions/`: `FloodWait`, `SlowmodeWait`,
`UserAlreadyParticipant`, `InviteHashExpired`, `InviteHashInvalid`, `ChannelsTooMuch`,
`ChannelPrivate`, `UsernameNotOccupied`, `SessionPasswordNeeded` (۳۴۴ کلاس فقط در `bad_request_400`).

> ⚠️ **محدودیت واقعی و غیرقابل دور زدن:** این فریم‌ورک روی PyPI **قابل نصب نیست**
> و upstream آن حذف شده. کپی موجود هم patch شده تا به PostgreSQL و
> `settings.py` و `eitaa_database.py` پروژهٔ ثالث وابسته باشد
> (`from eitaa_database import EitaaDatabase` در `client.py` و `methods/utils/start.py`).
>
> بنابراین **Joiner واقعی وابسته به نصب دستی این پکیج توسط کاربر است.**
> کد adapter آن نوشته شده و دقیقاً با همین امضاهای تأییدشده کار می‌کند،
> ولی تا وقتی پکیج نصب نشود وضعیت آن `UNAVAILABLE` گزارش می‌شود — **Fake نشده است.**

### 2.5 جمع‌بندی: چه چیزی واقعاً ممکن است؟

| قابلیت | Backend واقعی | وضعیت |
|---|---|---|
| Sender به کانال/گروه | `eitaapy.Robot` (توکن eitaayar) | ✅ کار می‌کند |
| ارسال فایل/مدیا | `eitaapy.Robot.send_file` | ✅ کار می‌کند |
| اعتبارسنجی اکانت | `eitaapy.Robot.get_me` | ✅ کار می‌کند |
| استخراج لینک از لینکدونی عمومی | scraping واقعی eitaa.com | ✅ کار می‌کند |
| Join گروه/کانال | `pyeitaa` MTProto | ⚠️ نیازمند نصب دستی |
| Dialogs / Contacts | `pyeitaa` MTProto | ⚠️ نیازمند نصب دستی |
| ورود با شماره + کد | `pyeitaa` MTProto | ⚠️ نیازمند نصب دستی |

---

## 3. TELEGRAM BOT API AUDIT

منبع: مستندات رسمی `core.telegram.org/bots/api` + تأیید عملی روی `aiogram 3.31.0` نصب‌شده.

### 3.1 تأیید عملی روی کتابخانه
```python
ParseMode: ['MarkdownV2', 'Markdown', 'HTML']
InlineKeyboardButton fields: ['callback_data', 'callback_game', 'copy_text', 'disabled',
  'icon_custom_emoji_id', 'login_url', 'pay', 'style', 'switch_inline_query',
  'switch_inline_query_chosen_chat', 'switch_inline_query_current_chat', 'text', 'url', 'web_app']
```

### 3.2 ماتریس قابلیت‌ها (بخش ۲۲ و ۲۳)

| Feature | Bot API | Client Only | Mini App | External | وضعیت در این پروژه |
|---|---|---|---|---|---|
| Bold / Italic / Underline / Strike | ✅ | — | — | — | **IMPLEMENTED** |
| Spoiler (`<tg-spoiler>`) | ✅ | — | — | — | **IMPLEMENTED** |
| Inline Code / Code Block (`<pre><code>`) | ✅ | — | — | — | **IMPLEMENTED** |
| Link / Mention (`tg://user?id=`) | ✅ | — | — | — | **IMPLEMENTED** |
| Quote (`<blockquote>`) — Bot API 7.2+ | ✅ | — | — | — | **IMPLEMENTED** |
| Expandable Quote (`<blockquote expandable>`) — 7.3+ | ✅ | — | — | — | **IMPLEMENTED** |
| Inline Keyboard / Callback / URL Buttons | ✅ | — | — | — | **IMPLEMENTED** |
| Edit Message (Live Progress) | ✅ | — | — | — | **IMPLEMENTED** |
| Send Document (Export) | ✅ | — | — | — | **IMPLEMENTED** |
| Media Group (`sendMediaGroup`) | ✅ | — | — | — | در Telegram پشتیبانی می‌شود؛ **در سمت ایتا NOT AVAILABLE** |
| Copy Text Button (`copy_text`) | ✅ | — | — | — | **IMPLEMENTED** (نمایش لینک) |
| Poll / Quiz | ✅ | — | — | — | **NOT IMPLEMENTED** (نیاز محصول نبود) |
| Web App / Mini App | ✅ (دکمه) | — | ✅ (UI) | نیاز به HTTPS | **NOT IMPLEMENTED** — طبق بخش ۲۴ ارزش نداشت |
| Login with Telegram | ✅ (`login_url`) | — | — | نیاز به دامنه در BotFather | **NOT IMPLEMENTED** |
| Colored / Styled Buttons | فیلد `style` در aiogram 3.31 موجود است | — | — | — | **NOT USED** — رفتار واقعی در مستندات رسمی تأیید نشد |
| Tables | ❌ در پیام معمولی | — | ✅ | — | **MINI APP REQUIRED** — با `<pre>` شبیه‌سازی متنی شد |
| LaTeX / Formula | ❌ | — | ✅ | ✅ | **NOT AVAILABLE** |
| Passkeys / Maps / Task Lists | ❌ در Bot API پیام‌رسان | — | ✅ | ✅ | **NOT AVAILABLE** |
| Communities / Member Tags / Mighty Polls | اطلاعات موجود نیست | — | — | — | **NOT VERIFIED → استفاده نشد** |
| AI features | ❌ بومی نیست | — | — | ✅ | **EXTERNAL SERVICE REQUIRED** |

> هیچ‌کدام از موارد `NOT AVAILABLE` / `MINI APP REQUIRED` در کد به‌عنوان Bot API جا زده نشده‌اند.

### 3.3 تفکیک Bot API در برابر Client
ربات تلگرام در این پروژه **فقط پنل کنترل** است. تمام عملیات ایتا در لایهٔ سرویس
جدا (`app/eitaa/`) انجام می‌شود. هیچ قابلیت Telegram Client (مثل خواندن دیالوگ‌های کاربر
یا join کردن کاربر تلگرام) به Bot API نسبت داده نشده است.

---

## 4. محیط تست — شفافیت کامل

```
$ curl https://api.telegram.org   → 000 (مسدود)
$ curl https://eitaa.com          → TLS EOF (مسدود)
$ curl https://pypi.org           → 200 (آزاد)
```

سندباکس به شبکهٔ تلگرام و ایتا دسترسی **ندارد**. بنابراین:
- ✅ تست‌های واقعی: DB، Job engine، استخراج/dedup/طبقه‌بندی لینک، Export (شامل PDF فارسی)،
  رندر کیبورد و Callback، pagination، امنیت و redaction.
- ❌ تست زندهٔ end-to-end با سرور تلگرام/ایتا **انجام نشده** و ادعا نمی‌شود.
