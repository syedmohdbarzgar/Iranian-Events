# مدلِ تاریخِ رویداد — هویت، وقوع، نسخه

> پیاده‌سازی: `scripts/history_store.py` · ساخت: `scripts/build_history.py` ·
> گیت: `scripts/audit_history.py` · داده: `data/history/`
>
> این سند فاز ۱ چک‌لیست را تعریف می‌کند: تفکیکِ هویتِ رویداد از وقوعِ سالانه و
> از نسخهٔ تقویمِ هر سال، بدونِ تعمیمِ خودکار بین سال‌ها.

## ۱. سه موجودیت

### `Event` — هویتِ اصلی

| فیلد | معنا |
|---|---|
| `id` | `E####` برای هویتِ کاتالوگ · `S########` برای هویتِ ساخته‌شده از یک ردیفِ PDF |
| `canonicalTitle` | عنوانِ مرجع (از کاتالوگ؛ برای هویتِ ردیف، پاک‌شده‌ترین عنوانِ دیده‌شده) |
| `aliases` | همهٔ عنوان‌هایی که در ردیف‌های تأییدشده برای همین هویت دیده شده‌اند |
| `identityKind` | `catalog` (هویتِ مستقل) یا `row` (فقط از ردیفِ تقویم شناخته شده) |
| `category` / `calendar` | دسته و تقویمِ مبنا (`solar`/`lunar`/`gregorian`/`unresolved`) |
| `established` | تاریخِ اصل/اعلام/تصویب — **جدا** از تاریخِ وقوع و از نخستین مشاهده |
| `firstObservedYear` | نخستین سالی که رویداد در یک سندِ تأییدشده دیده شده |
| `firstRecordedDate` | تاریخِ شمسی/میلادی و صفحهٔ همان نخستین مشاهده |
| `observedYears` | سال‌هایی که برای هرکدام شاهدِ مستقل وجود دارد |
| `occurrenceCount` | شمارِ وقوع‌های witnessed |
| `verificationStatus` | `verified` · `partially_verified` · `traditional` · `unverified` |
| `needsReview` | هویتِ ردیفیِ بلند/مشترک که **هنوز** تصمیمِ مستند ندارد |
| `review` | تصمیمِ ثبت‌شده برای هویتِ ردیفی: `keep-merged-row`/`keep-garbled-row` + علت + شاهد + اجزا |

`established.kind` یکی از `tradition`، `established`، `event`، `first-seen`،
`unrecorded` است. برای هویتِ ردیفی همیشه `unrecorded` است؛ یعنی «سندِ اصل در
دست نیست» و هیچ تاریخی از خودمان ساخته نمی‌شود.

### `EventOccurrence` — وقوع در یک سال

| فیلد | معنا |
|---|---|
| `id` | `O-<سال>-<هویت>-<ماه‌روز>-<شماره>` (قطعی و بازتولیدپذیر) |
| `eventId` / `year` | هویت و سالِ وقوع |
| `date` | `solar`, `gregorian`, `lunar` و `approxLunar` |
| `observedTitle` | **عنوانِ چاپ‌شده در همان سند و همان سال** (بدونِ بازنویسی) |
| `description` | توضیحِ همان سال (اختیاری؛ در صورت وجودِ متنِ توضیحی) |
| `holiday` | وضعیتِ تعطیلی در همان ردیف |
| `match` | `exact`/`alias`/`contained`/`fuzzy`/`row` + `sharedRow` + اطمینان |
| `verification.status` | اعتبارِ هویت (از کاتالوگ) |
| `verification.dateCertainty` | `unconfirmed` برای هر ردیفِ PDF (PDF به‌تنهایی تأییدِ تاریخی نیست) |
| `evidence` | نسخه، سند، هش، صفحه، مکان‌یاب، روش و زمانِ استخراج |

### `CalendarRevision` — نسخهٔ تقویمِ یک سال

