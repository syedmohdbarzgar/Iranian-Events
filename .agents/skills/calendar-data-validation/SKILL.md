---
name: calendar-data-validation
description: اعتبارسنجی ساختاری و سازگاری داده‌های تقویم، تاریخ‌های سه‌تقویمی، شناسه‌ها، شمارش‌ها و خروجی مصرف‌کنندگان؛ پس از هر تغییر داده یا پیش از انتشار استفاده شود.
---

# Calendar Data Validation

## هدف

ساختار داده، سازگاری ارجاع‌ها، صحت تبدیل‌های تقویمی و هم‌خوانی شمارش‌ها را بسنج. این مهارت «درستی تاریخی» را اثبات نمی‌کند؛ فقط نشان می‌دهد داده از نظر ساختاری و ریاضی معتبر است و ادعای تاریخی همچنان به شاهد مستقل نیاز دارد.

## قواعد

- اعتبارسنجی ساختاری را با تأیید تاریخی اشتباه نگیر.
- تاریخ را از روی شباهت عنوان یا سال‌های دیگر حدس نزن.
- هیچ خطا یا هشدار را برای سبز شدن گیت سرکوب نکن.
- داده اصلی را خودکار اصلاح نکن؛ پیشنهاد اصلاح باید به شاهد و صفحه متصل باشد.
- `data/events-master.json` و خروجی وب، منبع حقیقتِ تاریخی نیستند.
- manifest و گزارش‌های ثابت باید از همان اجرای داده ساخته شوند، نه از اجرای قدیمی.
- شمارش‌ها باید از داده جاری استخراج شوند؛ عدد دستی در گزارش ننویس.
- وضعیت `baseline` را با تأیید انسانی یکی نگیر.
- اعتبارسنجی باید روی fixture موقت قابل اجرا باشد و داده واقعی را تغییر ندهد.

## ورودی‌ها

- `data/events-master.json`
- `data/history/events.json`، `occurrences.json`، `revisions/index.json`
- `data/history/revisions/<id>.json`
- `data/years/` و `web/index.html` در صورت وجود
- `reports/audit/data-manifest.json`
- فایل‌های `reports/*-audit.json` و گزارش‌های متناظر

## گردش کار

1. `docs/evidence-contract.md`، `docs/history-model.md`، `docs/calendar-rules.md` و `docs/audit.md` را بخوان.
2. وضعیت working tree را ثبت کن؛ اجرای گیت ممکن است گزارش‌های مشتق‌شده را بازتولید کند.
3. اعتبارسنجی پایه را اجرا کن:

   ```bash
   py -3 scripts/check_consistency.py
   py -3 scripts/audit_master.py
   py -3 scripts/audit_catalog_duplicates.py
   py -3 scripts/audit_unmatched.py
   ```

4. اعتبارسنجی تاریخ و موتور تقویم را اجرا کن:

   ```bash
   py -3 scripts/audit_calendar.py
   py -3 scripts/build_years.py
   ```

5. هم‌خوانی آمار، پوشش سال و وب را بسنج:

   ```bash
   py -3 scripts/audit_statistics.py
   py -3 scripts/audit_year_coverage.py
   py -3 scripts/audit_web_consistency.py
   ```

6. برای هر تاریخ شمسی، این سه بررسی را جدا نگه دار:
   - تبدیل میلادی با تبدیل جلالی پروژه
   - روز هفته با تاریخ میلادی
   - توالی روزهای سال بدون پرش/تکرار
7. ارجاع‌ها را کنترل کن: هر occurrence باید به event موجود و revision/شاهد موجود اشاره کند. شناسه تکراری، event بدون منبع، صفحه خارج از محدوده و revision ناموجود خطا هستند.
8. تفکیک تاریخ‌ها را بررسی کن: `occurrenceDate`، `firstSeen`، `reviewedAt`، `publishedAt` و `recordedAt` نباید به‌جای هم استفاده شوند.
9. تفاوت شمارش manifest با داده واقعی، اختلاف JSON و وب، و گزارش قدیمی‌تر از داده را خطا/هشدار ثبت کن.
10. خروجی هر مرحله را با exit code ثبت کن. اگر یک مرحله شکست خورد، مراحل بعدی را «سبز» اعلام نکن؛ ابتدا علت را گزارش کن.
11. هیچ اصلاح خودکاری روی canonical انجام نده. پیشنهاد را با فایل، رکورد، شاهد و دلیل به بازبینی انسانی بده.

## بررسی‌های کلیدی

- شناسه تکراری یا خالی
- تاریخ شمسی نامعتبر (ماه/روز خارج از محدوده، اسفند نامعتبر)
- اختلاف تاریخ شمسی و میلادی
- اختلاف روز هفته
- پرش یا تکرار روز در جدول سال
- occurrence بدون event
- event بدون occurrence در حالی که نباید چنین باشد
- revision فعال بیشتر از یکی برای یک سال
- revision draft/rejected به‌عنوان منبع occurrence
- صفحه صفر/منفی/بیشتر از تعداد صفحات
- sourceRef ناقص یا به فایل اشتباه
- تفاوت شمارش manifest با فایل‌های داده
- تفاوت خروجی وب با JSON سال
- گزارش تولیدشده با timestamp قدیمی‌تر از ورودی

## خروجی

گزارش باید شامل این موارد باشد:

- زمان اجرا و commit/ref بررسی‌شده
- دامنه و فایل‌های ورودی
- شمارش رکوردها و ارجاع‌های بررسی‌شده
- خطاها و هشدارها با `code`، `path`، `entityId`، `severity` و `message`
- تفکیک خطای ساختاری از ابهام تاریخی
- گزارش‌های بازتولیدشده و تغییرات آن‌ها
- محدودیت‌ها و مراحلی که اجرا نشدند
- نتیجه: `PASS_WITHIN_SCOPE`، `FAIL` یا `INCOMPLETE`

## آزمون‌ها

1. تاریخ شمسی نامعتبر باید رد شود.
2. اختلاف تاریخ شمسی/میلادی باید خطا بدهد.
3. روز هفته نادرست باید شناسایی شود.
4. شناسه تکراری باید خطا بدهد.
5. occurrence با event ناموجود باید رد شود.
6. occurrence بدون شاهد باید خطا بدهد.
7. revision غیر approved نباید occurrence فعال بسازد.
8. شمارش manifest نادرست باید گیت را قرمز کند.
9. اختلاف JSON و وب باید شناسایی شود.
10. آزمون‌ها باید روی TempStore/fixture اجرا شوند و فایل اصلی را تغییر ندهند.

## معیار پذیرش

- ساختار و ارجاع‌های داده بدون خطای بحرانی باشند.
- شمارش‌ها از داده جاری آمده باشند.
- خطاها پنهان نشده باشند.
- هیچ تاریخ یا هویتی حدس زده نشده باشد.
- نتیجه فقط در محدودهٔ بررسی‌شده اعلام شود.

## فایل‌ها و ابزارها

- `docs/calendar-rules.md`
- `docs/evidence-contract.md`
- `docs/history-model.md`
- `docs/audit.md`
- `scripts/check_consistency.py`
- `scripts/audit_master.py`
- `scripts/audit_catalog_duplicates.py`
- `scripts/audit_unmatched.py`
- `scripts/audit_calendar.py`
- `scripts/build_years.py`
- `scripts/audit_statistics.py`
- `scripts/audit_year_coverage.py`
- `scripts/audit_web_consistency.py`
- `reports/audit/data-manifest.json`
- `tests/test_data_integrity.py`
- `tests/test_calendar_engine.py`
