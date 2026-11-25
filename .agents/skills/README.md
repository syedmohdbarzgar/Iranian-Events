# Iranian-Events Agent Skills

این بسته ده مهارت تخصصی برای مخزن `syedmohdbarzgar/Iranian-Events` دارد.

## نصب

محتویات `.agents/skills/` را بدون تغییر نام پوشه‌ها به ریشه مخزن منتقل کنید. فایل `AGENTS.md` در ریشه، قواعد مشترک را نگه می‌دارد و این مهارت‌ها مرجع عملیاتی هر حوزه‌اند.

```text
AGENTS.md
.agents/skills/
├── historical-event-verification/SKILL.md
├── calendar-source-verification/SKILL.md
├── pdf-ocr-extraction/SKILL.md
├── calendar-diff-analysis/SKILL.md
├── data-provenance-audit/SKILL.md
├── human-review-management/SKILL.md
├── calendar-data-validation/SKILL.md
├── event-identity-and-history/SKILL.md
├── release-quality-audit/SKILL.md
└── repository-maintenance/SKILL.md
```

## فهرست مهارت‌ها

| مهارت | کاربرد |
|---|---|
| `historical-event-verification` | بررسی صحت تاریخی یک ادعا با منبع مستقل |
| `calendar-source-verification` | اصالت سند، هش، صفحه و تطبیق ردیف PDF |
| `pdf-ocr-extraction` | ورود امن PDF، OCR و اتصال نتیجه به صفحه |
| `calendar-diff-analysis` | مقایسه دو نسخه از یک سال و طبقه‌بندی تغییرات |
| `data-provenance-audit` | ممیزی زنجیرهٔ منشأ و شاهد در چهار لایه |
| `human-review-management` | تصمیم انسانی، تأیید امضاشده و rollback |
| `calendar-data-validation` | اعتبارسنجی ساختار، تاریخ، شناسه و شمارش |
| `event-identity-and-history` | هویت/وقوع/نسخه و تاریخچهٔ فقط-افزودنی |
| `release-quality-audit` | گیت انتشار، تست، گزارش و شرایط توقف |
| `repository-maintenance` | نگهداری امن git، ignore، وابستگی و گزارش |

## سازگاری با مخزن

این مهارت‌ها بر اساس مستندات و اسکریپت‌های موجود مانند `docs/evidence-contract.md`، `docs/history-model.md`، `docs/pdf-ingestion.md`، `docs/revision-comparison.md`، `docs/review-workflow.md`، `docs/audit.md` و `scripts/` نوشته شده‌اند.

`AGENTS.md` ریشه، قواعد الزامی و اولویت‌ها را تعریف می‌کند. این مهارت‌ها آن قواعد را تکرار نمی‌کنند؛ جزئیات اجرایی هر حوزه را با ارجاع به فایل‌های واقعی می‌دهند.

## مرز مهم

Skillها دستورالعمل اجرایی‌اند، نه کنترل امنیتی. جلوگیری از جعل تأیید انسانی، حفاظت از داده اصلی و گیت انتشار باید در کد و آزمون‌های CI نیز enforce شود. امضای Ed25519 یکپارچگی را ثابت می‌کند؛ اگر رکورد را عامل نوشته باشد، `recordedBy` و `attestation` باید این را صریح بگویند و امضا نباید امضای شخصیِ انسان معرفی شود.
