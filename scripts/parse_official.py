#!/usr/bin/env python3
"""استخراج جدولِ تقویم‌های رسمی از PDF — هر فایل جداگانه و مستقل.

روش: `pdftotext -table` ستون‌ها را نگه می‌دارد. هر سطرِ تاریخ‌دار یک روز است با
هشت نشانه پیش از نامِ روزِ هفته (دو نشانه شمسی، سه قمری، سه میلادی) و
علامتِ تکرار (`"`) برای خانه‌های تکرارشده.

چون ترتیبِ درونیِ خانه‌ها در PDFهای مختلف یکی نیست (مثلاً «1448 15 ذی‌الحجه» در
برابر «15 ذی‌الحجه 1448»)، هر خانه با نوعِ نشانه‌ها (سال/روز/ماه) تفسیر می‌شود نه با جای ثابت.

خروجی: extracted/json/<سال>.json   (هیچ داده‌ای از برنامهٔ اندروید خوانده نمی‌شود)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "PDF"
OUT_DIR = ROOT / "extracted" / "json"

SOLAR_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]
LUNAR_MONTHS = [
    "محرم", "صفر", "ربیع الاول", "ربیع الثانی", "جمادی الاول", "جمادی الثانی",
    "رجب", "شعبان", "رمضان", "شوال", "ذی القعده", "ذی الحجه",
]
LUNAR_ALIASES = {
    "ربیعالاول": "ربیع الاول", "ربیع اول": "ربیع الاول", "ربیع الاولی": "ربیع الاول",
    "ربیعالثانی": "ربیع الثانی", "ربیع ثانی": "ربیع الثانی", "ربیع الآخر": "ربیع الثانی",
    "جمادیالاول": "جمادی الاول", "جمادی اولی": "جمادی الاول", "جمادی الاولی": "جمادی الاول",
    "جمادیالثانی": "جمادی الثانی", "جمادی ثانی": "جمادی الثانی", "جمادی الثانیه": "جمادی الثانی",
    "ذیالقعده": "ذی القعده", "ذیقعده": "ذی القعده",
    "ذیالحجه": "ذی الحجه", "ذیحجه": "ذی الحجه",
}

# گونه‌های چسبیده با نیم‌فاصله که در PDFهای قدیمی دیده می‌شود
LUNAR_ZWNJ = {
    "جمادی‌الاولی": "جمادی الاول", "جمادی‌الثانیه": "جمادی الثانی",
    "جمادی‌الاول": "جمادی الاول", "جمادی‌الثانی": "جمادی الثانی",
    "ربیع‌الاول": "ربیع الاول", "ربیع‌الثانی": "ربیع الثانی",
    "ذی‌القعده": "ذی القعده", "ذی‌الحجه": "ذی الحجه",
}

GREG_MONTHS = {
    "ژانویه": 1, "فوریه": 2, "مارس": 3, "آوریل": 4, "مه": 5, "می": 5,
    "ژوئن": 6, "ژوییه": 7, "ژوئیه": 7, "ژویه": 7, "جولای": 7, "اوت": 8, "آگوست": 8,
    "سپتامبر": 9, "اکتبر": 10, "نوامبر": 11, "دسامبر": 12,
}
WEEKDAYS = {
    "شنبه": 5, "یکشنبه": 6, "يكشنبه": 6, "دوشنبه": 0, "سهشنبه": 1,
    "چهارشنبه": 2, "پنجشنبه": 3, "جمعه": 4, "آدینه": 4,
}
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
BIDI = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200b\u200c\u200d\ufeff"), None)


def norm(text: str) -> str:
    """NFKC (فرم‌های نمایشی عربی → حروف استاندارد) + ارقام فارسی + فاصله‌ها."""
    text = unicodedata.normalize("NFKC", text).translate(BIDI).translate(PERSIAN_DIGITS)
    text = text.replace("ك", "ک").replace("ي", "ی").replace("ى", "ی").replace("ـ", "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    # حذفِ نشانه‌های دوسویه گاهی عدد و واژه را به هم می‌چسباند: «15ذی‌الحجه» → «15 ذی‌الحجه»
    text = re.sub(r"(?<=\d)(?=[^\d\s.,،)])", " ", text)
    text = re.sub(r"(?<=[^\d\s(])(?=\d)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    # نامِ ماه‌های دوقسمتی یک نشانه بمانند تا شمارشِ نشانه‌های خانه به‌هم نریزد.
    for a, b in (
        ("ربیع الاولی", "ربیع-الاول"), ("ربیع الاول", "ربیع-الاول"), ("ربیع اول", "ربیع-الاول"),
        ("ربیع الثانی", "ربیع-الثانی"), ("ربیع الثانیه", "ربیع-الثانی"), ("ربیع الآخر", "ربیع-الثانی"),
        ("جمادی الاولی", "جمادی-الاول"), ("جمادی الاول", "جمادی-الاول"), ("جمادی اولی", "جمادی-الاول"),
        ("جمادی الثانیه", "جمادی-الثانی"), ("جمادی الثانی", "جمادی-الثانی"), ("جمادی ثانی", "جمادی-الثانی"),
        ("ذی القعده", "ذی-القعده"), ("ذیقعده", "ذی-القعده"),
        ("ذی الحجه", "ذی-الحجه"), ("ذیحجه", "ذی-الحجه"),
    ):
        text = text.replace(a, b)
    return text.strip()


def pdf_pages(pdf: Path) -> list[str]:
    proc = subprocess.run(["pdftotext", "-table", "-enc", "UTF-8", str(pdf), "-"], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:300])
    return proc.stdout.decode("utf-8", "replace").translate(BIDI).split("\f")


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33 + 3) // 4) + jd + ((jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    months = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    for i, m in enumerate(months):
        if gd <= m:
            gm = i + 1
            break
        gd -= m
    return gy, gm, gd



def canon_month(tok: str) -> str:
    """نامِ ماه را از نیم‌فاصله/خط تیره/فاصله‌های اضافه پاک می‌کند."""
    t = tok.replace("‌", " ").replace("-", " ")
    return re.sub(r"\s+", " ", t).strip()


COMPACT_MONTHS = {
    "جمادی‌الاولی": "جمادی الاول", "جمادیالاولی": "جمادی الاول", "جمادی‌الاول": "جمادی الاول", "جمادیالاول": "جمادی الاول",
    "جمادی‌الثانیه": "جمادی الثانی", "جمادیالثانیه": "جمادی الثانی", "جمادی‌الثانی": "جمادی الثانی", "جمادیالثانی": "جمادی الثانی",
    "ربیع‌الاول": "ربیع الاول", "ربیعالاول": "ربیع الاول", "ربیع‌الثانی": "ربیع الثانی", "ربیعالثانی": "ربیع الثانی",
    "ذی‌القعده": "ذی القعده", "ذیالقعده": "ذی القعده", "ذی‌الحجه": "ذی الحجه", "ذیالحجه": "ذی الحجه",
}


def month_lookup(tok: str) -> str | None:
    t = canon_month(tok)
    if t in LUNAR_ALIASES:
        return LUNAR_ALIASES[t]
    if t in LUNAR_MONTHS or t in SOLAR_MONTHS or t in GREG_MONTHS:
        return t
    compact = t.replace(" ", "")
    return COMPACT_MONTHS.get(compact)


NOISE = re.compile(
    r"^(تقویم رسمی|مناسبتهای|مناسبتها|میلادی$|هجری قمری$|هجری شمسی$|روزهای هفته|روزهفته|مناسبت ها|استخراج و تنظیم|مصوب|باسمه|صفحه)"
)
HOLIDAY = re.compile(r"تعطیل")


def is_ditto(tok: str) -> bool:
    return tok in {'"', "”", "«", "»"}


def split_record(line: str) -> tuple[dict, str] | None:
    """سطرِ جدول را به سه خانه تاریخ + روزِ هفته + عنوان تجزیه می‌کند.

    خانه‌ها همیشه هشت نشانهٔ پیش از نامِ روزِ هفته‌اند: (ماه، روز) شمسی،
    (سال، ماه، روز) قمری، (سال، ماه، روز) میلادی — با هر ترتیبِ درونی، که
    `read_cell` بر اساس نوعِ نشانه‌ها تفسیر می‌کند.
    """
    toks = line.split(" ")
    n = len(toks)
    for wlen in (2, 1):
        if n < wlen:
            continue
        cand = " ".join(toks[-wlen:]).replace(" ", "")
        if cand in WEEKDAYS:
            idx = n - wlen
            break
    else:
        return None
    body = toks[:idx]
    if len(body) < 8:
        return None
    win = body[-8:]
    return {"wd": cand, "solar": win[6:8], "lunar": win[3:6], "greg": win[0:3]}, " ".join(body[:-8])


def read_cell(tokens: list[str], months: dict[str, int] | None, yearless: bool) -> dict:
    """خانه را با نوعِ نشانه‌ها می‌خواند: سالِ ۴رقمی، روز ۱–۲رقمی، ماه (نام یا تکرار)."""
    out = {"year": None, "month": None, "day": None, "unknown": []}
    for t in tokens:
        if is_ditto(t):
            continue
        if re.fullmatch(r"\d{4}", t):
            out["year"] = int(t)
        elif re.fullmatch(r"\d{1,2}", t):
            out["day"] = int(t)
        elif months is not None and month_lookup(t) in months:
            out["month"] = month_lookup(t)
        else:
            out["unknown"].append(t)
    return out


def resolve(records: list[dict], year: int) -> list[dict]:
    rows: list[dict] = []
    sm = lm = gm = None
    ly = gy = None
    for rec in records:
        s = rec["solar"]
        l = rec["lunar"]
        g = rec["greg"]
        sm = s["month"] or sm
        lm = l["month"] or lm
        gm = g["month"] or gm
        ly = l["year"] or ly
        gy = g["year"] or gy
        rows.append(
            {
                "solar": [year, SOLAR_MONTHS.index(sm) + 1 if sm in SOLAR_MONTHS else None, s["day"]],
                "gregorian": [gy, GREG_MONTHS.get(gm), g["day"]],
                "lunar": [ly, LUNAR_MONTHS.index(LUNAR_ALIASES.get(lm, lm)) + 1 if (lm in LUNAR_MONTHS or lm in LUNAR_ALIASES) else None, l["day"]],
                "weekday": WEEKDAYS.get(rec["wd"]),
                "title": rec["title"],
                "page": rec["page"],
                "unknown": s["unknown"] + l["unknown"] + g["unknown"],
            }
        )
    return rows


def parse_page(page: str, pageno: int) -> list[dict]:
    if "جدول ضمیمه" in page or "بلامانع است" in page:
        return []
    records: list[dict] = []
    current: dict | None = None
    for line in page.split("\n"):
        line = norm(line)
        if not line:
            continue
        parsed = split_record(line)
        if parsed:
            data, title = parsed
            while title[:1] in {'"', "”", "«"}:
                title = title[1:].lstrip()
            if current:
                records.append(current)
            current = {"...": None, **data, "title": title, "page": pageno}
            continue
        if NOISE.match(line):
            continue
        if current is not None:
            current["title"] = norm(current["title"] + " " + line)
    if current:
        records.append(current)
    return records


def build(year: int, pdf: Path) -> dict:
    raw: list[dict] = []
    for i, page in enumerate(pdf_pages(pdf), 1):
        raw.extend(parse_page(page, i))
    # تفسیرِ خانه‌ها
    parsed = []
    for rec in raw:
        parsed.append(
            {
                "solar": read_cell(rec["solar"], {m: i for i, m in enumerate(SOLAR_MONTHS)}, True),
                "lunar": read_cell(rec["lunar"], {**{m: i for i, m in enumerate(LUNAR_MONTHS)}, **LUNAR_ALIASES}, False),
                "greg": read_cell(rec["greg"], GREG_MONTHS, False),
                "wd": rec["wd"],
                "title": rec["title"],
                "page": rec["page"],
            }
        )
    rows = resolve(parsed, year)
    had = len(rows)
    rows = fill_days(rows, year)
    filled = len(rows) - had

    bad: list[str] = []
    anomalies: list[str] = []
    prev = None
    for idx, r in enumerate(rows):
        jy, jm, jd = r["solar"]
        r["holiday"] = bool(HOLIDAY.search(r["title"]))
        if None in (jm, jd):
            bad.append(f"#{idx} بی‌تاریخ solar={r['solar']} lunar={r['lunar']} greg={r['gregorian']} unknown={r['unknown']}")
            prev = r
            continue
        exp = jalali_to_gregorian(jy, jm, jd)
        if None in r["gregorian"]:
            r["gregorian"] = list(exp)
            r.setdefault("derived", [])
            r["derived"] = list(r["derived"]) + ["gregorian"]
        elif tuple(r["gregorian"]) != exp:
            anomalies.append(f"#{idx} میلادیِ چاپی {r['gregorian']} ≠ {exp} (شمسی {jy}/{jm}/{jd})")
            r["pdf_gregorian"] = list(r["gregorian"])
            r["gregorian"] = list(exp)
        if r["weekday"] is not None and date(*exp).weekday() != r["weekday"]:
            bad.append(f"#{idx} روزِ هفته {r['weekday']} ≠ {date(*exp).weekday()} ({jy}/{jm}/{jd})")
        if prev and None not in prev["solar"]:
            pj, pjm, pjd = prev["solar"]
            if pjm == jm and pjd is not None and jd != pjd + 1:
                bad.append(f"#{idx} پرشِ شمسی {pjm}/{pjd} → {jm}/{jd}")
            if pjm != jm and jm != (pjm % 12) + 1:
                bad.append(f"#{idx} ماهِ شمسی {pjm} → {jm}")
        r["holiday"] = bool(HOLIDAY.search(r["title"]))
        prev = r
    return {"source": pdf.name, "year": year, "rows": rows, "filled_days": filled,
            "qc": {"rows": len(rows), "problems": bad, "gregorian_anomalies": anomalies}}



def fill_days(rows: list[dict], year: int) -> list[dict]:
    """روزهای بی‌ردیف را از تقویمِ خودِ سال پر می‌کند (بدونِ هیچ رویداد).

    بعضی PDFها ردیفِ روزهایی را که هیچ مناسبت و هیچ ستونِ تاریخی ندارند اصلاً
    چاپ نمی‌کنند؛ روزِ شمسی از توالیِ ماه‌ها قطعی است، پس تنها همان روز با
    `derived=True` افزوده می‌شود.
    """
    by_date = {(r["solar"][1], r["solar"][2]): r for r in rows if None not in r["solar"][1:]}
    out = []
    gy, gm, gd = jalali_to_gregorian(year, 1, 1)
    for m in range(1, 13):
        length = 31 if m <= 6 else 30
        if m == 12:
            g1 = date(*jalali_to_gregorian(year, 12, 1))
            g2 = date(*jalali_to_gregorian(year + 1, 1, 1))
            length = (g2 - g1).days
        for d in range(1, length + 1):
            key = (m, d)
            if key in by_date:
                out.append(by_date[key])
            else:
                g = jalali_to_gregorian(year, m, d)
                out.append({"solar": [year, m, d], "gregorian": list(g), "lunar": [None, None, None],
                            "weekday": (date(*g).weekday()), "title": "", "page": None, "unknown": [],
                            "derived": True})
    # قمریِ روزهای پرشده را از همسایه‌ها درون‌یابی کن (روزها پیوسته‌اند)
    for i, r in enumerate(out):
        if None in r["lunar"]:
            j = i - 1
            while j >= 0 and None in out[j]["lunar"]:
                j -= 1
            if j >= 0 and None not in out[j]["lunar"]:
                ly, lmn, ld = out[j]["lunar"]
                d = ld + (i - j)
                while d > 30:
                    d -= 29 if lmn in (2, 4, 6, 8, 10, 12) else 30
                    lmn = lmn % 12 + 1
                r["lunar"] = [ly, lmn, d]
                r["derived"] = True
    return out


def main(years: list[int] | None = None) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    for pdf in sorted(PDF_DIR.glob("Calendar-*.pdf")):
        m = re.search(r"Calendar-(\d{4})\.pdf$", pdf.name)
        if not m:
            continue
        year = int(m.group(1))
        if years and year not in years:
            continue
        data = build(year, pdf)
        (OUT_DIR / f"{year}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        bad = data["qc"]["problems"]
        print(f"{year}: {len(data['rows']):4d} rows (+{data['filled_days']} filled), {len(bad):3d} qc, {len(data['qc']['gregorian_anomalies']):2d} greg-anomalies, holidays={sum(r['holiday'] for r in data['rows'])}")
        problems.extend(f"{year}: {b}" for b in bad[:6])
    if problems:
        print("\n--- نمونه مشکلات ---")
        for p in problems[:40]:
            print(" ", p)
    return 0


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    sys.exit(main(args or None))
