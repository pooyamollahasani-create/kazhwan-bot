# ربات کژوان — نسخه آزمایشی MVP

این نسخه شامل این امکانات است:

- ثبت نام و نام خانوادگی
- دریافت شماره تماس با دکمه رسمی تلگرام
- ثبت شهر محل سکونت
- بررسی عضویت در کانال `@Kazhwantravel`
- نمایش و پذیرش قوانین
- ثبت نحوه آشنایی با کژوان
- صدور شناسه عضویت مثل `KZH-000001`
- منوی اصلی
- پروفایل و تاریخچه فعالیت‌های کاربر
- فرمان مدیریتی `/chatid` برای دریافت شناسه عددی گروه
- فرمان مدیریتی `/stats` برای آمار اولیه

## راه‌اندازی روی لپ‌تاپ

1. Python 3.10 یا بالاتر نصب باشد.
2. پوشه پروژه را باز کنید.
3. محیط مجازی بسازید:

```bash
python -m venv .venv
```

ویندوز:

```bash
.venv\Scripts\activate
```

4. وابستگی‌ها را نصب کنید:

```bash
pip install -r requirements.txt
```

5. فایل `.env.example` را به `.env` کپی کنید و توکن BotFather را فقط داخل آن قرار دهید.

6. اجرا:

```bash
python -m bot.main
```

## تنظیم کانال

ربات را در کانال `@Kazhwantravel` ادمین کنید. لازم نیست اجازه انتشار پست داشته باشد؛ دسترسی ادمین برای بررسی مطمئن عضویت لازم است.

## تنظیم گروه

ربات را به گروه اضافه و ادمین کنید. سپس در همان گروه فرمان زیر را بفرستید:

```text
/chatid
```

عدد نمایش‌داده‌شده را در مقدار `GROUP_CHAT_ID` فایل `.env` قرار دهید.

## نکات امنیتی

- فایل `.env` را در GitHub آپلود نکنید.
- توکن ربات را در پیام، گروه یا اسکرین‌شات منتشر نکنید.
- اگر توکن لو رفت، در BotFather آن را لغو و توکن جدید صادر کنید.

## مرحله بعد

بعد از تست ثبت عضویت، ماژول برنامه‌ها، ثبت‌نام، ظرفیت و لیست انتظار به همین پروژه اضافه می‌شود.


---

## استقرار روی Railway

این نسخه برای Railway آماده است. دستور اجرا:

```text
python -m bot.main
```

در تب **Variables** سرویس ربات این متغیرها را وارد کنید:

```text
BOT_TOKEN=توکن جدید ربات
CHANNEL_USERNAME=@Kazhwantravel
ADMIN_IDS=86054420
SUPPORT_CONTACT=@Kazhwantravel
GROUP_CHAT_ID=
```

برای دیتابیس دائمی، در Railway از مسیر **+ New → Database → PostgreSQL** یک دیتابیس اضافه کنید و متغیر `DATABASE_URL` آن را در اختیار سرویس ربات قرار دهید. کد، آدرس PostgreSQL Railway را خودکار به قالب asyncpg تبدیل می‌کند.

فایل `.env` را در GitHub آپلود نکنید.

---

## نسخه Join Request + Referral

در این نسخه، ربات می‌تواند درخواست عضویت گروه را دریافت کند، در پیام خصوصی اطلاعات عضو را بگیرد و پس از تکمیل فرم، Join Request را تأیید کند.

ترتیب فرم:

1. نام و نام خانوادگی
2. شماره تماس
3. شهر محل سکونت
4. نحوه آشنایی با کژوان
5. داشتن/نداشتن کد معرف
6. عضویت در کانال کژوان
7. پذیرش قوانین
8. ذخیره در PostgreSQL و تأیید خودکار درخواست عضویت

هر عضو یک کد معرف اختصاصی مثل `KZH-R000123` می‌گیرد. معرفی موفق در حال حاضر ۱۰ امتیاز برای معرف دارد.

### تنظیم ضروری Railway

`GROUP_CHAT_ID` باید شناسه عددی گروه اصلی باشد، مثل:

```text
GROUP_CHAT_ID=-1001234567890
```

برای گرفتن آن، ربات را در گروه ادمین کنید و `/chatid` را اجرا کنید.

ربات در گروه باید دسترسی مدیریت Join Request / Invite Users را داشته باشد تا بتواند درخواست عضویت را تأیید کند.

ربات همچنین باید در کانال `@Kazhwantravel` ادمین باشد تا بتواند عضویت کاربران را بررسی کند.

---

## v1.4 — پنل مدیریت و سفرها

### پنل مدیریت BTC

```text
/admin
/stats
/member <نام|شماره|کد عضویت|Telegram ID>
/inactive30
/inactive60
/topreferrals
/exportmembers
/exportinactive
/exportreferrals
/exportall
```

### گروه هر سفر

ربات را به گروه سفر اضافه کنید و مدیر داخل همان گروه بزند:

```text
/settrip
```

سپس نام، تاریخ شروع و تاریخ پایان را پاسخ دهد. بعد از ثبت سفر:

```text
/tripregister
```

دکمه ثبت سفر در پروفایل مسافر منتشر می‌شود.

دستورات مدیریتی سفر:

```text
/tripinfo
/tripparticipants
/exporttrip
/tripclose
/tripopen
/endtrip
/tripattend
/tripcancel
```

`/tripattend` و `/tripcancel` را می‌توان روی پیام یک مسافر Reply کرد یا کد عضویت/شماره او را بعد از دستور نوشت.

---

## v1.4.2 — Kazhwan vs BTC membership

`KZH-xxxxxx` is the permanent Kazhwan profile code. BTC is an optional separate membership with a `BTC-xxxxxx` code. Existing KZH codes are never replaced.

Trip scoring:
- Domestic one-day: 5 points
- Domestic multi-day: 15 points
- International: 100 points

Trip passengers only need a Kazhwan profile and membership in `@Kazhwantravel`; BTC membership is optional.

## v1.5 — ثبت دستی سفر و مسافر

در پنل خصوصی مدیر (`/admin → مدیریت سفرها`) می‌توان سفر جدیدی بدون گروه تلگرام ساخت و از داخل هر سفر «افزودن مسافر دستی» را انتخاب کرد. نام و نام خانوادگی الزامی و شماره موبایل اختیاری است. اگر پروفایل کژوان پیدا نشود، سابقه به‌عنوان مسافر موقت ذخیره می‌شود و امتیاز سفر تا زمان اتصال به پروفایل واقعی معوق می‌ماند.


## v1.6 — Trip data hygiene
Duplicate prevention, group-to-existing-trip linking, merge, archive/restore, and strict scoped command menus.
