# calendars-final — بازسازیِ کامل از PDFها

**تنها منبعِ معتبر در این پوشه، `PDF/` است.** در ۱۴۰۵/۰۹/۰۱ به درخواستِ کاربر همهٔ
خروجی‌ها و اسکریپت‌های قبلی (data، md، timeline، reports، i18n، viewer) حذف شدند و
همه‌چیز از صفر و **فقط از روی همین ۶۱ فایل PDF** بازتولید می‌شود.

## لولهٔ کار

```bash
py -3 scripts/extract_text.py            # هر PDF → extracted/text/<slug>.txt (+ _index.json)
py -3 scripts/parse_official.py          # تقویم‌های سالانه → extracted/json/<سال>.json
py -3 scripts/build_dataset.py           # دادهٔ تمیز، رویدادها، تعطیلات، وابستگیِ تقویمی
py -3 scripts/build_history.py           # هویت/وقوعِ سالانه + نسخهٔ هر سال → data/history/
py -3 scripts/extract_reference_docs.py  # ۳۶ سندِ مرجع → extracted/ref/<slug>.json
```

لولهٔ تولید فقط `PDF/` را می‌خواند؛ بازرسیِ جداگانهٔ `audit_events.py` پک‌های همراهِ برنامه را فقط برای مقایسه می‌خواند و چیزی از آن‌ها به داده اضافه نمی‌کند.

## خروجی‌ها

| مسیر | محتوا |
|---|---|
| `extracted/text/` | متنِ خامِ هر PDF، یک فایل جداگانه |
| `extracted/json/<سال>.json` | جدولِ روزبه‌روزِ تقویم‌های رسمی: شمسی، میلادی، قمری، روزِ هفته، عنوان، تعطیل، QC |
| `extracted/ref/` | استخراجِ ساختاریافتهٔ ۳۶ سندِ غیرسالانه (ویکی‌شیعه، مصوبه‌ها، فهرست‌ها) |
| `data/official-calendar-<سال>.json` | دادهٔ تمیزِ هر سال (بدونِ روزهای خالی) |
| `data/events.json` | ۱۷۸۹ رویدادِ یکتای خام با تاریخ‌های سه‌تقویمی (لایهٔ استخراج) |
| `data/events-master.json` | ۵۰۳ رویدادِ کاتالوگِ کانونی با شناسه، منبع و سطحِ اعتبار |
| `reports/dataset-report.md` | صحت‌سنجی، غلط‌های اصلاح‌شده، فایل‌های کنارگذاشته |
| `reports/holidays.md` | روزهای تعطیلِ هر سال با هر سه تاریخ |
| `reports/calendar-dependency.md` | شمسی/قمری/میلادی و روشِ تشخیص |

## سطحِ اعتبار (از `data-manifest.json` همان اجرا)

- **۰ رویداد `verified`**: در این دور هیچ رویدادی شاهدِ مستقلِ تأییدشده نداشت.
- **۳۸۸ `partially_verified`**: فقط یک ردیفِ جدولِ رسمیِ PDF دارند؛ PDF به‌تنهایی تأییدِ تاریخی نیست.
- **۱۲ `traditional`**: آیین/سنتی، بدونِ ادعای سندِ رسمی.
- **۱۰۳ `unverified`**: شاهدِ اولیه/صفحهٔ سند ندارند و در وب با نشانِ هشدار دیده می‌شوند.
- شاهدِ هر رویداد (`sourceRef`، `page`، `witnessText`، `reviewedAt`) داخل `data/events-master.json` است؛ جزئیات در `docs/audit.md` §۳.۳.

## صحت‌سنجی

برای هر ردیف سه بررسی مستقل انجام می‌شود:

1. **تاریخِ میلادی** باید با تبدیلِ نجومیِ تقویمِ جلالی از تاریخِ شمسی برابر باشد؛
2. **روزِ هفته** باید با `date(y,m,d).weekday()` بخواند؛
3. **توالیِ روزها** باید بدونِ پرش و تکرار باشد.

سال‌های ۱۳۸۲–۱۴۰۶ (۲۵ فایل) اسکن شدند؛ **۲۲ سال** کاملاً پاک‌اند. سه فایل لایهٔ
متنیِ سالم ندارند و بدونِ OCR قابلِ استخراج نیستند:

