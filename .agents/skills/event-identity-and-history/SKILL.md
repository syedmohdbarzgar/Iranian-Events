---
name: event-identity-and-history
description: مدیریت هویت رویداد، وقوع سالانه، نسخه‌های تقویم، تصمیم‌های ادغام/نگاشت و تاریخچه فقط-افزودنی؛ هنگام تغییر مدل تاریخ، حل هویت‌های مشکوک یا بازگردانی نسخه استفاده شود.
---

# Event Identity And History

## هدف

هویت تاریخی رویداد را از وقوع سالانه و از نسخهٔ تقویم جدا نگه دار. یک عنوان مشابه، یک تاریخ مشابه یا یک ردیف PDF به‌تنهایی هویت را اثبات نمی‌کند. این مهارت تغییرات را قابل‌ردیابی، قابل‌بازگردانی و قابل‌ممیزی نگه می‌دارد.

## مدل سه‌لایه

| لایه | فایل | معنا |
|---|---|---|
| هویت | `data/history/events.json` | رویداد چیست و چه عنوان‌هایی دارد |
| وقوع | `data/history/occurrences.json` | در کدام سال، با کدام تاریخ و کدام شاهد |
| نسخه | `data/history/revisions/` | جدول همان سال در یک سند مشخص |

`data/history/identity-reviews.json` تصمیم پیشنهادی برای هویت‌های ردیفیِ مشکوک است و `data/history/approvals/` دفتر تأیید امضاشده است.

## قواعد غیرقابل‌مذاکره

- هویت را از شباهت عنوان به‌تنهایی نساز و ادغام نکن.
- تاریخ یک سال را به سال دیگر تعمیم نده.
- ردیف چسبیده/شکسته/تکراری را بدون شاهد و تصمیم انسانی به چند رویداد نشکن.
- `UNCHANGED` می‌تواند خودکار بماند؛ هر تغییر هویت/تاریخ نیازمند تصمیم است.
- حذف از یک نسخه به معنای عدم وقوع تاریخی نیست؛ سابقه را حذف نکن.
- `baseline` تأیید انسانی نیست.
- `approval.kind=human` یا `reviewedAt` به‌تنهایی مدرک انسان نیست.
- تأیید فقط از دفتر امضاشده و بیانیهٔ کانونی معتبر می‌آید.
- `recordedBy` و `attestation` باید صادقانه بگویند رکورد را چه کسی ثبت کرده است.
- تاریخچه فقط-افزودنی است؛ rollback یک نسخه/رکورد جدید می‌سازد و قبلی را حذف نمی‌کند.
- داده اصلی را مستقیم ویرایش نکن.

## ورودی‌ها

- `data/history/events.json`
- `data/history/occurrences.json`
- `data/history/revisions/index.json`
- `data/history/identity-reviews.json`
- `data/history/changelog.json`
- `data/history/approvals/identity-approvals.json` و `trusted-keys.json`
- گزارش `reports/history-audit.md` و `reports/history-identity-review.md`

## گردش کار

1. `docs/history-model.md`، `docs/review-workflow.md`، `docs/revision-comparison.md` و `docs/evidence-contract.md` را بخوان.
2. وضعیت فعلی را با `git status` و گزارش‌های audit ثبت کن.
3. برای هر هویت مشکوک، شاهد ردیفی (revision، صفحه، عنوان، سال)، اجزای کاتالوگی و علت را جمع کن.
4. پیشنهاد تصمیم را فقط با `build_identity_reviews.py` بساز:

   ```bash
   py -3 scripts/build_identity_reviews.py
   ```

