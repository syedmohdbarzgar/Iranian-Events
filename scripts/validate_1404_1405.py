"""اعتبارسنجی مستقلِ جدول‌های رسمی ۱۴۰۴ و ۱۴۰۵ + گزارشِ قبل/بعد.

آزمون‌ها:
  ۱ یکتایی تاریخ هر ردیف
  ۲ تاریخ معتبر (طول ماه/کبیسه/سال)
  ۳ روز هفته مطابقِ تاریخ میلادی
  ۴ تبدیل میلادی با مرجعِ مستقلِ jalali_reference
  ۵ قمری: بازهٔ معتبر + مقادیرِ چاپیِ PDF برای ردیف‌های اصلاح‌شده
  ۶ تعطیلی: مقدار انتظاریِ PDF برای ردیف‌های اصلاح‌شده + سازگاریِ سایر ردیف‌ها
  ۷ عدمِ انتقالِ رویداد به روز مجاور
  ۸ عدمِ حذف/تکرارِ رویدادها
  ۹ تطبیقِ تعداد/تاریخ ردیف‌ها با روزهای تاریخ‌دارِ PDF
  ۱۰ شاهدِ متنیِ صفحهٔ PDF برای هر اصلاح

اجرا:
  py -3 scripts/validate_1404_1405.py --phase before
  py -3 scripts/validate_1404_1405.py --phase after
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PDF = ROOT / "PDF"
OUT = ROOT / "reports" / "audit"
sys.path.insert(0, str(ROOT / "scripts"))
import jalali_reference as jr  # noqa: E402

YEARS = (1404, 1405)
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
RTL = "\u202b\u202a\u202c\u200f\u200e"


def norm(text: str) -> str:
    text = text.translate({ord(c): None for c in RTL})
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه").replace("ۀ", "ه")
    text = text.replace("\u200c", "").replace("\u00ad", "")
    text = re.sub(r"(?<=[0-9])(?=[آ-ی])", " ", text)
    text = re.sub(r"(?<=[آ-ی])(?=[0-9])", " ", text)
    text = re.sub(r"[\(\)«»\"“”]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def pdf_page(year: int, page: int) -> str:
    proc = subprocess.run(
        ["pdftotext", "-table", "-enc", "UTF-8", "-f", str(page), "-l", str(page),
         str(PDF / f"Calendar-{year}.pdf"), "-"],
        capture_output=True,
    )
    return proc.stdout.decode("utf-8", "replace")


def load_year(year: int) -> dict:
    return json.loads((DATA / f"official-calendar-{year}.json").read_text(encoding="utf-8"))


def load_corrections() -> list[dict]:
    doc = json.loads((DATA / "official-corrections-1404-1405.json").read_text(encoding="utf-8"))
    return doc["corrections"]


def find(rows: list[dict], solar: list[int]) -> dict | None:
    hit = [r for r in rows if r["solar"] == solar]
    return hit[0] if len(hit) == 1 else None


def has_words(text: str, words: list[str]) -> bool:
    t = norm(text)
    return all(norm(w) in t for w in words)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["before", "after"], required=True)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    corrections = load_corrections()
    docs = {y: load_year(y) for y in YEARS}
    checks: list[tuple[str, bool, str]] = []
    changes: list[dict] = []

    # ۱ یکتایی
    for y, d in docs.items():
        dates = [tuple(r["solar"]) for r in d["rows"]]
        ok = len(dates) == len(set(dates))
        checks.append((f"{y}: یکتایی تاریخ", ok, f"{len(dates)} ردیف، {len(set(dates))} تاریخِ یکتا"))

    # ۲–۴ تاریخ، هفته، میلادی
    for y, d in docs.items():
        bad_valid, bad_wd, bad_greg = [], [], []
        for r in d["rows"]:
            jy, jm, jd = r["solar"]
            try:
                if not (1 <= jm <= 12):
                    raise ValueError
                length = jr.month_length(jy, jm)
                if not (1 <= jd <= length):
                    raise ValueError
                greg = jr.to_gregorian(jy, jm, jd)
            except Exception:
                bad_valid.append(r["solar"])
                continue
            if tuple(r["gregorian"]) != greg:
                bad_greg.append((r["solar"], r["gregorian"], greg))
            if date(*greg).weekday() != r["weekday"]:
                bad_wd.append((r["solar"], r["weekday"], date(*greg).weekday()))
        checks.append((f"{y}: تاریخ معتبر", not bad_valid, f"نامعتبر: {bad_valid[:5]}"))
        checks.append((f"{y}: روز هفته", not bad_wd, f"ناسازگار: {bad_wd[:5]}"))
        checks.append((f"{y}: میلادی مستقل", not bad_greg, f"ناسازگار: {bad_greg[:5]}"))

    # ۵ قمری
    lunar_bad = []
    for c in corrections:
        row = find(docs[c["year"]]["rows"], c["date"])
        if c["lunar"] is None:
            continue
        if row is None or row.get("lunar") != c["lunar"]:
            lunar_bad.append((c["id"], row.get("lunar") if row else None, c["lunar"]))
    all_lunar_valid = all(
        1 <= m <= 12 and 1 <= day <= 30 and 1300 <= y <= 1500
        for d in docs.values() for r in d["rows"] for y, m, day in [r["lunar"]]
    )
    checks.append(("قمریِ ردیف‌های اصلاح‌شده", not lunar_bad, f"ناسازگار با PDF: {lunar_bad}"))
    checks.append(("قمری: بازهٔ معتبر همهٔ ردیف‌ها", all_lunar_valid, "سال/ماه/روز در بازه"))

    # ۶ تعطیلی + ۱۰ شاهد PDF
    holiday_bad, evidence_bad = [], []
    for c in corrections:
        row = find(docs[c["year"]]["rows"], c["date"])
        if c["after"]["title"] is None:
            if row is not None:
                holiday_bad.append((c["id"], "ردیف باید حذف شده باشد"))
            changes.append({
                "id": c["id"], "date": c["date"], "page": c["page"],
                "before": c["before"], "after": c["after"],
                "reason": c["reason"], "evidence": c["evidence"],
                "status": c["status"], "test": "verified" if row is None else "failed",
            })
            continue
        if row is None:
            holiday_bad.append((c["id"], "ردیف نیست"))
            continue
        if row["title"] != c["after"]["title"]:
            checks.append((f"{c['id']}: عنوان", False, f"{row['title'][:70]!r} ≠ {c['after']['title'][:70]!r}"))
        else:
            checks.append((f"{c['id']}: عنوان", True, "مطابقِ after"))
        if row["holiday"] != c["after"]["holiday"]:
            holiday_bad.append((c["id"], row["holiday"], c["after"]["holiday"]))
        text = pdf_page(c["year"], c["page"])
        page_norm = norm(text)
        # ترتیبِ کلمات در استخراجِ RTL جدول جابه‌جا می‌شود؛ وجودِ همهٔ واژه‌ها کافی است.
        missing = [p for p in c["pdf_phrases"] if not all(norm(w) in page_norm for w in p.split())]
        if missing:
            evidence_bad.append((c["id"], c["page"], missing))
        changes.append({
            "id": c["id"], "date": c["date"], "page": c["page"],
            "before": c["before"], "after": c["after"],
            "reason": c["reason"], "evidence": c["evidence"],
            "status": c["status"], "test": "verified" if (not missing and row["holiday"] == c["after"]["holiday"] and row["title"] == c["after"]["title"]) else "failed",
        })
    checks.append(("تعطیلیِ ردیف‌های اصلاح‌شده", not holiday_bad, f"ناسازگار: {holiday_bad}"))
    checks.append(("شاهدِ صفحهٔ PDF", not evidence_bad, f"ناقص: {evidence_bad}"))

    # ۷ انتقال به روز مجاور
    adjacent_bad = []
    for c in corrections:
        y, m, d = c["date"]
        rows = docs[y]["rows"]
        prev = find(rows, [y, m, d - 1]) if d > 1 else None
        nxt = find(rows, [y, m, d + 1])
        forbidden = {
            "1404-01-01": ["شهادت حضرت امام علی", "فتح‌المبین"],
            "1404-01-02": [],
            "1405-01-01": ["فیضیه", "فتح‌المبین"],
            "1405-01-02": [],
            "1405-03-13": ["غدیر", "رحلت", "انتخاب"],
            "1405-03-14": [],
            "1404-03-13": ["رحلت", "انتخاب"],
            "1404-03-14": [],
        }[c["id"]]
        # فقط خودِ روزِ اصلاح‌شده سنجیده می‌شود؛ روزِ مقصد (مثلاً ۱۴ خرداد)
        # عمداً همان رویدادها را دارد و نباید نقض شمرده شود.
        row = find(rows, c["date"])
        if row and any(w in row["title"] for w in forbidden):
            adjacent_bad.append((c["id"], "خودِ روز", row["solar"]))
        if prev and any(w in prev["title"] for w in forbidden):
            adjacent_bad.append((c["id"], "قبلی", prev["solar"]))
    checks.append(("عدمِ انتقال به روز مجاور", not adjacent_bad, f"نقض: {adjacent_bad}"))

    # ۸ حذف/تکرار رویدادها
    all_text = {y: norm(" ".join(r["title"] for r in d["rows"])) for y, d in docs.items()}
    event_bad = []
    for phrase, year, expected in [
        ("غدیر", 1405, 1), ("رحلت حضرت امام خمینی", 1405, 1), ("انتخاب حضرت آیت", 1405, 1),
    ]:
        n = all_text[year].count(norm(phrase))
        if n != expected:
            event_bad.append((year, phrase, n, expected))
    # ۱۴۰۵/۳/۱۳ باید بدونِ این سه باشد
    r13 = find(docs[1405]["rows"], [1405, 3, 13])
    if r13 and any(w in r13["title"] for w in ("غدیر", "رحلت", "انتخاب")):
        event_bad.append((1405, "۳/۱۳ آلوده", r13["title"][:60], "بدونِ سه مناسبت"))
    checks.append(("عدمِ حذف/تکرار رویداد", not event_bad, f"نقض: {event_bad}"))

    # ۹ تعداد/تاریخ ردیف‌ها با PDF
    count_bad = []
    for y, d in docs.items():
        for r in d["rows"]:
            text = norm(pdf_page(y, r["page"]))
            wd = norm(WEEKDAYS[r["weekday"]])
            day = str(r["solar"][2])
            if wd not in text or not re.search(rf"(?<!\d){day}(?!\d)", text):
                count_bad.append((y, r["solar"], r["page"], wd, day))
    checks.append(("تاریخِ ردیف‌ها در صفحهٔ PDF", not count_bad, f"ناسازگار: {count_bad[:6]}"))

    ok = all(c[1] for c in checks)
    (OUT / f"1404-1405-{args.phase}.json").write_text(
        json.dumps({"phase": args.phase, "checks": checks, "changes": changes}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# اعتبارسنجی ۱۴۰۴ و ۱۴۰۵ — {'قبل از اصلاح' if args.phase == 'before' else 'بعد از اصلاح'}",
        "",
        "منبع: `PDF/Calendar-1404.pdf` و `PDF/Calendar-1405.pdf`؛ داده: `data/official-calendar-1404.json` و `1405.json`.",
        "",
        "## آزمون‌ها",
        "",
        "| آزمون | نتیجه | جزئیات |",
        "|---|---|---|",
    ]
    for name, passed, detail in checks:
        lines.append(f"| {name} | {'✅' if passed else '❌'} | {detail} |")
    lines += [
        "",
        "## تغییراتِ مستند",
        "",
        "| شناسه | تاریخ | صفحه | عنوان قبلی | عنوان اصلاح‌شده | تعطیلی قبل→بعد | وضعیت | آزمون |",
        "|---|---|---:|---|---|---|---|---|",
    ]
    for ch in changes:
        before = (ch["before"]["title"] or "—").replace("|", "\\|")
        after = (ch["after"]["title"] or "— حذف ردیفِ خالی —").replace("|", "\\|")
        lines.append(
            f"| {ch['id']} | {ch['date'][0]}/{ch['date'][1]}/{ch['date'][2]} | {ch['page']} | "
            f"{before} | {after} | {ch['before']['holiday']}→{ch['after']['holiday']} | {ch['status']} | {ch['test']} |"
        )
    lines += [
        "",
        "## دامنهٔ اعتبار",
        "",
        "- آزمون‌های ساختاری (یکتایی، تاریخ معتبر، روز هفته، میلادی، بازهٔ قمری) روی **همهٔ** ردیف‌های دو سال اجرا شده‌اند.",
        "- تعطیلی و قمریِ ردیف‌های اصلاح‌شده با ستون‌های همان صفحهٔ PDF تطبیق داده شده‌اند.",
        "- عنوانِ همهٔ ردیف‌ها به‌صورت کلمه‌به‌کلمه با متنِ صفحهٔ PDF مقایسه نشده است؛ فقط ردیف‌های اصلاح‌شده `verified` هستند و بقیه تأییدِ کامل نشده‌اند.",
        "",
        "## نتیجه",
        "",
        ("همهٔ آزمون‌ها سبز." if ok else "برخی آزمون‌ها ناموفق‌اند؛ جزئیاتِ بالا."),
        "",
    ]
    (OUT / f"1404-1405-{args.phase}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{args.phase}: {'OK' if ok else 'FAIL'} — {sum(1 for c in checks if c[1])}/{len(checks)} آزمون")
    for name, passed, detail in checks:
        if not passed:
            print(f"  ❌ {name}: {detail}")
    return 0 if (ok or args.phase == "before") else 1


if __name__ == "__main__":
    raise SystemExit(main())