| سال | مشکل |
|---|---|
| ۱۳۹۳ | نگاشتِ ناقصِ فونت؛ متن به `ʆɳʈ…` تبدیل می‌شود |
| ۱۳۹۶ | ارقامِ فارسی جابه‌جا (۱۳۹۶→۳۱۶۹، ۱۴۳۸→۱۴۱۸) |
| ۱۴۰۲ | ارقام و ستون‌ها جابه‌جا (۱۴۰۲→۲۱۲۲، اسفند→آوریل) |

در ۱۳۹۵ و ۱۴۰۵ ستونِ میلادیِ چاپی در چند ردیف ماه را اشتباه چاپ کرده؛ مقدارِ چاپی در
`pdf_gregorian` نگه داشته و تاریخِ درست از شمسی محاسبه شده است
(`reports/dataset-report.md`).

## وابستگیِ تقویمی

ایران سه تقویمِ رسمی دارد: هجری شمسی (رویدادهای ملی)، هجری قمری (مناسبت‌های اسلامی)
و میلادی (روزهای جهانی/مسیحی). تشخیصِ خودکار بر پایهٔ ثابت‌بودنِ (ماه، روز) در
سال‌های مختلف است؛ جزئیات و نمونه‌ها در `reports/calendar-dependency.md`.

## سایت تقویم (وب)

```bash
py -3 scripts/build_web.py     # → web/index.html (تک‌فایل: HTML+CSS+JS+داده)
```

`web/index.html` تقویم ۱۳۰۰–۱۴۲۰ را نشان می‌دهد:

- **شبکهٔ ۱۲ماهه** برای هر سال (طولِ ماه اسفند از تبدیلِ جلالی محاسبه می‌شود؛ ۶ سال کبیسه در بازه).
- **رویدادهای رسمی** فقط در سالِ خودشان (از جدولِ همان PDF).
- **رویدادهای تکرارشونده** (شمسی/میلادی) در همهٔ سال‌ها؛ قمری فقط برای سال‌هایی که PDF دارند، چون تاریخ قمری از جدولِ همان سال می‌آید.
- **سطحِ اعتبار** هر ردیف (`verified`/`partially_verified`/`traditional`/`unverified`) و صفحهٔ PDF در وب و JSON نمایش داده می‌شود.
- **تبِ «تغییرات سال»**: افزوده/حذف‌شده/ویرایش‌شده نسبت به سال قبل (برای ۱۳۸۲–۱۴۰۶).
- **تبِ «منابع سال»** برای ۱۳۴۹–۱۳۷۳ از ویکی‌شیعه؛ ۱۳۷۴–۱۳۸۱ سند مرجعی ندارند.

پیش‌نیاز بازتولید: `extract_text.py` → `parse_official.py` → `build_dataset.py` → `extract_reference_docs.py` → `build_web.py`.

## سامانهٔ قاعده‌محور (هر سال، نه فقط داده)

`scripts/calendar_engine.py` تقویم را برای هر سال می‌سازد و `web/index.html` بازهٔ ۱۳۰۰–۱۴۲۰ را نشان می‌دهد:

- **۱۳۸۲–۱۴۰۶:** جدولِ رسمیِ همان PDF (بالاترین اعتبار).
- **بیرون از آن:** کاتالوگ `data/events-master.json` + قاعده‌ها — فرهنگی/مذهبی تکرار هر سال، تاریخی از سالِ رویداد، رسمیِ متغیر فقط از سالِ ورودش، و آیندهٔ ۱۴۰۷+ فقط با شاهدِ تداوم.
- **قمریِ بیرون از داده** با تقویمِ تربیعی و برچسبِ «تقریبی ±۱ روز».

```bash
py -3 scripts/calendar_engine.py --catalog            # ساخت/به‌روزرسانی کاتالوگ
py -3 scripts/calendar_engine.py --year 1410 --out out.json
```

قواعد کامل: `calendars-final/docs/calendar-rules.md`.

## یکپارچگی و صحت‌سنجی

- `scripts/check_consistency.py` → `reports/consistency.md`: تکرارها، عنوان‌های چسبیده و پوشش هر سال.
- `reports/audit/data-manifest.json` تنها منبعِ نسخه‌دارِ شمارش است؛ `release-summary.md`، `master-validation.md` و `consistency.md` از همین اجرا/کاتالوگ ساخته می‌شوند.
- `docs/verification.md`: جدول لنگرهای تأییدشده با منبع بیرونی (عاشورا ۱۳۴۹، فطر ۱۳۴۹، نفت ۱۳۲۹، ۲۲ بهمن ۱۳۵۷).
- `docs/calendar-rules.md`: قواعد R1–R8 و مدل داده.