| فیلد | معنا |
|---|---|
| `id` | `R-<سال>-<هشت نویسهٔ هش PDF>`؛ نسخه‌های بازگردانی `R-<سال>-revert-NN` |
| `year` | سالِ تقویم |
| `document` | فایل، SHA-256، حجم، شمارِ صفحه |
| `extraction` | روش (`text-layer`/`ocr`/`mixed`/`manual-revert`)، ابزار، زمان، شمارِ ردیف، صفحه‌های OCR، مکان‌یاب |
| `state` | `draft` · `approved` · `superseded` · `rejected` |
| `approval` | منشأِ تأیید: `{kind: baseline|human, method, by, at, note}` — مبنا هرگز «تأییدِ انسانی» نیست |
| `approvedBy` / `approvedAt` | نام و زمانِ ثبت؛ برای مبنا `baseline:parse_official` |
| `supersedes` / `supersededBy` | زنجیرهٔ نسخه‌ها |
| `review` | شمارشِ تصمیم‌های تأیید/رد/اصلاح |

ردیف‌های هر نسخه در `data/history/revisions/<revisionId>.json` و فهرست در
`data/history/revisions/index.json` است.

## ۲. سه تاریخ که نباید قاطی شوند

| تاریخ | کجاست | مثال |
|---|---|---|
| تاریخِ **وقوع** در یک سال | `occurrence.date` | عاشورا ۱۴۰۵ = ۵ محرم ۱۴۴۷ / ۴ مرداد ۱۴۰۵ |
| تاریخِ **نخستین مشاهده در منابعِ پروژه** | `event.firstObservedYear` + `firstRecordedDate` | «نخستین ثبت: ۶ مهر ۱۳۹۷» |
| تاریخِ **اصل/اعلام/تصویب** | `event.established` | ملی‌شدن نفت ۲۹ اسفند ۱۳۲۹ |

`firstObservedYear` از وقوع‌ها محاسبه می‌شود، نه از `first_year` کاتالوگ و نه از
`origin`. اگر سالِ قدیمی‌تری تأیید شود، خودکار پایین می‌آید؛ اگر سندی نباشد،
`null` می‌ماند.

## ۲٫۱. منشأِ تأیید: مبنا در برابر انسان

هر نسخهٔ `approved` باید `approval.kind` داشته باشد:

- `baseline`: ساخته‌شده از `data/official-calendar-*.json`؛ یعنی **واردکردنِ
  خودکار**، نه تأییدِ انسانی. `approvedBy` همان `baseline:parse_official` است.
- `human`: تأییدِ `review_changes.py finalize` یا بازگردانیِ انسانی؛ `by` نامِ
  واقعی و `method` یکی از `review`/`revert` است.

گیت با `REV_APPROVAL_MISSING`، `REV_BASELINE_ACTOR`، `REV_BASELINE_SOURCE`،
`REV_HUMAN_ACTOR` و `REV_HUMAN_METHOD` نمی‌گذارد مبنا خود را انسانی جا بزند.
صفحهٔ تاریخ و گزارشِ گیت همین تفاوت را نشان می‌دهند؛ آمارِ امروز: ۲۲ نسخهٔ مبنا
و ۰ نسخهٔ تأییدِ انسانی.

## ۲٫۲. هویت‌های ردیفیِ بازبینی‌شده

`data/history/identity-reviews.json` تصمیم‌های ثبت‌شده برای هویت‌های `S…` است:

- `map`: فقط وقتی یک ردیف با یک رویدادِ کاتالوگی عنوان/تاریخِ یکسان دارد؛
  مقصد صریح است و ردیفِ اصلی به‌عنوان شاهد/alias حفظ می‌شود.
- `keep-merged-row`: ردیفِ PDF چند رویدادِ متفاوت را در یک سطر چاپ کرده؛ هیچ
  ادغامی انجام نمی‌شود، اجزای کاتالوگی و صفحه/نسخه ثبت می‌شوند و
  `needsReview` فقط پس از همین تصمیم `false` می‌شود.
- `keep-garbled-row`: یک رویداد با عنوانِ مخدوش که نگاشتِ مطمئن ندارد.

