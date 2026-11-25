---
name: data-provenance-audit
description: ممیزی منشأ، زنجیره شواهد، هش اسناد، وضعیت تأیید و سازگاری تاریخچه رویدادها؛ پیش از انتشار یا پس از تغییر داده و مدل تاریخچه استفاده شود.
---

# Data Provenance Audit

## هدف

برای هر ادعای داده‌ای مشخص کن از کجا آمده، به کدام سند و صفحه متصل است، چگونه استخراج شده، چه کسی و در چه فرایندی آن را بازبینی کرده و آیا زنجیره قابل بازسازی است.

## قواعد غیرقابل‌مذاکره

- داده بدون منشأ قابل ردیابی نباید به‌عنوان verified منتشر شود.
- `events-master.json`، خروجی موتور تقویم یا پک اپ به‌تنهایی شاهد وقوع نیستند.
- `official-pdf-row` شاهد حضور در PDF است، نه تأیید تاریخی مستقل.
- هش باید با فایل واقعی تطبیق داده شود؛ LFS pointer جایگزین بایت‌های PDF نیست.
- `reviewedAt`، `by` یا `approval.kind=human` به‌تنهایی اثبات اقدام انسانی نیستند.
- ثابت‌های کد و فایل JSON قابل ویرایش‌اند؛ آن‌ها را ریشه اعتماد مستقل تلقی نکن.
- گزارش سبز ساختاری به معنی صحت تاریخی تمام رویدادها نیست.
- این مهارت فقط ممیزی و گزارش می‌کند؛ داده را اصلاح یا وضعیت را ارتقا نمی‌دهد.

## دامنه ممیزی

ممیزی را در چهار سطح انجام بده:

1. **Document provenance:** فایل، SHA-256، نام، اندازه، تعداد صفحات، منبع و نسخه.
2. **Row provenance:** revision، صفحه، sourceRef، متن شاهد، method، locator/bbox در صورت وجود.
3. **Event provenance:** اتصال occurrence به event identity و شاهد همان سال؛ عدم تعمیم بین سال‌ها.
4. **Decision provenance:** بازبین، زمان، تصمیم، دلیل، change IDs، snapshot قبل/بعد و ChangeLog.

## گردش کار

1. `docs/evidence-contract.md`، `docs/history-model.md` و `docs/review-workflow.md` را بخوان.
2. ورودی‌های canonical و تاریخچه را شناسایی کن: `data/history/revisions/index.json`، `data/history/revisions/`، `events.json`، `occurrences.json`، `changelog.json` و `identity-reviews.json`.
3. زنجیره هر occurrence را تا revision، document، SHA-256 و صفحه دنبال کن.
4. وجود فایل PDF واقعی و تطابق هش را بررسی کن. اگر PDF در دسترس نیست یا فقط LFS pointer دیده می‌شود، این محدودیت را گزارش کن.
5. کامل بودن قرارداد شاهد را کنترل کن: kind، revisionId، documentId، hash، page، sourceRef، method و زمان استخراج. فیلد اختیاری ناموجود را با مقدار جعلی پر نکن.
6. وضعیت revision را کنترل کن: draft نباید منبع occurrence منتشرشده باشد؛ baseline را از human approval جدا نگه دار؛ superseded/rejected نباید active تلقی شوند.
7. ChangeLog را با revision و snapshotها تطبیق بده. ChangeLog باید append-only باشد و عملیات revert نیز یک رویداد جدید ایجاد کند.
8. تصمیم‌های هویتی را با `reports/history-identity-review.md` و `data/history/identity-reviews.json` تطبیق بده. تصمیم ثابت در اسکریپت را مدرک مستقل تأیید تلقی نکن.
9. گزارش‌های audit را با داده جاری مقایسه کن؛ شمارش‌های قدیمی یا گزارش‌هایی که از اجرای فعلی نیستند را به‌عنوان وضعیت جاری اعلام نکن.
10. گیت موجود را اجرا کن فقط اگر وظیفه و محیط اجازه اجرای آن را می‌دهد: `py -3 scripts/audit_history.py` و در ممیزی کامل `py -3 scripts/verify_all.py`. این اسکریپت‌ها ممکن است گزارش‌ها و خروجی‌های مشتق‌شده را بازتولید کنند؛ پیش از اجرا وضعیت working tree و اثر فایل‌ها را بررسی کن.
11. هر شکست را با شناسه issue، سطح severity و مسیر اصلاح پیشنهادی گزارش کن؛ فایل‌ها را خودکار تعمیر نکن.

## بررسی‌های کلیدی

- occurrence بدون شاهد
- revision بدون PDF یا با hash mismatch
- page خارج از محدوده سند
- sourceRef به فایل اشتباه یا به `events-master.json`
- شاهد OCR بدون منشأ OCR معتبر
- occurrence وابسته به revision غیر approved
- بیش از یک revision فعال برای یک سال
- approved بدون منشأ approval معتبر
- baseline اشتباهاً human نشان داده شده
- ChangeLog ناسازگار با snapshot
- identity review بدون شاهد صفحه/نسخه/علت
- اختلاف manifest و داده واقعی

## خروجی

گزارش ممیزی باید شامل زمان اجرا، commit/ref بررسی‌شده، دامنه، شمارش موارد بررسی‌شده، خطاها و هشدارها، هر مورد با `code/path/entityId/revisionId/evidence/impact/recommendation`، محدودیت‌های دسترسی و نتیجه انتشار باشد.

نتیجه فقط یکی از این‌ها باشد: `PASS_WITHIN_SCOPE`، `FAIL` یا `INCOMPLETE`. از واژه «کاملاً معتبر» استفاده نکن مگر دامنه و معیارها واقعاً چنین نتیجه‌ای را پشتیبانی کنند.

## آزمون‌ها

1. تغییر بایت PDF باید `REV_SHA_MISMATCH` ایجاد کند.
2. occurrence بدون evidence باید گیت را fail کند.
3. revision draft یا rejected نباید occurrence فعال بسازد.
4. baseline با `approval.kind=human` باید رد شود.
5. ChangeLog دستکاری‌شده یا snapshot ناسازگار باید خطا دهد.
6. sourceRef فاقد شماره صفحه/مربوط به فایل اشتباه باید شناسایی شود.
7. هویت دارای approval ثابت در کد نباید صرفاً به همین دلیل «تأیید مستقل» تلقی شود.
8. گزارش manifest با hash/count نادرست باید fail شود.
9. آزمون ممیزی باید روی داده موقت/fixture قابل اجرا باشد و فایل اصلی را تغییر ندهد.

## فایل‌ها و ابزارها

- `docs/evidence-contract.md`
- `docs/history-model.md`
- `docs/review-workflow.md`
- `scripts/history_store.py`
- `scripts/audit_history.py`
- `scripts/build_event_evidence.py`
- `scripts/build_data_manifest.py`
- `reports/history-audit.md` و `.json`
- `reports/history-identity-review.md`
- `tests/test_event_history.py`
- `tests/test_data_integrity.py`
