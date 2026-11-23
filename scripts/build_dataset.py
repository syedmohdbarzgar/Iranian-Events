#!/usr/bin/env python3
"""از استخراجِ خامِ PDFها، مجموعهٔ داده‌های تمیز و مستند می‌سازد.

مراحل:
  ۱. سال‌های خوانا از `extracted/json/<year>.json` بارگذاری می‌شوند
     (سال‌هایی که لایهٔ متنی‌شان خراب است کنار گذاشته و گزارش می‌شوند)؛
  ۲. عنوان‌ها یکسان‌سازی و غلط‌های املاییِ شناخته‌شده اصلاح می‌شوند؛
  ۳. تعطیلات از نشانهٔ «تعطیل» خودِ PDF جدا می‌شوند؛
  ۴. وابستگیِ هر رویداد به تقویم (شمسی/قمری/میلادی) از دادهٔ چندسالِ خودِ
     PDFها استنتاج می‌شود: ثابت‌بودنِ (ماه، روز) در یکی از سه تقویم.

هیچ داده‌ای از برنامهٔ اندروید خوانده نمی‌شود؛ همه‌چیز از PDFها می‌آید.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "extracted" / "json"
DATA = ROOT / "data"
REPORTS = ROOT / "reports"

# سال‌هایی که لایهٔ متنیِ PDF خراب است و استخراجِ ساختاری ممکن نیست.
BROKEN = {
    1393: "لایهٔ متنی با نگاشتِ ناقصِ فونت (نویسه‌های ʆɳʈ…) — نیاز به OCR",
    1396: "ارقامِ فارسی با نگاشتِ جابه‌جا (۱۳۹۶→۳۱۶۹) — نیاز به OCR",
    1402: "ارقام و ستون‌ها جابه‌جا (۱۴۰۲→۲۱۲۲) — خروجی غیرقابل‌اعتماد",
}

# اصلاحِ غلط‌های املایی/تایپیِ دیده‌شده در PDFها (فقط نگارش، نه معنا).
FIXES = {
    "چهارشبه": "چهارشنبه",
    "پنج شبه": "پنجشنبه",
    "يكشنبه": "یکشنبه",
    "سه شنبه": "سه‌شنبه",
    "پنج شنبه": "پنجشنبه",
    "هو ش": "ه‍.ش",
    "هو ق": "ه‍.ق",
    "مي ": "می‌",
    "ميتوان": "می‌توان",
    "بعضي": "بعضی",
    "روزهاي": "روزهای",
    "مناسب تها": "مناسبت‌ها",
    "هفتهٔ": "هفتهٔ",
    "سالروز": "سالروز",
    "بیست ": "بیست ",
    "امير": "امیر",
    "شهيد": "شهید",
    "شهادت": "شهادت",
    "تعطيل": "تعطیل",
    "انقلابي": "انقلابی",
    "ايران": "ایران",
    "اسلامي": "اسلامی",
    "كشور": "کشور",
    "ملي": "ملی",
    "جهاني": "جهانی",
    "بزرگداشت": "بزرگداشت",
    "عليه": "علیه",
    "سلام الله": "سلام‌الله",
    "صلي الله": "صلی‌الله",
    "عليه السلام": "علیه‌السلام",
    "عليه‌السلام": "علیه‌السلام",
}

HOLIDAY_TAG = re.compile(r"\(\s*تعطیل\s*\)")


def clean_title(raw: str, fix_log: dict[str, int]) -> tuple[str, bool]:
    title = raw
    holiday = bool(HOLIDAY_TAG.search(title))
    title = HOLIDAY_TAG.sub("", title)
    # پرانتزهای جابه‌جا در متن RTL
    title = title.replace(")تعطیل(", "")
    title = re.sub(r"\s+", " ", title).strip(" -،.;")
    # نشانه‌های تکرارِ سرگردانِ ستون‌های تاریخ که به ابتدای عنوان چسبیده‌اند
    while re.match(r'^[«»"”]\s*', title):
        title = re.sub(r'^[«»"”]\s*', "", title)
    # باقی‌ماندهٔ ستون‌های تاریخ در ابتدای عنوان («28 " " 26 " 7 …»)
    title = re.sub(r'^(?:[\d]{1,2}\s+[«»"”]\s*)+', "", title)
    title = re.sub(r'^[\d]{1,2}\s+', "", title) if re.match(r'^[\d]{1,2}\s+[^\d]', title) else title
    if not re.search(r"[؀-ۿ]{3,}", title):
        title = ""
    for a, b in FIXES.items():
        if a in title and a != b:
            fix_log[a] = fix_log.get(a, 0) + title.count(a)
            title = title.replace(a, b)
    # فاصله‌های خرابِ اطرافِ نشانه‌ها
    title = re.sub(r"\s+([،؛:])", r"\1", title)
    title = re.sub(r"\(\s+", "(", title)
    title = re.sub(r"\s+\)", ")", title)
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(), holiday


def main() -> int:
    DATA.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    fix_log: dict[str, int] = {}
    per_year = {}
    excluded = {}
    for path in sorted(SRC.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        year = data["year"]
        if year in BROKEN:
            excluded[year] = {"reason": BROKEN[year], "source": data["source"]}
            continue
        rows = []
        for r in data["rows"]:
            if not r.get("title"):
                continue
            title, holiday = clean_title(r["title"], fix_log)
            if not title:
                continue
            rows.append(
                {
                    "solar": r["solar"],
                    "gregorian": r["gregorian"],
                    "lunar": r["lunar"],
                    "weekday": r["weekday"],
                    "title": title,
                    "holiday": holiday or r.get("holiday", False),
                    "page": r.get("page"),
                    "derived": r.get("derived", []),
                }
            )
        per_year[year] = {"source": data["source"], "rows": rows,
                          "gregorian_anomalies": data["qc"].get("gregorian_anomalies", []),
                          "filled_days": data.get("filled_days", 0)}
        (DATA / f"official-calendar-{year}.json").write_text(
            json.dumps({"year": year, "source": data["source"], "rows": rows}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    # --- تجمیع رویدادها در سال‌ها ---
    def match_key(title: str) -> str:
        """کلیدِ تطبیق: عنوان‌های نزدیک به هم یک رویداد شمرده شوند."""
        t = re.sub(r"\([^)]*\d[^)]*\)", "", title)          # (۱۳۶۱ ه‍.ش) و مانند آن
        t = re.sub(r"\([^)]*\)", "", t)
        t = re.sub(r"[\d۰-۹]+", "", t)
        t = re.sub(r"[،؛:().«»\-]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t[:80]

    events: dict[str, dict] = {}
    for year, pack in per_year.items():
        for r in pack["rows"]:
            key = match_key(r["title"])
            if not key:
                continue
            ev = events.setdefault(key, {"title": r["title"], "titles": set(), "years": [], "solar": set(), "lunar": set(),
                                         "gregorian": set(), "holiday_years": [], "pages": []})
            ev["titles"].add(r["title"])
            ev["years"].append(year)
            ev["solar"].add((r["solar"][1], r["solar"][2]))
            ev["lunar"].add((r["lunar"][1], r["lunar"][2]))
            ev["gregorian"].add((r["gregorian"][1], r["gregorian"][2]))
            if r["holiday"]:
                ev["holiday_years"].append(year)
            ev["pages"].append([year, r["page"]])

    def classify(ev: dict) -> str:
        n = len(set(ev["years"]))
        solar, lunar, greg = ev["solar"], ev["lunar"], ev["gregorian"]
        markers_solar = "ه‍.ش" in ev["title"] or "ه.ش" in ev["title"]
        markers_lunar = "ه‍.ق" in ev["title"] or "ه.ق" in ev["title"]
        if n >= 2:
            if len(solar) == 1 and len(lunar) > 1:
                return "solar"
            if len(lunar) == 1 and len(solar) > 1:
                return "lunar"
            if len(greg) == 1 and len(solar) > 1:
                return "gregorian"
            if len(solar) == 1:
                return "solar"
            if len(lunar) == 1:
                return "lunar"
            return "unresolved"
        if markers_solar and not markers_lunar:
            return "solar"
        if markers_lunar and not markers_solar:
            return "lunar"
        t = ev["title"]
        LUNAR_HINTS = ("امام", "شهادت حضرت", "ولادت حضرت", "رحلت حضرت", "عید سعید", "عید فطر",
                       "عید قربان", "غدیر", "عاشورا", "تاسوعا", "اربعین", "مبعث", "میلاد",
                       "شعبان", "رمضان", "محرم", "صفر", "ربیع", "جمادی", "رجب", "شوال",
                       "ذی‌القعده", "ذی‌الحجه", "حضرت زهرا", "حضرت فاطمه", "ائمه", "معصوم", "اعتکاف", "ایام البیض")
        SOLAR_HINTS = ("سالروز", "انقلاب اسلامی", "دفاع مقدس", "نوروز", "سیزده‌بدر", "یزد", "شهدای",
                       "پیروزی", "فتح", "آزادسازی", "ملی شدن", "کودتای", "بهمن ۵۷", "خرداد ۴۲",
                       "هجوم", "بسیج", "سپاه", "جنگ تحمیلی", "آغاز", "تأسیس", "تشکیل")
        GREG_HINTS = ("روز جهانی", "روز بین‌المللی", "World", "International")
        if any(h in t for h in LUNAR_HINTS) and "روز جهانی" in t:
            return "lunar"
        if any(h in t for h in GREG_HINTS):
            return "gregorian"
        if any(h in t for h in LUNAR_HINTS):
            return "lunar"
        if any(h in t for h in SOLAR_HINTS):
            return "solar"
        return "unresolved"

    out_events = []
    for i, (title, ev) in enumerate(sorted(events.items())):
        cls = classify(ev)
        out_events.append(
            {
                "id": f"ev-{i + 1:04d}",
                "title": ev["title"],
                "titles": sorted(ev["titles"])[:6],
                "years": sorted(set(ev["years"])),
                "occurrences": len(ev["years"]),
                "solar_dates": sorted(ev["solar"]),
                "lunar_dates": sorted(ev["lunar"]),
                "gregorian_dates": sorted(ev["gregorian"]),
                "calendar": cls,
                "holiday_years": sorted(set(ev["holiday_years"])),
                "sources": ev["pages"][:12],
            }
        )
    (DATA / "events.json").write_text(json.dumps(out_events, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- گزارش ---
    total_rows = sum(len(p["rows"]) for p in per_year.values())
    counts = defaultdict(int)
    for e in out_events:
        counts[e["calendar"]] += 1
    lines = ["# گزارش استخراج و صحت‌سنجی PDFها", "",
             f"- PDFهای تقویمِ سالانه: ۲۵ فایل؛ قابلِ استخراجِ ساختاری: {len(per_year)} سال",
             f"- سال‌های کنارگذاشته: {len(excluded)}",
             f"- ردیف‌های رویدادِ استخراج‌شده: {total_rows}",
             f"- رویدادهای یکتا: {len(out_events)}",
             f"- وابستگیِ تقویمی: شمسی {counts['solar']} · قمری {counts['lunar']} · میلادی {counts['gregorian']} · نامشخص {counts['unresolved']}",
             "", "## سال‌ها", "", "| سال | فایل | ردیف | مناسبت | تعطیل | اصلاح میلادی | روزِ پرشده |", "|---|---|---|---|---|---|---|"]
    for y in sorted(per_year):
        p = per_year[y]
        lines.append(f"| {y} | {p['source']} | {len(p['rows'])} | {sum(1 for r in p['rows'] if r['title'])} | "
                     f"{sum(1 for r in p['rows'] if r['holiday'])} | {len(p['gregorian_anomalies'])} | {p['filled_days']} |")
    lines += ["", "## فایل‌های غیرقابل‌استخراج", ""]
    for y, info in sorted(excluded.items()):
        lines.append(f"- **{y}** — {info['reason']} (`{info['source']}`)")
    lines += ["", "## غلط‌های املاییِ اصلاح‌شده", ""]
    for a, c in sorted(fix_log.items(), key=lambda x: -x[1]):
        lines.append(f"- «{a}» → «{FIXES[a]}» — {c} بار")
    (REPORTS / "dataset-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    (REPORTS / "calendar-dependency.md").write_text(
        "# وابستگیِ رویدادها به تقویم\n\n"
        "روش: هر رویداد در سال‌های مختلف نگاه می‌شود؛ اگر (ماه، روزِ) شمسی‌اش ثابت بماند ولی\n"
        "قمری‌اش بچرخد، وابسته به تقویمِ شمسی است؛ برعکسش قمری؛ و اگر (ماه، روزِ) میلادی ثابت\n"
        "بماند، میلادی. رویدادِ تک‌سال با نشانهٔ «ه‍.ش» در عنوان شمسی و با «ه‍.ق» قمری برچسب می‌خورد.\n"
        f"\nنتیجه: شمسی {counts['solar']} · قمری {counts['lunar']} · میلادی {counts['gregorian']} · نامشخص {counts['unresolved']}\n",
        encoding="utf-8",
    )
    # --- گزارش تعطیلات ---
    hol = ["# روزهای تعطیلِ استخراج‌شده از PDFها", "",
           "مبنای هر ردیف، نشانهٔ «(تعطیل)» در ستونِ مناسبت‌های همان PDF است؛ تاریخِ شمسی، میلادی و قمری همه از خودِ PDF می‌آید.", ""]
    for y in sorted(per_year):
        rows = [r for r in per_year[y]["rows"] if r["holiday"]]
        hol.append(f"## {y} — {len(rows)} روزِ تعطیل")
        hol.append("")
        hol.append("| شمسی | میلادی | قمری | مناسبت |")
        hol.append("|---|---|---|---|")
        for r in rows:
            jy, jm, jd = r["solar"]; g = r["gregorian"]; l = r["lunar"]
            hol.append(f"| {jy}/{jm}/{jd} | {g[0]}-{g[1]:02d}-{g[2]:02d} | {l[0]}/{l[1]}/{l[2]} | {r['title']} |")
        hol.append("")
    (REPORTS / "holidays.md").write_text(chr(10).join(hol), encoding="utf-8")

    # --- نمونه‌های هر طبقهٔ تقویمی ---
    by_cls = defaultdict(list)
    for e in out_events:
        by_cls[e["calendar"]].append(e)
    dep = [f"# وابستگیِ رویدادها به تقویم", "",
           "ایران سه تقویمِ رسمی دارد: هجری شمسی (ملی)، هجری قمری (مناسبت‌های اسلامی) و میلادی",
           "(رویدادهای جهانی/مسیحی). منبع: ویکی‌پدیا «Public holidays in Iran» و مستند PersianCalendar.",
           "",
           "روشِ این استخراج: هر رویداد در سال‌های مختلف دیده می‌شود؛ اگر (ماه، روزِ) شمسی ثابت بماند",
           "و قمری بچرخد ⇒ شمسی؛ اگر قمری ثابت بماند ⇒ قمری؛ اگر میلادی ثابت بماند ⇒ میلادی.",
           "رویدادهای تک‌سال با نشانهٔ «ه‍.ش»/«ه‍.ق» و واژه‌های کلیدی (امام، عید، نوروز، روز جهانی…) برچسب می‌خورند.",
           "",
           f"- شمسی: {counts['solar']} · قمری: {counts['lunar']} · میلادی: {counts['gregorian']} · نامشخص: {counts['unresolved']}",
           ""]
    for cls, label in (("solar", "شمسی"), ("lunar", "قمری"), ("gregorian", "میلادی"), ("unresolved", "نامشخص")):
        dep.append(f"## {label} — {len(by_cls[cls])} رویداد")
        dep.append("")
        for e in by_cls[cls][:8]:
            dep.append(f"- {e['title'][:90]} — سال‌ها: {e['years'][:6]} — شمسی: {e['solar_dates'][:3]}")
        dep.append("")
    (REPORTS / "calendar-dependency.md").write_text(chr(10).join(dep), encoding="utf-8")

    print(f"years={len(per_year)} events={len(out_events)} rows={total_rows} "
          f"solar={counts['solar']} lunar={counts['lunar']} greg={counts['gregorian']} unresolved={counts['unresolved']}")
    print("excluded:", excluded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