هر ورودی `reason`، `evidence[{revisionId,page,year,observedTitle}]`،
`reviewedBy`، `reviewedAt`، `active` و در صورتِ تأیید `approval` دارد. `approval`
نتیجهٔ یک **امضای Ed25519** روی بیانیهٔ کانونیِ تصمیم است، نه یک فیلدِ قابلِ
نوشتن: `keyId`، `publicKey`، `signature`، `statementSha256`، `ledgerSeq` و
`recordHash`، `recordedBy` و `attestation`. دفترِ فقط-افزودنی در
`data/history/approvals/identity-approvals.json` و کلیدهای عمومی در
`trusted-keys.json` است؛ کلیدِ خصوصی commit نمی‌شود.

**تفکیک تأیید از ثبت:** `by`/`approvedAt` به اقدام انسانی اشاره می‌کنند، اما
`recordedBy: agent:codebuff` و `attestation: chat-approval-recorded-by-agent`
صریح می‌گویند رکورد را عامل از تأیید چت ثبت کرده است. امضای Ed25519 فقط
یکپارچگیِ رکورد را ثابت می‌کند، نه هویتِ شخصیِ امضاکننده؛ اگر کلیدِ خصوصی در
اختیار عامل باشد، امضا به‌تنهایی اثباتِ مستقلِ انسان نیست. `approvedAt` تاریخِ
تأیید انسانی است و باید از زمانِ امضای ماشینی جدا بماند؛ اگر زمان دقیق چت ثبت
نشده باشد، فقط تاریخ با یادداشتِ صریح نوشته می‌شود.

تصمیمِ بدونِ امضا یا با بیانیهٔ تغییرکرده با `REVIEW_APPROVAL_MISSING` /
`APPROVAL_STATEMENT_MISMATCH` رد می‌شود. گیت: `REVIEW_DECISION_UNKNOWN`،
`REVIEW_TARGET_MISSING`، `REVIEW_EVIDENCE_MISSING`، `REVIEW_EVIDENCE_PAGE`،
`REVIEW_INCOMPLETE`، `REVIEW_DUPLICATE`، `APPROVAL_LEDGER_CHAIN` و هشدارِ
`REVIEW_OPEN`.

ثبت/بازگردانیِ تصمیم فقط با امضا:

```bash
py -3 scripts/approval_ledger.py sign --all --private .approval-keys/approver.key \
    --approver "user:..." --channel chat --approved-at 2026-11-24T00:00:00Z \
    --recorded-by agent:codebuff --attestation chat-approval-recorded-by-agent \
    --statement "متنِ تأیید"
py -3 scripts/build_identity_reviews.py --disable S1273FA50 \
    --private-key .approval-keys/approver.key --approver "user:..." --statement "دلیل"
py -3 scripts/build_identity_reviews.py --enable S1273FA50 \
    --private-key .approval-keys/approver.key --approver "user:..." --statement "دلیل"
py -3 scripts/approval_ledger.py verify
```

خاموش‌کردن، هویت/وقوع را از نو می‌سازد و هویتِ ردیفی را دوباره `needsReview`
می‌کند؛ خودِ تصمیم و شاهدش در فایل می‌ماند. `--disable`/`--enable` هر دو
`identity-reviews.json` را تغییر می‌دهند، پس با گیت قابلِ ردیابی‌اند.

## ۳. قاعدهٔ ساخت: فقط شاهد

```
برای هر نسخهٔ approved سال Y:
    برای هر ردیفِ دارای عنوان:
        هویت را با عنوانِ همان ردیف تطبیق بده
        یک Occurrence با سال Y و تاریخِ همان ردیف بساز
هیچ حلقه‌ای روی سال‌های بدونِ سند وجود ندارد.
```

- خروجیِ قاعده‌محورِ `data/years/*.json` (پیش‌بینیِ نوروز/عاشورا برای ۱۴۰۷+)
  **وارد این مدل نمی‌شود**؛ در وبِ عمومی هم با برچسبِ جدا نمایش داده می‌شود.
- هویت‌های کاتالوگ که هیچ ردیفی ندارند، در `events.json` می‌مانند تا «در هیچ
  سندِ بررسی‌شده‌ای دیده نشد» صادقانه نمایش داده شود؛ برای آن‌ها وقوعی ساخته نمی‌شود.