## تاریخ رویداد و نسخه‌های تقویم

مدلِ سه‌لایه (هویتِ رویداد / وقوعِ سالانه / نسخهٔ تقویمِ هر سال) در
`data/history/` است:

| فایل | محتوا |
|---|---|
| `data/history/events.json` | هویت‌ها، عنوان‌های ثبت‌شده، تاریخِ اصل، نخستین مشاهده |
| `data/history/occurrences.json` | وقوعِ هر سال با تاریخِ سه‌تقویمی و شاهدِ صفحه/هش |
| `data/history/revisions/index.json` | فهرستِ نسخه‌های هر سال و وضعیتِ تأیید |
| `data/history/revisions/<id>.json` | ردیف‌های همان نسخه |
| `data/history/identity-reviews.json` | تصمیمِ پیشنهادی برای هویت‌های ردیفیِ مشکوک (نگاشت/حفظ بدونِ ادغام) |
| `data/history/approvals/identity-approvals.json` | دفترِ فقط-افزودنیِ تأییدِ امضاشده (Ed25519) با زنجیرهٔ هش |
| `data/history/approvals/trusted-keys.json` | کلیدهای عمومیِ موردِ اعتماد؛ کلیدِ خصوصی در `.approval-keys/` و commit نمی‌شود |
| `data/history/changelog.json` | تاریخچهٔ فقط-افزودنیِ تأیید/رد/اصلاح/بازگردانی |

**قاعده:** وقوع فقط از ردیفِ یک نسخهٔ **تأییدشده** ساخته می‌شود؛ هیچ رویدادی به
سالِ بی‌سند تعمیم داده نمی‌شود و خروجیِ قاعده‌محور وارد این بخش نمی‌شود.

```bash
py -3 scripts/build_history.py --force       # بازسازیِ مبنا از PDFهای رسمی
py -3 scripts/build_identity_reviews.py      # پیشنهادِ تصمیم‌ها؛ تأیید فقط از دفترِ امضاشده
py -3 scripts/approval_ledger.py keygen --owner "user:..."   # یک‌بار؛ کلیدِ خصوصی محلی می‌ماند
py -3 scripts/approval_ledger.py sign --all --private .approval-keys/approver.key \
    --approver "user:..." --channel chat --statement "متنِ تأیید"
py -3 scripts/approval_ledger.py verify    # زنجیره + امضا + بیانیه
py -3 scripts/ingest_pdf.py --pdf PDF/Calendar-1407.pdf   # پیش‌نویسِ امن (بدونِ تغییرِ داده)
py -3 scripts/ingest_pdf.py --pdf new.pdf --year 1407 --ocr
py -3 scripts/ingest_pdf.py --pdf scanned.pdf --year 1407 --ocr-text-dir ocr-pages/
py -3 scripts/review_changes.py list          # بازبینیِ پیش‌نویس‌ها
py -3 scripts/review_server.py --port 8765    # صفحهٔ بازبینی + بارگذاریِ PDF، فقط 127.0.0.1
py -3 scripts/audit_history.py                # گیت: شاهد، بازتولید، هشِ PDF، منشأِ تأیید
py -3 scripts/build_history_view.py           # → web/history.html + reports/history.md
```

- `docs/history-model.md`: سه موجودیت و تفکیکِ تاریخِ وقوع/ثبت/اصل.
- `docs/pdf-ingestion.md`: تشخیصِ سال، مکان‌یابِ صفحه/خط، محدودیتِ OCR و `-bbox`.
- `docs/revision-comparison.md`: دسته‌های ADDED/REMOVED/RENAMED/DATE_CHANGED/MODIFIED.
- `docs/review-workflow.md`: تصمیمِ انسانی، تأییدِ گروهی، ChangeLog، بازگردانی و بارگذاریِ PDF.
- `docs/evidence-contract.md`: قالبِ شاهد و سطوحِ اعتبار.
- `reports/history-identity-review.md`: شاهد/علتِ هر تصمیمِ هویتِ ردیفی.
- `reports/ocr-status.md`: اجرای واقعیِ OCR فارسی، اصلاحِ «صفحهٔ ۱۸» و محدودیتِ بازسازیِ جدول.
- `reports/identity-review-audit.md`: ممیزیِ مستقلِ ۲۲ تصمیم + امضا و شاهدِ ردیفی.
- `reports/statistics-audit.md` و `reports/web-consistency.md`: تطبیقِ آمار و خروجیِ وب با داده.
- `reports/year-coverage.md`: تکلیفِ صریحِ ۱۳۹۳/۱۳۹۶/۱۴۰۲ (منتشرنشده).

