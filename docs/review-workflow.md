# بازبینی، تأیید و بازگردانیِ تغییرات

> پیاده‌سازی: `scripts/review_changes.py` · صفحهٔ محلی: `scripts/review_server.py`
> · گیت: `scripts/audit_history.py` · تاریخچه: `data/history/changelog.json`

## ۱. قاعدهٔ اصلی

هیچ تغییرِ خودکاری اعمال نمی‌شود. `ingest_pdf.py` فقط پیش‌نویس می‌سازد؛ ورود به
`data/history/` تنها با `finalize` و نامِ بررسی‌کننده ممکن است.

## ۲. چرخهٔ وضعیت

```
draft  ──decide/approve-all──▶  in-review  ──finalize──▶  applied
   │                                │
   └──────────reject────────────────┴──▶ rejected

approved ──revert──▶ superseded  +  نسخهٔ تازهٔ approved (revert)
```

- `draft`: پیش‌نویسِ استخراج؛ در تاریخچه اثری ندارد.
- `in-review`: برخی/همهٔ تصمیم‌ها ثبت شده.
- `applied`: نسخهٔ `approved` جایگزین شده و ChangeLog نوشته شده.
- `rejected`: کلِ پیش‌نویس رد شده؛ دادهٔ اصلی دست‌نخورده.
- نسخهٔ قدیمی پس از تأییدِ نسخهٔ تازه `superseded` می‌شود و در گیت می‌ماند.

## ۳. دستورها

```bash
# فهرستِ پیش‌نویس‌های در انتظار
py -3 scripts/review_changes.py list [--year 1405]

# نمایشِ کاملِ تغییرها
py -3 scripts/review_changes.py show --revision R-1405-8e32b520 [--all]

# تصمیم برای یک تغییر
py -3 scripts/review_changes.py decide --revision R-1405-8e32b520 \
    --change C-1405-0002 --action approve --by "نامِ مدیر" --note "…"

# ردِ یک تغییر
py -3 scripts/review_changes.py decide --revision R-1405-8e32b520 \
    --change C-1405-0001 --action reject --by "نامِ مدیر"

# اصلاحِ عنوان/تاریخ/تعطیلی و سپس تأیید
py -3 scripts/review_changes.py decide --revision R-1405-8e32b520 \
    --change C-1405-0004 --action edit --title "عنوانِ درست" \
    --solar 1405-01-02 --holiday true --description "توضیحِ همان سال" \
    --by "نامِ مدیر"

# تأییدِ گروهی (تصمیمِ مدیر برای همهٔ تغییرهای باقی‌مانده)
py -3 scripts/review_changes.py approve-all --revision R-1405-8e32b520 \
    --by "نامِ مدیر" --note "تأییدِ گروهیِ ویرایشِ ۱۴۰۵"

# اعمالِ نهایی
py -3 scripts/review_changes.py finalize --revision R-1405-8e32b520 \
    --by "نامِ مدیر" --note "پس از بررسیِ صفحه‌های ۳ و ۴"

# ردِ کلِ پیش‌نویس
py -3 scripts/review_changes.py reject --revision R-1405-8e32b520 \
    --by "نامِ مدیر" --note "استخراجِ نامعتبر"

# بازگردانیِ یک تأیید (کلِ سال) یا یک تغییر
py -3 scripts/review_changes.py revert --log L-00001 --by "نامِ مدیر"
py -3 scripts/review_changes.py revert --change C-1405-0002 --by "نامِ مدیر"

py -3 scripts/review_changes.py status
```

## ۴. پیش‌شرط‌های `finalize`

1. وضعیتِ پیش‌نویس `applied`/`reverted` نباشد.
2. برای **هر** تغییرِ `requiresHuman` تصمیمِ `approve` یا `reject` ثبت شده باشد؛
   در غیر این صورت خطا با فهرستِ تغییرهای بی‌تصمیم.
3. نسخهٔ فعالِ همان سال از زمانِ ساختِ پیش‌نویس عوض نشده باشد (وگرنه
   «پیش‌نویسِ کهنه» رد می‌شود و باید دوباره `ingest` شود).
4. ردیف‌های نتیجه سالِ درست، تاریخِ معتبر و عنوانِ غیرخالی داشته باشند.
5. `--by` غیرخالی باشد.

نتیجه:

- نسخهٔ تازه با همان سند/هش و ردیف‌های حل‌شده `approved` می‌شود (اگر همان PDFِ مبنا دوباره بازبینی شود، شناسهٔ `-review-NN` می‌گیرد تا نسخهٔ مبنا پاک نشود)؛
- نسخهٔ فعالِ پیشین `superseded` و `supersededBy` می‌شود؛
- وقوع‌ها/هویت‌ها از نسخه‌های approved بازتولید می‌شوند؛
- یک ورودیِ `APPROVE` با عکسِ کاملِ ردیف‌های پیش/پس در ChangeLog می‌نشیند.

## ۵. ChangeLog

```json
{
  "id": "L-00007",
  "at": "2026-11-24T…Z",
  "action": "APPROVE",
  "actor": "نامِ مدیر",
  "year": 1405,
  "revisionId": "R-1405-8e32b520",
  "supersedes": "R-1405-8e32b520",
  "changeIds": ["C-1405-0001", "…"],
  "decisions": {"C-1405-0001": "approve", "C-1405-0002": "reject"},
  "note": "…",
  "snapshotBefore": [ … ردیف‌های سال پیش از اعمال … ],
  "snapshotAfter":  [ … ردیف‌های سال پس از اعمال … ]
}
```

ورودیِ `REVERT` همان `snapshotBefore/snapshotAfter` را دارد و
`restoresLogId`/`restoresChange` را ثبت می‌کند. ChangeLog فقط افزودنی است؛
هیچ ورودی‌ای حذف یا بازنویسی نمی‌شود.

## ۶. صفحهٔ بازبینی

```bash
py -3 scripts/review_server.py --port 8765
```

- فقط `127.0.0.1` گوش می‌دهد؛ هیچ فایلی از بیرون سرو نمی‌شود.
- هر اجرا توکنِ تصادفی می‌سازد؛ POST بدونِ هدرِ `X-Review-Token` رد می‌شود.
- همان توابعِ `review_changes` را صدا می‌زند؛ منطقِ تأیید دوباره پیاده نشده.
- برای هر تغییر: پیش/پس، دسته، شباهت، هشدارِ تکراری/شکسته، دکمهٔ تأیید/رد/اصلاح،
  تأییدِ گروهی و اعمالِ نهایی. تصویرِ صفحه فقط اگر رندرکننده نصب باشد.

## ۷. بازگردانی

- `revert --log L-…` کلِ ردیف‌های سال را به `snapshotBefore` برمی‌گرداند.
- `revert --change C-…` فقط همان تغییر را وارونه می‌کند (ADDED حذف، REMOVED
  بازگشت، RENAMED/DATE_CHANGED/MODIFIED به مقدارِ پیشین).
- بازگردانی، نسخهٔ تازهٔ `approved` می‌سازد (`R-<سال>-revert-NN`) و نسخهٔ فعلی
  را `superseded` می‌کند؛ تاریخچه پاک نمی‌شود و خودِ بازگردانی هم قابلِ
  بازگردانی است.
- اگر سندِ PDF در دسترس نباشد، بازگردانی همچنان با همان فرادادهٔ سند انجام
  می‌شود و گیت هشدارِ `REV_PDF_MISSING` می‌دهد.

## ۸. گیتِ انتشار

```bash
py -3 scripts/audit_history.py
```

خطا (خروجِ ۱) یعنی انتشار متوقف است: وقوعِ بی‌شاهد، نسخهٔ تأییدنشده، هشِ ناهمخوان،
وقوعِ دست‌کاری‌شده، تاریخِ نامعتبر یا ChangeLogِ ناسازگار. گزارش:
`reports/history-audit.md` و `.json`.

## ۹. نگاشت به معیارِ پذیرش

| خواسته | پیاده‌سازی |
|---|---|
| نمایشِ قبل/بعد و صفحه | `show` / صفحهٔ بازبینی |
| تأیید، رد، اصلاحِ هر تغییر | `decide` |
| تأییدِ گروهی با تصمیمِ مدیر | `approve-all` + `--by`/`--note` |
| اعمال فقط پس از تأیید | `finalize` + پیش‌شرطِ تصمیمِ کامل |
| ثبتِ منبع/نسخه/زمان/نتیجه | ChangeLog + `revision.review` |
| بازگردانیِ هر تغییر | `revert --change` |
| تاریخچهٔ کامل | `data/history/changelog.json` (فقط افزودنی) |