- ردیفِ چسبیدهٔ PDF فقط وقتی به چند هویت می‌شکند که پوششِ عنوان‌های کاتالوگ در
  آن ردیف دست‌کم ۵۵٪ باشد. ردیفِ بلندِ ناشناس یک هویتِ `row` می‌شود، نه چند
  وقوعِ حدسی.
- عنوان‌های تکراری (چهار «عید نوروز»، سه «شب قدر»، دو «شهادت فاطمه») با تاریخِ
  همان ردیف، سالِ مشاهده و شباهتِ عنوان از هم جدا می‌شوند.

## ۴. بازتولید و ضدِ دست‌کاری

وقوع‌ها و هویت‌ها **مشتق** هستند: `build_history.py` و پس از هر تأیید،
`review_changes.py` آن‌ها را از نسخه‌های `approved` بازمی‌سازند.
`audit_history.py` همین بازتولید را دوباره انجام می‌دهد و با فایل مقایسه می‌کند:

- `OCC_NOT_DERIVED` اگر وقوعی در فایل باشد که از شاهدها ساخته نمی‌شود؛
- `OCC_REVISION_NOT_APPROVED` اگر وقوع به نسخهٔ `draft`/`rejected` اشاره کند؛
- `REV_SHA_MISMATCH` اگر PDF عوض شده باشد؛
- `OCC_YEAR_MISMATCH` اگر سالِ وقوع با سالِ نسخه نخواند.

## ۵. معیارِ پذیرش (نگاشت به چک‌لیست)

| خواسته | جای پیاده‌سازی | آزمون |
|---|---|---|
| وجود/عدم‌وجود/تفاوتِ مشخصات در سال‌ها | `derive()` + `occurrences.json` | `test_each_year_has_its_own_occurrence` |
| عدمِ تعمیم به سالِ بی‌سند | فقط نسخهٔ approved | `test_no_generalization_without_witness` |
| چند عنوان برای یک هویت | `aliases` + `match` | `test_alias_change_does_not_rewrite_other_year` |
| تفکیکِ تاریخِ وقوع/ثبت/اصل | `date` / `firstRecordedDate` / `established` | بازرسیِ داده |
| جلوگیری از ورودِ دادهٔ تأییدنشده | `audit_history.py` | `test_validation_catches_orphan_and_tampering` |
| تفکیکِ مبنای خودکار از تأییدِ انسانی | `approval` + گیت | `test_baseline_cannot_pose_as_human_approval` |
| بازبینیِ هویتِ ردیفی بدونِ ادغامِ خودکار | `identity-reviews.json` + `derive` | `test_keep_documents_without_merging` / `test_map_uses_explicit_target` |

## ۶. نمونهٔ ساختاری (غیرواقعی)

| نسخه | وضعیت | معنا |
|---|---|---|
| ۱۴۰۴ | ثبت نشده | در سندِ بررسی‌شدهٔ آن سال دیده نشده؛ **نه** «رخ نداده» |
| ۱۴۰۵ | افزوده | عنوان و تاریخ از PDF همان سال با صفحه/هش ثبت شده |
| ۱۴۰۶ | تغییر یافته | عنوان یا تاریخ نسبت به ۱۴۰۵ متفاوت است؛ هر دو وقوع جدا می‌مانند |

این جدول فقط ساختار را نشان می‌دهد و سابقهٔ یک مناسبتِ واقعی نیست.

## ۷. محدودیت‌ها

- سال‌های ۱۳۹۳، ۱۳۹۶ و ۱۴۰۲ لایهٔ متنیِ سالم ندارند؛ نسخه‌ای برایشان ساخته
  نشده و در نتیجه هیچ وقوعی هم ندارند. تا نصبِ OCR، این سه سال «سندِ بررسی‌نشده»‌اند.
- تطبیقِ عنوان همیشه قطعی نیست؛ `match.kind` و `needsReview` همین را آشکار می‌کنند.
- یک ردیفِ PDF می‌تواند چند رویداد را در یک خط چاپ کند؛ `sharedRow` نشان می‌دهد
  که وقوع از ردیفِ مشترک آمده و صفحه/عنوانِ کامل را برای بازبینی نگه می‌دارد.