آمارِ فعلی: **۶۵۲ هویت** (۵۴۶ با وقوع، ۱۰۶ بدونِ سند)، **۴٬۵۴۳ وقوع**، **۲۲ نسخه**؛
هر ۲۲ نسخه `approval.kind = baseline` دارند (تأییدِ انسانیِ نسخه نیست) و هر ۲۲ هویتِ
ردیفیِ مشکوک تصمیمِ **امضاشده** دارند (۵ نگاشت + ۱۷ حفظِ ردیفِ چنده‌رویدادی).
تأییدِ تصمیم‌ها با کلیدِ Ed25519 و دفترِ زنجیره‌ای است، نه فیلدِ JSON یا رشتهٔ ثابتِ کد.

**تفکیکِ تأیید از ثبت:** این ۲۲ رکورد تأییدِ صریحِ کاربر در چت را ثبت می‌کنند؛
`recordedBy: agent:codebuff` و `attestation: chat-approval-recorded-by-agent` نشان
می‌دهند که عامل رکورد را نوشته و امضا کرده است. دفتر ۴۴ رکورد دارد: ۲۲ رکوردِ اول و
۲۲ رکوردِ اصلاحیِ پس از آن؛ برای هر هویت آخرین رکورد معتبر است و رکوردهای قبلی حذف
نشده‌اند. امضای Ed25519 یکپارچگیِ رکورد را
ثابت می‌کند، نه هویتِ شخصیِ انسان. `approvedAt` تاریخِ تأییدِ چت است (زمانِ دقیق
ثبت نشده) و با زمانِ امضای ماشینی اشتباه گرفته نمی‌شود.

**مرزِ امنیت:** این سازوکار از ویرایشِ JSON/داده در مخزن و CI محافظت می‌کند. کسی که
به فایلِ خصوصیِ `.approval-keys/approver.key` دسترسی دارد می‌تواند امضا بسازد؛ آن فایل
باید فقط در اختیارِ تأییدکننده و خارج از git بماند. برای تفکیکِ کاملِ انسان از ماشین،
امضا باید روی دستگاهِ تأییدکننده و با کلیدِ غیرقابلِ‌استخراج انجام شود.

سال‌های ۱۳۹۳، ۱۳۹۶ و ۱۴۰۲ منتشر نشده‌اند: ۱۳۹۳ اسکن است و OCR فارسی اجرا شد
(اطمینان ۵۳، صفر ردیفِ تاریخ‌دار)؛ ۱۳۹۶ عنوانِ خالی و ۱۴۰۲ ستونِ تاریخِ جابه‌جا دارد.
گزارشِ `reports/year-coverage.md` دلیل و اقدامِ هر سه را ثبت می‌کند.

## تعیین تقویم رویدادها

```bash
py -3 scripts/classify_calendars.py
```

خروجی: `data/calendar-classification.json` و `reports/calendar-comparison.md` (مقایسهٔ ۱۴۰۵/۱۴۰۶ و همهٔ سال‌ها).

## فایل یگانه و ساخت سال‌ها

```bash
py -3 scripts/verify_all.py            # گیتِ رسمی: ۲۳ مرحله + ۸۵ تست؛ CI در .github/workflows/gate.yml
```

`build_master.py` فقط ابزارِ بازسازیِ کاملِ اولیه است و **در گیت نیست**؛ اجرای دوبارهٔ آن
ممکن است کاتالوگ را تغییر دهد. منبعِ رسمی، `data/events-master.json` موجود است و شاهد/وضعیت
را `build_event_evidence.py` + `apply_evidence_status.py` (داخلِ `verify_all.py`) می‌سازند.
گزارش‌ها: `reports/master-validation.md` و `reports/year-build-validation.md`.

## پاک‌سازیِ املا

`calendar_engine.clean_title` پیش از ساختِ کاتالوگ/سال/سایت، عنوان‌ها را یکسان‌سازی می‌کند (ی/ک، الله، آیتالله، ة، فاصله‌ها و زوائدِ تاریخِ PDF). گزارش: `reports/master-validation.md`.