5. تصمیم را بدون تأیید انسانی اعمال نکن. تأیید باید صریح، مشخص و به همان بیانیه متصل باشد. اگر انسان تصمیم نداده است، وضعیت `needs_review` را نگه دار.
6. تأیید/پس‌گرفتن را فقط از مسیر امضاشده انجام بده:

   ```bash
   py -3 scripts/approval_ledger.py sign --all --private .approval-keys/approver.key \
       --approver "user:..." --channel chat --approved-at <زمان تأیید> \
       --recorded-by agent:codebuff --attestation chat-approval-recorded-by-agent \
       --statement "<متن تأیید>"
   py -3 scripts/approval_ledger.py verify
   ```

7. پس از تغییر، داده مشتق را بازتولید کن:

   ```bash
   py -3 scripts/build_identity_reviews.py
   py -3 scripts/build_history_view.py
   ```

8. ممیزی هویت و تاریخچه را اجرا کن:

   ```bash
   py -3 scripts/audit_identity_reviews.py
   py -3 scripts/audit_history.py
   ```

9. برای rollback، از مسیر `review_changes.py revert` طبق `docs/review-workflow.md` استفاده کن؛ ChangeLog و snapshot جدید باید باقی بمانند.
10. اگر تصمیم یا شاهد کافی نیست، نتیجه را «نیازمند بررسی» گزارش کن، نه تأیید و نه رد.

## تصمیم‌های هویت

- `map`: ردیف به یک هویت کاتالوگی موجود نگاشت می‌شود؛ مقصد و شاهد باید صریح باشند.
- `keep-merged-row`: ردیف PDF چند رویداد را در یک سطر چاپ کرده؛ هیچ ادغام خودکاری انجام نمی‌شود و اجزا/صفحه ثبت می‌شوند.
- `keep-garbled-row`: عنوان مخدوش است و نگاشت مطمئن ندارد؛ باید برای بازبینی بماند.

هیچ تصمیم جدیدی بدون تعریف در مدل داده و گیت نساز.

## خروجی

- هویت/وقوع‌های تغییریافته با شناسه
- revision و صفحهٔ شاهد
- تصمیم، دلیل، اجزای کاتالوگی و مقصد
- رکورد دفتر با `ledgerSeq`، `recordHash`، `keyId` و `recordedBy`
- ChangeLog و snapshot قبل/بعد
- نتیجهٔ audit و موارد باقی‌مانده
- صریح‌ترین محدودیت: آیا تأیید مستقل انسانی هست یا فقط ثبتِ عامل از تأیید چت

## آزمون‌ها

1. تصمیم بدون امضا باید `REVIEW_APPROVAL_MISSING` بدهد.
2. تغییر بیانیه پس از امضا باید `APPROVAL_STATEMENT_MISMATCH` بدهد.
3. تغییر `recordedBy`/`attestation` باید امضا را باطل کند.
4. کلید غیرمورداعتماد باید رد شود.
5. دست‌کاری زنجیرهٔ دفتر باید شناسایی شود.
6. `map` فقط با مقصد صریح اعمال شود.
7. `keep-merged-row` هیچ ادغام خودکاری انجام ندهد.
8. تصمیم خاموش‌شده هویت ردیفی را دوباره `needsReview` کند.
9. rollback تاریخچه را حذف نکند.
10. آزمون‌ها روی TempStore اجرا شوند.

## معیار پذیرش

- هر تصمیم به شاهد صفحه/نسخه و علت متصل باشد.
- هیچ تأیید جعلی یا بدون امضا اثر نداشته باشد.
- تاریخچه و رکوردهای قبلی حفظ شوند.
- منشأ ثبت صادقانه گزارش شود.
- گیت تاریخ و ممیزی هویت سبز باشد.

## فایل‌ها و ابزارها

- `docs/history-model.md`
- `docs/review-workflow.md`
- `docs/revision-comparison.md`
- `scripts/history_store.py`
- `scripts/build_history.py`
- `scripts/build_identity_reviews.py`
- `scripts/approval_ledger.py`
- `scripts/build_history_view.py`
- `scripts/review_changes.py`
- `scripts/audit_identity_reviews.py`
- `scripts/audit_history.py`
- `tests/test_event_history.py`
