---
name: repository-maintenance
description: نگهداری امن مخزن، مدیریت فایل‌های تولیدشده، ignoreها، وابستگی‌ها، commit و هم‌گامی گزارش‌ها؛ برای هر تغییر ساختاری یا پیش از تحویل استفاده شود.
---

# Repository Maintenance

## هدف

مخزن را قابل‌بازتولید و قابل‌ممیزی نگه دار: فایل‌های منبع از خروجی‌های تولیدشده جدا باشند، secret وارد نشود، تاریخچه بازنویسی نشود و تغییرات فقط مرتبط با وظیفه باشند.

## قواعد

- هیچ کلید خصوصی، رمز، توکن یا فایل محیطی محرمانه commit نشود.
- `.approval-keys/`، `tools/ocr/node_modules/`، `__pycache__/` و cacheها نباید stage شوند.
- تاریخچه Git را بازنویسی نکن (بدون force-push، rebase مخرب یا حذف commit) مگر کاربر صریحاً بخواهد.
- فایل داده اصلی را با ادیت دستی بازنویسی نکن؛ از اسکریپت و مسیر نسخه‌بندی استفاده کن.
- گزارش تولیدشده را با منبعش هم‌گام کن؛ گزارش قدیمی را به‌عنوان وضعیت جاری نگه ندار.
- وابستگی‌ها را با نسخهٔ قفل‌شده نگه دار (`requirements.txt`، `tools/ocr/package.json`).
- lockfile یا پوشهٔ وابستگی را برای «تمیزکاری» حذف نکن.
- logهای محلی، خروجی تست و فایل‌های موقت را وارد commit نکن.
- تغییر نامرتبط را در commit نیاور.
- PDFهای بزرگ/ LFS را با بایت واقعی و هش بررسی کن؛ pointer را جای سند نگذار.
- commit پیام انگلیسی و مشخص داشته باشد؛ push فقط با مجوز کاربر.

## ورودی‌ها

- `git status`، `git diff`، `git log`
- `.gitignore`
- `requirements.txt`
- `tools/ocr/package.json`
- `.github/workflows/gate.yml`
- `scripts/sync_report_versions.py`

## گردش کار

1. وضعیت را بررسی کن:

   ```bash
   git status --short
   git diff --stat
   git log -5 --oneline
   ```

2. فایل‌های ناخواسته را پیدا کن:

   ```bash
   git status --short --ignored | head -50
   ```

3. مطمئن شو مسیرهای حساس ignore هستند:

   ```bash
   git check-ignore -v .approval-keys/approver.key tools/ocr/node_modules
   ```

4. تفاوت‌ها را بخوان و تغییرات نامرتبط را کنار بگذار. فایل تولیدشده را فقط اگر بخشی از وظیفه است stage کن.
5. پیش از commit، secret scan و whitespace check انجام بده:

   ```bash
   git diff --cached --name-only
   git diff --cached --check
   ```

6. اگر داده/گزارش تغییر کرده، هم‌گام‌سازی و گیت مرتبط را اجرا کن:

   ```bash
   py -3 scripts/sync_report_versions.py
   py -3 scripts/verify_all.py
   ```

7. فایل‌های مرتبط را stage کن؛ سپس `git diff --cached --stat` را بازبینی کن.
8. commit را با HEREDOC و پیام انگلیسی بنویس؛ تغییرات حساس را در پیام فاش نکن.
9. push فقط در صورت مجوز؛ بعد از push، `HEAD` و `origin/main` را مقایسه کن.
10. اگر فایل تولیدشده پس از commit دوباره تغییر کرد، علتش را پیدا کن؛ commit خالی یا amend پنهانی نساز.

## بررسی‌های کلیدی

- secret در stage
- کلید خصوصی/keystore
- node_modules یا cache
- فایل موقت و log
- تغییر نامرتبط در data/reports
- گزارش قدیمی‌تر از داده
- وابستگی بدون نسخهٔ قفل‌شده
- LFS pointer اشتباه
- فایل حذف‌شده بدون دلیل
- تاریخچهٔ بازنویسی‌شده
- push بدون مجوز

## خروجی

- فهرست فایل‌های تغییرکرده و دلیل
- فایل‌های نادیده‌گرفته‌شده/حساس
- نتیجهٔ بررسی secret و whitespace
- نتیجهٔ گیت (در صورت اجرا)
- commit hash و وضعیت push
- موارد باقی‌مانده یا مشکوک

## آزمون‌ها

1. `.approval-keys/approver.key` باید ignore باشد.
2. `tools/ocr/node_modules` باید ignore باشد.
3. `git diff --cached --check` نباید خطای whitespace بدهد.
4. هیچ فایل `.env` یا کلید در stage نباشد.
5. حذف تست/اعتبارسنجی برای سبز شدن ممنوع باشد.
6. گزارش‌های تولیدشده با منبع هم‌گام باشند.
7. commit فقط فایل‌های مرتبط را شامل شود.
8. push فقط با مجوز و با تأیید `HEAD == origin/main`.

## معیار پذیرش

- مخزن بدون secret و فایل زائد commit شود.
- تاریخچه و داده اصلی حفظ شوند.
- وابستگی‌ها قابل بازتولید بمانند.
- گزارش‌ها با داده جاری بخوانند.
- commit و push قابل ردیابی و محدود به وظیفه باشند.

## فایل‌ها و ابزارها

- `.gitignore`
- `requirements.txt`
- `tools/ocr/package.json`
- `.github/workflows/gate.yml`
- `scripts/sync_report_versions.py`
- `scripts/verify_all.py`
- `README.md`
- `docs/audit.md`
