#!/usr/bin/env python3
"""موتورِ تولیدِ تقویم برای هر سال — قاعده‌محور و مستقل از دادهٔ برنامه.

ورودی:  `data/events.json` (استخراجِ PDFها) → کاتالوگِ رویدادها
خروجی:  `data/event-catalog.json` و تولیدِ تقویمِ هر سال با `--year`.

قواعد (خلاصه؛ کامل در `docs/calendar-rules.md`):
  R1  سال‌های ۱۳۸۲–۱۴۰۶ با جدولِ رسمیِ همان PDF تولید می‌شوند (بالاترین اعتبار).
  R2  بیرونِ آن بازه، رویدادها از کاتالوگ و بر اساس قاعدهٔ تکرار ساخته می‌شوند.
  R3  رویدادِ فرهنگی/تاریخی/مذهبی هر سال تکرار می‌شود (تاریخی از سالِ رویداد).
  R4  رویدادِ «رسمی متغیر» فقط از سالِ ورودش به تقویم و فقط با شاهدِ همان سال‌ها.
  R5  برای سال‌های بعد از آخرین داده، رسمی‌های «پایدار» ادامه می‌یابند، «تازه»ها
      با اعتمادِ کمتر، و آن‌هایی که در سالِ آخر نیستند تولید نمی‌شوند.
  R6  وابستگیِ تقویمی: شمسی/میلادی دقیق؛ قمری بیرونِ داده با تقویمِ تربیعی و
      پرچمِ `approx=True` (ماهِ قمریِ رسمی ممکن است ±۱ روز باشد).
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

PERSIAN = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
           "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
LUNAR = ["محرم", "صفر", "ربیع‌الاول", "ربیع‌الثانی", "جمادی‌الاول", "جمادی‌الثانی",
         "رجب", "شعبان", "رمضان", "شوال", "ذی‌القعده", "ذی‌الحجه"]

CULTURAL = ("نوروز", "سیزده", "چهارشنبه‌سوری", "یلدا", "مهرگان", "سده", "تیرگان", "جشن", "آب‌پاشی")
HISTORICAL_MARK = re.compile(r"ه[‌.]?ش")
OFFICIAL_START = 1357  # از ۲۲ بهمن ۱۳۵۷ به بعد تقویمِ رسمیِ جمهوری اسلامی


# ---------- تبدیل‌های تقویمی ----------
def _jalali_to_gregorian_unchecked(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
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
    ml = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 1
    for m in ml:
        if gd <= m:
            return gy, gm, gd
        gd -= m
        gm += 1
    raise ValueError("bad conversion")


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """تبدیلِ شمسی به میلادی با اعتبارسنجیِ ورودی (ماه ۱–۱۲ و روزِ موجود در همان ماه).

    پیش از این، ورودیِ نامعتبر (مثل ۳۰ اسفندِ سالِ غیرکبیسه یا ماهِ ۱۳) بی‌صدا به یک
    تاریخِ غلط تبدیل می‌شد؛ ممیزیِ ۲۰۲۶-۱۱-۲۲ این را به‌عنوانِ نقصِ موتور ثبت کرد.
    """
    if not 1 <= jm <= 12:
        raise ValueError(f"ماهِ شمسی نامعتبر: {jm}")
    if not 1 <= jd <= 31:
        raise ValueError(f"روزِ شمسی نامعتبر: {jd}")
    length = 31 if jm <= 6 else 30 if jm <= 11 else (30 if (jy % 33) in (1, 5, 9, 13, 17, 22, 26, 30) else 29)
    if jd > length:
        raise ValueError(f"روز {jd} در ماه {jm} سال {jy} وجود ندارد")
    return _jalali_to_gregorian_unchecked(jy, jm, jd)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    date(gy, gm, gd)  # اعتبارسنجیِ تاریخِ میلادی (ماه/روزِ نامعتبر باید خطا بدهد)
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    jy = 0 if gy <= 1600 else 979
    gy -= 621 if gy <= 1600 else 1600
    gy2 = gy + 1 if gm > 2 else gy
    days = 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return jy, jm, jd


def jdn_jalali(jy: int, jm: int, jd: int) -> int:
    return date(*jalali_to_gregorian(jy, jm, jd)).toordinal() + 1721425


def jdn_islamic(iy: int, im: int, idd: int) -> int:
    """تقویمِ تربیعی/مدنیِ اسلامی (چرخهٔ ۳۰ساله) — تقریبِ ±۱ روز نسبت به رؤیتِ رسمی."""
    if not 1 <= im <= 12:
        raise ValueError(f"ماهِ قمری نامعتبر: {im}")
    if not 1 <= idd <= 30:
        raise ValueError(f"روزِ قمری نامعتبر: {idd}")
    return idd + math.ceil(29.5 * (im - 1)) + (iy - 1) * 354 + (3 + 11 * iy) // 30 + 1948440 - 1


def islamic_from_jdn(jdn: int) -> tuple[int, int, int]:
    iy = (30 * (jdn - 1948440) + 10646) // 10631
    im = min(12, math.ceil((jdn - 29 - jdn_islamic(iy, 1, 1)) / 29.5) + 1)
    while jdn_islamic(iy, im, 1) > jdn:
        im -= 1
    idd = jdn - jdn_islamic(iy, im, 1) + 1
    return iy, im, idd


def month_len(jy: int, jm: int) -> int:
    if not 1 <= jm <= 12:
        raise ValueError(f"ماهِ شمسی نامعتبر: {jm}")
    g1 = date(*_jalali_to_gregorian_unchecked(jy, jm, 1))
    nxt = (jy, jm + 1, 1) if jm < 12 else (jy + 1, 1, 1)
    return (date(*_jalali_to_gregorian_unchecked(*nxt)) - g1).days


def lunar_occurrence(jy: int, lm: int, ld: int) -> tuple[int, int, int] | None:
    """تاریخِ شمسیِ (lm، ld) قمری در سالِ شمسی jy — با تقویمِ تربیعی."""
    lo = jdn_jalali(jy, 1, 1)
    hi = jdn_jalali(*( (jy + 1, 1, 1) ))
    approx_iy = int((lo - 1948440) * 30 / 10631) + 1
    for iy in range(approx_iy - 2, approx_iy + 3):
        j = jdn_islamic(iy, lm, ld)
        if lo <= j < hi:
            return gregorian_to_jalali(*date.fromordinal(j - 1721425 + 1).timetuple()[:3])
    return None


# ---------- کاتالوگ ----------
def parse_event_year(title: str) -> int | None:
    m = re.search(r"(1[23]\d{2})\s*(?:ه[‌.]?ش|هجری شمسی)", title)
    if not m:
        m = re.search(r"(1[23]\d{2})", title)
    return int(m.group(1)) if m else None


def categorize(e: dict) -> str:
    t = e["title"]
    cal = e["calendar"]
    if any(k in t for k in CULTURAL):
        return "cultural"
    if cal == "lunar":
        return "religious"
    if cal == "gregorian":
        return "international"
    if HISTORICAL_MARK.search(t) or parse_event_year(t) is not None:
        return "historical"
    return "official"


SPLIT = re.compile(r"\s*[·؛]\s*|\s+و\s+(?=(?:روز|شهادت|ولادت|رحلت|عید|آغاز|سالروز|فتح|ملی|پیروزی|قیام|انفجار|تأسیس|تشکیل|هجوم|عملیات|درگذشت|ارتحال|بازگشت|حمله|انقلاب|کودتا|صدور|افتتاح|تکریم|بزرگداشت|وفات|میلاد|شب))")


def first_clause(title: str) -> str:
    """از عنوانِ چندرویدادی، فقط رویدادِ اول را نگه می‌دارد."""
    parts = re.split(r"\s+[-–]\s+|\s+و\s+(?=(?:روز|شهادت|ولادت|رحلت|عید|آغاز|سالروز|فتح|ملی|پیروزی|قیام|انفجار|تأسیس|تشکیل|هجوم|عملیات|درگذشت|ارتحال|بازگشت|حمله|انقلاب|کودتا|صدور|افتتاح|تکریم|بزرگداشت|وفات|میلاد|شب))", title)
    out = parts[0]
    for m in ("روز", "شهادت", "ولادت", "رحلت", "وفات", "میلاد", "عید", "آغاز", "سالروز",
              "فتح", "قیام", "انفجار", "تأسیس", "تشکیل", "درگذشت", "ارتحال", "بازگشت", "حمله"):
        idx = out.find(" " + m, 6)
        if idx > 0:
            out = out[:idx]
    out = re.sub(r"\s+روز\s+.*$", "", out) if len(out) > 8 else out
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip(" -،.()")


def _norm(t: str) -> str:
    t = t.replace("‌", " ").replace("‏", " ").replace("‎", " ")
    t = t.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه").replace("ۀ", "ه")
    t = t.replace("وهلال", "هلال").replace("و هلال", "هلال")
    t = re.sub(r"[ً-ْ]", "", t)
    t = re.sub(r"[\(\)\[\]«»\-–—،؛:.,!?'\/]", " ", t)
    t = re.sub(r"[\d۰-۹]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


KEYWORDS = ("نیمه شعبان", "ملی شدن", "پیروزی انقلاب", "شب قدر", " عاشورا", "تاسوعا", "اربعین",
            "مبعث", "غدیر", "فطر", "قربان", "معراج", "اسرا", "اعتکاف", "ولادت", "شهادت",
            "رحلت", "وفات", "میلاد", "نوروز", "یلدا", "سیزده", "مهرگان", "سده", "تیرگان",
            "خردادگان", "انقلاب", "نفت", "بهمن", "قدس", "فلسطین")
STOP = ("حضرت", "امام", "سعید", "مبارک", "روز", "عید", "سالروز", "شب", "هجری", "قمری",
        "ه‍", "ق", "سال", "قبل", "هش", "سلام", "الله", "علیه", "علیها", "و", "آله")


def normalize_spelling(t: str) -> str:
    """یکسان‌سازیِ املا و فاصلهٔ عبارت‌های افتخاری/جغرافیایی در عنوان‌ها.

    دادهٔ PDF و پک هر کدام یک شکل نوشته‌اند؛ بدونِ این مرحله یک رویداد با دو املا
    دو ردیف می‌شود و کاربر «غلط املایی» می‌بیند.
    """
    t = re.sub(r"آیت[\s\u200c]*الله", "آیت\u200cالله", t)
    t = re.sub(r"بیت[\s\u200c]*المقدس", "بیت\u200cالمقدس", t)
    t = re.sub(r"صلی[\s\u200c]*الله[\s\u200c]*علیه[\s\u200c]*و[\s\u200c]*آله",
               "صلی الله علیه و آله", t)
    t = re.sub(r"سلام[\s\u200c]*الله[\s\u200c]*علیها", "سلام الله علیها", t)
    t = re.sub(r"علیه[\s\u200c]*السلام", "علیه\u200cالسلام", t)
    t = t.replace("السلاممؤسس", "السلام مؤسس")
    t = t.replace("منافقوان", "منافقان").replace("مسؤوالن", "مسئولان")
    t = re.sub(r"امام\s+ت\s+", "امامت ", t)
    for w in ("معصومه", "زهرا", "خدیجه", "زینب", "فاطمه"):
        t = t.replace(w + "سلام", w + " سلام")
    return t


def clean_title(t: str) -> str:
    """پاک‌سازیِ املا و زوائدِ ستون‌های PDF در عنوانِ رویداد."""
    t = (t or "").replace("ي", "ی").replace("ك", "ک")
    # عنوان‌های به‌هم‌ریختهٔ استخراج که با متنِ همان سطر بازسازی می‌شوند
    if "سالروز ازدواج" in t:
        return "سالروز ازدواج حضرت علی علیهالسلام و حضرت فاطمه سلامالله علیها"
    if "طالقانی" in t and "عاشورای حسینی" in t:
        return "عاشورای حسینی"
    if "به روایتی" in t and "سلامالله علیها" in t and "فاطمه" not in t:
        return "شهادت حضرت فاطمه زهرا سلامالله علیها (به روایتی)"
    if "زائران حرم رضوی" in t and t.rstrip().endswith("عاشورای"):
        return "شهادت زائران حرم رضوی (ع) به دست ایادی آمریکا"
    if t.startswith("سالروز صدور فرمان") and "تبلیغات" in t:
        return "سالروز صدور فرمان حضرت امام خمینی (رحمةالله علیه) مبنی بر تأسیس سازمان تبلیغات اسلامی"
    if "بهشتی" in t and "72 تن" in t:
        return "شهادت مظلومانه آیتالله دکتر بهشتی و ۷۲ تن از یاران امام خمینی"
    if "کاپیتولاسیون" in t and "خمینی" in t:
        return "اعتراض و افشاگری حضرت امام خمینی علیه پذیرش کاپیتولاسیون"
    if "بازگشت" in t and "خمینی" in t and "ایران" in t:
        return "بازگشت حضرت امام خمینی (رحمةالله علیه) به ایران"
    if "تبلیغات" in t and "خمینی" in t:
        return "سالروز صدور فرمان حضرت امام خمینی (رحمةالله علیه) مبنی بر تأسیس سازمان تبلیغات اسلامی"
    t = re.split(r'"\s*"', t)[0]
    t = t.replace('"', "").replace("“", "").replace("”", "")
    # زوائدِ تاریخ/تقویم در انتهای عنوان (مثل «1358)ه.ش» یا «1357 ه‍.ش(و»)
    t = re.sub(r"\s*[\(\{]?\s*\d{1,4}\s*[\)\}]?\s*ه[\u200c\u200d.\s]*[شق]\s*[\)\}]?\s*(?:[\(\{]\s*و?\s*[\)\}]?)?\s*$", "", t)
    t = re.sub(r"\s*[\(\{]?\s*\d{1,4}\s*[\)\}]?\s*ه[\u200c\u200d.\s]*[شق]\s*[\)\}]?\s*به\s+روایتی\s*$", "", t)
    # تاریخِ تقویمیِ داخلِ عنوان: «( 1361 ه‍.ش)» یا «1342 ه.ش»
    t = re.sub(r"[\(\{]\s*\d{1,4}\s*ه[\u200c\u200d.\s]*[شق]\s*[\)\}]", " ", t)
    t = re.sub(r"\s*\d{1,4}\s*ه[\u200c\u200d.\s]*[شق]\s*", " ", t)
    # هر نشانهٔ باقی‌ماندهٔ تقویمی، هرجای عنوان
    t = re.sub(r"[\(\{]?\s*\d{0,4}\s*-?\s*ه[\u200c\u200d.]+\s*[شق]\s*[\)\}]?", " ", t)
    t = re.sub(r"\bه\s+[قش]\b|\b[قش]\s+ه\b", " ", t)
    # پرانتزِ معکوس: «)رحمة الله علیه(»
    t = re.sub(r"\)([^()]+)\(", r" (\g<1>) ", t)
    if t.count("(") != t.count(")"):
        t = t.replace("(", " ").replace(")", " ")
    # املاهای رایج
    t = re.sub(r"آیت\s*ا+لله", "آیتالله", t)
    t = re.sub(r"ا+لله", "الله", t)
    t = t.replace("سلاماالله", "سلامالله").replace("صلیاالله", "صلیالله")
    t = t.replace("علیه السلام", "علیهالسلام").replace("علیهسلام", "علیهالسلام")
    t = re.sub(r"صلی\s*الله\s*علیه\s*و\s*آله", "صلیاللهعلیهوآله", t)
    t = re.sub(r"سلام\s*الله\s*علیها", "سلامالله علیها", t)
    t = re.sub(r"رحمة[‌‍\s]*ه?[‌‍\s]*الله[‌‍\s]*علیه", "رحمةالله علیه", t)
    t = t.replace("رحمةهاللهعلیه", "رحمةالله علیه").replace("رحمةاللهعلیه", "رحمةالله علیه")
    t = re.sub(r"(?<!رحم)ة", "ه", t)
    t = t.replace("مظلومانة", "مظلومانه").replace("مظلومانۀ", "مظلومانه").replace("ددمنشانة", "ددمنشانه").replace("توسعة", "توسعه")
    t = t.replace("بیابان زدایی", "بیابان‌زدایی")
    t = re.sub(r"(فاطمه)[‌‍\s]*(زهرا)", r"\g<1> \g<2>", t)
    t = re.sub(r"(موسی)[‌‍\s]*(کاظم)", r"\g<1> \g<2>", t)
    t = re.sub(r"(کاظم)\s*(علیهالسلام)", r"\g<1> \g<2>", t)
    t = re.sub(r"(امام)[‌‍]*(رضا|حسن|حسین|سجاد|باقر|صادق|کاظم|جواد|هادی|عسکری|مهدی|زمان)", r"\g<1> \g<2>", t)
    # چسبیدنِ واژه‌های آغازین
    for p in ("آیتالله", "شهادت", "ولادت", "رحلت", "وفات", "امام", "حضرت", "عید", "هفته", "سالگرد", "تأسیس"):
        t = re.sub(r"(?<![\u0600-\u06FF\u200c\u200d])" + p + r"(?=[؀-ۿ])", p + " ", t)
    t = re.sub(r"([^\s(])\(([^()]+)\)", r"\g<1> (\g<2>)", t)
    t = re.sub(r"\s+و\s*$", "", t)
    t = re.sub(r"[\(\{]\s*و?\s*[\)\}]", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -،.؛:()")
    # گیومهٔ بازِ جامانده (مثل «جوادالائمه) با بستنِ آن کامل می‌شود.
    if t.count("«") > t.count("»"):
        t += "»" * (t.count("«") - t.count("»"))
    return normalize_spelling(t)


def signature(title: str) -> str:
    """کلیدِ معناییِ رویداد برای ادغامِ املاهای یک رویداد."""
    n = _norm(title)
    for k in KEYWORDS:
        kk = k.strip()
        if kk in n:
            rest = n.split(kk, 1)[1].split()
            nxt = next((w for w in rest if w not in STOP and len(w) > 2), "")
            return (kk + nxt).replace(" ", "")
    toks = [w for w in n.split() if w not in STOP and len(w) > 2]
    return "".join(toks[:3])


def split_events(title: str) -> list[str]:
    """عنوان‌های چندرویدادیِ PDF را به رویدادهای تک‌جمله‌ای می‌شکند."""
    parts = [p.strip(" -،.()") for p in SPLIT.split(title)]
    out = [p for p in parts if len(p) >= 8 and re.search(r"[؀-ۿ]{3,}", p)]
    return out or ([title] if title else [])


HONOR = ("سلام‌الله علیها", "سلام الله علیها", "سلام‌الله علیه", "سلام الله علیه",
         "علیه‌السلام", "علیه السلام", "صلی‌الله علیه و آله", "صلی الله علیه و آله",
         "صلی‌الله علیه وآله", "صلی الله علیه وآله", "رحمةالله علیه", "رحمة الله علیه",
         "قدس‌الله نفسه الزکیه", "قدس الله نفسه الزکیه")


def _key(t: str) -> str:
    t = re.sub(r"\([^)]*\)", "", t)
    t = re.sub(r"[\d۰-۹]+", "", t)
    for h in HONOR:
        t = t.replace(h, " ")
    t = re.sub(r"[،؛:().«»\-\s]+", " ", t)
    t = t.replace("روز ", " ").replace("عید ", " ")
    return t.strip()[:30]


RELIGIOUS_START = ("شهادت", "ولادت", "رحلت", "عید", "وفات", "مبعث", "اربعین", "تاسوعا",
                   "میلاد", "شب قدر", "اعتکاف", "غدیر", "قربان", "فطر", "سالروز", "عاشورا")


MARKERS = ("آغاز", "عید", "شهادت", "ولادت", "رحلت", "وفات", "میلاد", "سالروز", "عاشورا", "فتح",
           "ملی شدن", "پیروزی", "قیام", "انفجار", "تأسیس", "تشکیل", "روز", "شب", "اربعین",
           "تاسوعا", "مبعث", "درگذشت", "ارتحال", "بازگشت", "حمله", "انقلاب", "کودتا", "صدور")


def _clean(title: str) -> bool:
    """فقط عنوان‌هایی که یک رویدادِ مستقل‌اند (نه چسبیده به چند رویداد)."""
    if not (8 <= len(title) <= 75):
        return False
    if title.count(" و ") > 1 or "·" in title:
        return False
    if len(re.findall(r"\d{4}", title)) > 1:
        return False
    if not title.startswith(MARKERS):
        return False
    # شمارشِ نشانه‌های شروعِ رویداد در بقیهٔ عنوان؛ بیش از یکی یعنی چند رویداد چسبیده
    rest = title
    for m in MARKERS:
        if rest.startswith(m):
            rest = rest[len(m):]
            break
    INTERNAL = ("آغاز", "عید", "شهادت", "ولادت", "رحلت", "وفات", "میلاد", "سالروز",
                "فتح", "قیام", "انفجار", "تأسیس", "تشکیل", "درگذشت", "ارتحال", "بازگشت", "کودتا")
    if any(f" {m}" in rest or f"({m}" in rest for m in INTERNAL):
        return False
    return bool(re.search(r"[؀-ۿ]{4,}", title))


MONTHS_FA = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
             "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
GREG_MONTHS_FA = ("ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن", "ژوئیه",
                  "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر")
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# تاریخِ «ثبت/اعلام» رویدادهایی که سالِ داده کافی نیست (منبع در docs/verification.md)
ORIGIN_OVERRIDES = (
    (("روز جهانی قدس", "روز قدس"), (1358, 5, 16), "اعلام", "https://en.wikipedia.org/wiki/Quds_Day"),
    (("ملی شدن صنعت نفت",), (1329, 12, 29), "تصویب قانون",
     "https://www.mohammadmossadegh.com/news/iran-oil-nationalization-law-1951/"),
    (("پیروزی انقلاب",), (1357, 11, 22), "وقوع",
     "https://en.wikipedia.org/wiki/Anniversary_of_the_Iranian_Revolution"),
    (("شهادت امام خامنه", "شهادت آیت‌الله خامنه"), (1404, 12, 9), "وقوع", "دادهٔ کاربر"),
)


def fa_date(jy: int, jm: int, jd: int) -> str:
    return f"{str(jd).translate(FA_DIGITS)} {MONTHS_FA[jm - 1]} {str(jy).translate(FA_DIGITS)}"


def fa_greg(gy: int, gm: int, gd: int) -> str:
    return f"{str(gd).translate(FA_DIGITS)} {GREG_MONTHS_FA[gm - 1]} {str(gy).translate(FA_DIGITS)}"


def event_origin(entry: dict) -> dict:
    """تاریخِ ثبت/اعلامِ رویداد برای نمایش در پرانتز؛ با منبعِ صادقانه یا برچسبِ سنتی."""
    title = _norm(entry["title"])
    for keys, (jy, jm, jd), note, source in ORIGIN_OVERRIDES:
        if any(k in title for k in keys):
            return {"kind": "established", "label": fa_date(jy, jm, jd), "note": note,
                    "gregorian": "-".join(map(str, jalali_to_gregorian(jy, jm, jd))), "source": source}
    if "روز جهانی آب" in title:
        return {"kind": "established", "label": fa_greg(1993, 3, 22), "note": "نخستین بزرگداشت (تصویب ۱۹۹۲)",
                "gregorian": "1993-03-22", "source": "https://www.un.org/en/observances/water-day/background"}
    cat = entry["category"]
    if cat == "historical":
        year = parse_event_year(entry["title"]) or (entry["years"][0] if entry["years"] else None)
        dates = entry["solar_dates"]
        if year and dates:
            m, d = dates[0]
            try:
                g = jalali_to_gregorian(year, m, d)
            except ValueError:
                return {"kind": "event", "label": f"سال {year}", "note": "وقوع (تاریخِ روزِ نامعتبر در داده)",
                        "gregorian": "", "source": "دادهٔ PDF"}
            return {"kind": "event", "label": fa_date(year, m, d), "note": "وقوع",
                    "gregorian": "-".join(map(str, g)), "source": "دادهٔ PDF"}
    if cat == "official":
        if entry["years"]:
            y = entry["years"][0]
            if entry["solar_dates"]:
                m, d = entry["solar_dates"][0]
                return {"kind": "first-seen", "label": f"نخستین ثبت: {fa_date(y, m, d)}",
                        "note": "اولین سالِ مشاهده در جدول", "gregorian": "",
                        "source": "data/official-calendar-*.json"}
            return {"kind": "first-seen", "label": f"نخستین ثبت: سال {y}",
                    "note": "اولین سالِ مشاهده در جدول (تاریخِ شمسی ثبت نشده)",
                    "gregorian": "", "source": "data/official-calendar-*.json"}
    if cat == "international":
        if entry["years"]:
            y = entry["years"][0]
            gm, gd = (entry["gregorian_dates"] or [[0, 0]])[0]
            gy = jalali_to_gregorian(y, 1, 1)[0]
            if not (1 <= gm <= 12 and 1 <= gd <= 31):
                return {"kind": "first-seen", "label": f"نخستین ثبت: سال {y}",
                        "note": "اولین سالِ مشاهده (تاریخِ میلادی در داده ناقص است)",
                        "gregorian": "", "source": "دادهٔ PDF"}
            jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
            return {"kind": "first-seen", "label": f"نخستین ثبت: {fa_greg(gy, gm, gd)} — {fa_date(jy, jm, jd)}",
                    "note": "اولین سالِ مشاهده در داده (میلادی و معادل شمسی)",
                    "gregorian": f"{gy}-{gm:02d}-{gd:02d}", "source": "دادهٔ PDF"}
    if cat == "cultural":
        return {"kind": "tradition", "label": "سنتی", "note": "آیینِ سالانه، بدون تاریخِ ثبت", "gregorian": "",
                "source": ""}
    m = re.search(r"(\d{1,3})\s*ه", entry["title"])
    if m:
        return {"kind": "tradition", "label": f"سنت ({m.group(1)} ه.ق)", "note": "مناسبتِ مذهبی",
                "gregorian": "", "source": ""}
    return {"kind": "tradition", "label": "سنت قمری", "note": "مناسبتِ مذهبی", "gregorian": "", "source": ""}


CURATED_CULTURAL = [
    ("عید نوروز (روز دوم)", 1, 2), ("عید نوروز (روز سوم)", 1, 3), ("عید نوروز (روز چهارم)", 1, 4),
    ("سیزده‌بدر (روز طبیعت)", 1, 13),
    ("خردادگان", 3, 6),
    ("تیرگان", 4, 13),
    ("مهرگان", 7, 16),
    ("یلدا (شب چله)", 9, 30),
    ("سده", 11, 10),
]


def _build_catalog_from_sources() -> dict:
    events = json.loads((DATA / "events.json").read_text(encoding="utf-8"))
    files = [int(p.stem.split("-")[-1]) for p in DATA.glob("official-calendar-*.json")]
    last_year, first_data = max(files), min(files)
    merged: dict[str, dict] = {}
    for e in events:
        years = sorted(set(e["years"]))
        title = e["title"].strip()
        if "سالروز ازدواج" in title:
            title = "سالروز ازدواج حضرت علی علیهالسلام و حضرت فاطمه سلامالله علیها"
        elif "طالقانی" in title and "عاشورای حسینی" in title:
            title = "عاشورای حسینی"
        elif "به روایتی" in title and "سلامالله علیها" in title:
            title = "شهادت حضرت فاطمه زهرا سلامالله علیها (به روایتی)"
        else:
            title = first_clause(title)
        if not years or not _clean(title):
            continue
        cal = e["calendar"]
        if cal == "solar" and len(e["solar_dates"]) != 1:
            continue
        if cal == "lunar" and len(e["lunar_dates"]) != 1:
            continue
        if cal == "gregorian" and len(e["gregorian_dates"]) != 1:
            continue
        if "روز جهانی قدس" in title or "روز قدس" in title:
            continue
        elif any(k in title for k in CULTURAL):
            category = "cultural"
            fixed = next(((m, d) for k, m, d in (
                ("نوروز", 1, 1), ("سیزده", 1, 13), ("خردادگان", 3, 6), ("تیرگان", 4, 13),
                ("مهرگان", 7, 16), ("یلدا", 9, 30), ("سده", 11, 10)) if k in title), None)
            if cal != "solar" or not fixed or e["solar_dates"] != [list(fixed)]:
                continue
        elif cal == "lunar" and title.startswith(RELIGIOUS_START):
            category = "religious"
        elif cal == "gregorian" and title.startswith("روز"):
            category = "international"
        elif cal == "solar" and (HISTORICAL_MARK.search(title) or parse_event_year(title)):
            category = "historical"
        elif cal == "solar" and title.startswith("روز"):
            category = "official"
        else:
            continue
        first = years[0]
        if category == "historical":
            first = parse_event_year(title) or first
        if category in ("cultural", "religious", "international"):
            first = 1300
        entry = {
            "title": title,
            "raw_title": e["title"],
            "category": category,
            "calendar": cal,
            "solar_dates": e["solar_dates"],
            "lunar_dates": e["lunar_dates"],
            "gregorian_dates": e["gregorian_dates"],
            "first_year": first,
            "years": years,
            "holiday": bool(e["holiday_years"]),
            "unresolved": False,
        }
        if "روز جهانی قدس" in title or "روز قدس" in title:
            entry["category"] = "official"
            entry["calendar"] = "lunar"
            entry["lunar_dates"] = [[9, 30]]
            entry["first_year"] = 1358
            entry["holiday"] = True
        entry["origin"] = event_origin(entry)
        if category == "official":
            entry["in_last_year"] = last_year in years
            entry["recent5"] = len([y for y in years if y >= last_year - 4])
        if "روز جهانی قدس" in title or "روز قدس" in title:
            md = [9, 30]
        else:
            md = (e["lunar_dates"] if cal == "lunar" else
              e["gregorian_dates"] if cal == "gregorian" else
              e["solar_dates"] or e["lunar_dates"] or e["gregorian_dates"] or [[0, 0]])[0]
        if category in ("official", "international"):
            sig = "".join([w for w in _norm(title).split() if w not in STOP][:4])
        else:
            sig = signature(title)
        k = f"{category}|{cal}|{md[0]}-{md[1]}|{sig}"
        if k in merged:
            merged[k]["years"] = sorted(set(merged[k]["years"]) | set(years))
            merged[k]["holiday"] = merged[k]["holiday"] or entry["holiday"]
            if len(title) < len(merged[k]["title"]):
                merged[k]["title"] = title
            if category == "official":
                merged[k]["in_last_year"] = merged[k].get("in_last_year") or entry["in_last_year"]
                merged[k]["recent5"] = max(merged[k].get("recent5", 0), entry["recent5"])
        else:
            merged[k] = entry
    quds_origin = {"kind": "established", "label": fa_date(1358, 5, 16), "note": "اعلام",
                   "gregorian": "-".join(map(str, jalali_to_gregorian(1358, 5, 16))),
                   "source": "https://en.wikipedia.org/wiki/Quds_Day"}
    merged["quds-canonical"] = {
        "title": "روز جهانی قدس", "category": "official", "calendar": "lunar",
        "solar_dates": [[12, 29]], "lunar_dates": [[9, 30]], "gregorian_dates": [],
        "first_year": 1358, "years": list(range(1382, 1407)), "holiday": True,
        "unresolved": False, "in_last_year": True, "recent5": 5, "origin": quds_origin,
        "source": "canonical-lunar",
    }
    for title, m, d in CURATED_CULTURAL:
        if any(x["category"] == "cultural" and x["solar_dates"] == [[m, d]] for x in merged.values()):
            continue
        merged[f"curated-{m}-{d}"] = {
            "title": title, "category": "cultural", "calendar": "solar",
            "solar_dates": [[m, d]], "lunar_dates": [], "gregorian_dates": [],
            "first_year": 1300, "years": [], "holiday": False, "unresolved": False,
            "source": "curated-customs",
        }
    # پاسِ دوم — یک رویدادِ قمری ممکن است در سال‌های مختلف ±۱ روز ثبت شده باشد
    def sig_of(x):
        return (x["category"], x["calendar"], signature(x["title"]))

    ordered = sorted(merged.values(), key=lambda x: (x["category"] != "religious", -len(x["years"])))
    final: list[dict] = []
    for x in ordered:
        twin = None
        for y in final:
            if sig_of(x) != sig_of(y):
                continue
            d1 = (x["lunar_dates"] or x["solar_dates"] or x["gregorian_dates"] or [[0, 0]])[0]
            d2 = (y["lunar_dates"] or y["solar_dates"] or y["gregorian_dates"] or [[0, 0]])[0]
            if abs(d1[0] - d2[0]) == 0 and abs(d1[1] - d2[1]) <= 1:
                twin = y
                break
        if twin is None:
            final.append(x)
        else:
            twin["years"] = sorted(set(twin["years"]) | set(x["years"]))
            twin["holiday"] = twin["holiday"] or x["holiday"]
            twin["in_last_year"] = twin.get("in_last_year") or x.get("in_last_year", False)
            twin["recent5"] = max(twin.get("recent5", 0), x.get("recent5", 0))
    cat = final
    for e in cat:
        e["title"] = clean_title(e["title"])
    for e in cat:
        if not e.get("origin"):
            e["origin"] = event_origin(e)
    counts: dict[str, int] = {}
    for c in cat:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    return {"last_data_year": last_year, "first_data_year": first_data,
            "catalog": cat, "counts": counts}


def build_catalog() -> dict:
    """فایلِ یگانهٔ رویدادها را می‌خواند؛ در نبودِ آن، از منابع بازمی‌سازد."""
    master = DATA / "events-master.json"
    if master.exists():
        d = json.loads(master.read_text(encoding="utf-8"))
        events = d["events"]
        counts: dict[str, int] = {}
        for e in events:
            counts[e["category"]] = counts.get(e["category"], 0) + 1
        return {"last_data_year": d["last_data_year"], "first_data_year": d["first_data_year"],
                "catalog": events, "counts": counts, "source": "events-master.json"}
    return _build_catalog_from_sources()


_TOKEN_CACHE: dict[str, set[str]] = {}


def _match_tokens(e: dict) -> set[str]:
    key = e.get("id") or e["title"]
    cached = _TOKEN_CACHE.get(key)
    if cached is None:
        generic = {"ولادت", "شهادت", "رحلت", "وفات", "میلاد", "روز", "عید", "سالروز",
                   "حضرت", "امام", "مراسم", "بزرگداشت", "هجری", "قمری", "شمسی"}
        cached = {w for w in _norm(e["title"]).split() if len(w) >= 4 and w not in generic}
        _TOKEN_CACHE[key] = cached
    return cached


_CANON_CACHE: dict[str, str] = {}


def _canon(t: str) -> str:
    from event_normalize import canon_key  # دوریِ ماژول‌ها: فقط هنگامِ فراخوانی
    v = _CANON_CACHE.get(t)
    if v is None:
        v = canon_key(t)
        _CANON_CACHE[t] = v
    return v


def match_catalog(title: str, catalog: list[dict]) -> dict | None:
    """تطبیقِ محافظه‌کارانهٔ عنوانِ ردیفِ PDF با یک رویدادِ کاتالوگ.

    نسخهٔ پیشین با نسبتِ واژه‌های *خودِ رویداد* امتیاز می‌داد؛ ردیفِ کوتاهِ
    «شهادت مظلومانه آیت‌الله دکتر بهشتی...» به «مصطفی خمینی» می‌چسبید و
    «آغاز نوروز» به یک رویدادِ قمری. اکنون: کلیدِ کانونیِ یکتا، و در نبودش
    پوششِ ≥۶۰٪ واژه‌های *ردیف* + یک واژهٔ متمایز (≥۵ نویسه) + حاشیهٔ ۱۵٪ از
    گزینهٔ دوم. هر ابهام = بدونِ تطبیق، نه تطبیقِ اشتباه.
    """
    key = _canon(title)
    exact = [e for e in catalog if _canon(e["title"]) == key]
    if len(exact) == 1:
        return exact[0]
    generic = {"ولادت", "شهادت", "رحلت", "وفات", "میلاد", "روز", "عید", "سالروز",
               "حضرت", "امام", "مراسم", "بزرگداشت", "هجری", "قمری", "شمسی"}
    row = {w for w in _norm(title).split() if len(w) >= 3 and w not in generic}
    if not row:
        return None
    scored: list[tuple[float, int, dict]] = []
    for e in catalog:
        inter = row & _match_tokens(e)
        if not inter or not any(len(t) >= 4 for t in inter):
            continue
        cov = len(inter) / len(row)
        if cov >= 0.55:
            scored.append((cov, len(inter), e))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.15:
        return None
    return scored[0][2]


def events_in_title(title: str, catalog: list[dict]) -> list[dict]:
    """رویدادهایی که عنوانِ کاملشان داخلِ عنوانِ ردیف آمده است.

    ردیف‌های چسبیدهٔ PDF اغلب بدونِ «و» دو عنوان را کنارِ هم گذاشته‌اند
    («روز بهره‌وری ... روز بزرگداشت ملاصدرا»). اگر مجموعِ عنوان‌های یافته
    دست‌کم ۵۵٪ عنوانِ ردیف را بپوشاند، همان‌ها رویدادهای واقعیِ ردیف‌اند.
    """
    # سال/توضیحِ داخلِ پرانتز بخشی از نامِ رویداد نیست و مانعِ تطبیقِ عنوانِ
    # کاملِ کاتالوگ با ردیفِ PDF می‌شود؛ برای سنجشِ زیررشته حذفش می‌کنیم.
    def bare(s: str) -> str:
        s = s.replace("هٔ", "ه").replace("ة", "ه")
        s = re.sub(r"[،,؛;.]", " ", s)
        return _canon(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s))

    row = bare(title)
    if len(row) < 10:
        return []
    cands: list[tuple[int, dict, str]] = []
    for e in catalog:
        c = bare(e["title"])
        if len(c) >= 8 and c in row:
            cands.append((len(c), e, c))
    cands.sort(key=lambda x: -x[0])
    chosen: list[tuple[int, dict, str]] = []
    ids: set[str] = set()
    for length, e, c in cands:
        if e["id"] in ids:
            continue
        if any(c in cc or cc in c for _, _, cc in chosen):
            continue
        chosen.append((length, e, c))
        ids.add(e["id"])
    if len(chosen) < 2:
        return []
    cover = sum(x[0] for x in chosen) / len(row)
    return [e for _, e, _ in chosen] if cover >= 0.55 else []


def event_dates(entry: dict, year: int) -> list[tuple[int, int, int, bool]]:
    """(ماه، روز، شمسی/میلادی/قمری؟، تقریبی؟) برای یک سال."""
    out: list[tuple[int, int, int, bool]] = []
    if entry["category"] == "official" and ("روز جهانی قدس" in entry["title"] or "روز قدس" in entry["title"]):
        from datetime import date
        last = None
        for ld in range(1, 30):
            got = lunar_occurrence(year, 9, ld)
            if not got:
                continue
            g = date(*jalali_to_gregorian(year, got[1], got[2]))
            if g.weekday() == 4:  # جمعه
                last = (got[1], got[2], g)
        if last:
            return [(last[0], last[1], "lunar", True)]
    cal = entry["calendar"]
    if cal == "solar":
        for m, d in entry["solar_dates"]:
            if m <= 12 and 1 <= d <= month_len(year, m):
                out.append((m, d, "solar", False))
    elif cal == "gregorian":
        for gm, gd in entry["gregorian_dates"]:
            gs = jalali_to_gregorian(year, 1, 1)[0]
            for gy in (gs, gs + 1):
                jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
                if jy == year:
                    out.append((jm, jd, "gregorian", False))
    elif cal == "lunar":
        for lm, ld in entry["lunar_dates"]:
            got = lunar_occurrence(year, lm, ld)
            if got:
                out.append((got[1], got[2], "lunar", True))
    return out


def generate(year: int, catalog: dict) -> dict:
    rows = []
    if catalog["first_data_year"] <= year <= catalog["last_data_year"]:
        path = DATA / f"official-calendar-{year}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            seen = set()
            dropped = 0

            def add_row(display: str, m: int, d: int, ev: dict | None,
                        holiday: bool, approx: bool = False,
                        source: str = "official-pdf") -> None:
                nonlocal dropped
                key = ((m, d), _canon(display))
                if key in seen:
                    dropped += 1  # همان رویداد در همان روز، از پیش آمده
                    return
                seen.add(key)
                rows.append({"title": display, "solar": [year, m, d],
                             "gregorian": list(jalali_to_gregorian(year, m, d)),
                             "lunar": list(islamic_from_jdn(jdn_jalali(year, m, d))),
                             "holiday": holiday, "approx": approx,
                             "category": (ev["category"] if ev else
                                          categorize({"title": display, "calendar": "unresolved"})),
                             "recurrenceType": ev.get("recurrenceType") if ev else None,
                             "eventId": ev.get("id") if ev else None,
                             "verificationStatus": "verified",
                             "origin": ev.get("origin") if ev else None,
                             "source": source, "year": year})

            for r in data["rows"]:
                title = clean_title(r["title"])
                if not re.search(r"[آ-ی]", title) or re.fullmatch(
                        r"[\d\s۰-۹]*(?:چهارشنبه|پنجشنبه|سه‌شنبه|یکشنبه|دوشنبه|شنبه)?[\d\s۰-۹]*", title.strip()):
                    dropped += 1  # ردیفِ سربرگِ تاریخ/روزِ هفته، نه رویداد
                    continue
                from event_normalize import alias_title
                aliased = clean_title(alias_title(title))
                display = aliased if aliased != title else title
                ev = match_catalog(aliased, catalog["catalog"])
                if ev is None:
                    # نامِ کانونیِ تکراری (مثل چهار روزِ نوروز): با تاریخِ همان ردیف جدا کن.
                    cands = [e for e in catalog["catalog"] if _canon(e["title"]) == _canon(aliased)]
                    ev = next((e for e in cands if (e.get("month"), e.get("day")) ==
                               (r["solar"][1], r["solar"][2])), cands[0] if cands else None)
                pm, pd = r["solar"][1], r["solar"][2]
                if ev:
                    # ردیفِ تطبیق‌خورده به تاریخِ کانونیِ خودش می‌رود؛ ردیفِ PDF
                    # درهم‌ادغام است و تاریخش یک روز جابه‌جا می‌شود.
                    m, d, approx = pm, pd, False
                    dates = event_dates(ev, year)
                    # ردیفِ اصلاح‌شده با تاریخِ قطعیِ PDF نبايد به روزِ کانونیِ
                    # تقریبی جابه‌جا شود؛ قانون: هیچ رویدادی بین دو روز جابه‌جا نشود.
                    if dates and not r.get("corrections"):
                        m, d, _kind, approx = min(
                            dates, key=lambda x: abs((x[0] * 31 + x[1]) - (pm * 31 + pd)))
                    add_row(display, m, d, ev, r["holiday"], approx)
                    continue
                # ردیفِ چندرویدادیِ چسبیده بدونِ «و»: عنوان‌های کاملِ کاتالوگ را
                # داخلِ ردیف پیدا کن (پوششِ ≥۵۵٪) و همان‌ها را جدا کن.
                embedded = events_in_title(title, catalog["catalog"])
                if len(embedded) >= 2:
                    first = True
                    for cev in embedded:
                        cm, cd, approx = pm, pd, False
                        dates = event_dates(cev, year)
                        if dates and not r.get("corrections"):
                            cm, cd, _kind, approx = min(
                                dates, key=lambda x: abs((x[0] * 31 + x[1]) - (pm * 31 + pd)))
                        add_row(cev["title"], cm, cd, cev,
                                r["holiday"], approx, "official-split")
                        first = False
                    continue
                # ردیفِ چندرویدادیِ چسبیده: در مرزِ «و» به بندها می‌شکند و هر
                # بند جداگانه تطبیق می‌گیرد (دسته/تقویم/تاریخِ درست).
                clauses = [c.strip() for c in re.split(r"\s+و\s+", title)
                           if len(c.strip()) >= 4 and re.search(r"[آ-ی]", c)]
                pairs: list[tuple[str, dict]] = []
                for c in clauses:
                    cev = match_catalog(clean_title(alias_title(c)), catalog["catalog"])
                    if cev:
                        pairs.append((c, cev))
                # فقط وقتی می‌شکافیم که **همهٔ** بندها رویدادِ کاتالوگ باشند؛ وگرنه
                # تکه‌های نیمه‌کاره («ورزش زورخانه‌ای»، «پیروزی») ساخته می‌شود.
                if len(pairs) >= 2 and len(pairs) == len(clauses):
                    first = True
                    for _c, cev in pairs:
                        cm, cd, approx = pm, pd, False
                        dates = event_dates(cev, year)
                        if dates and not r.get("corrections"):
                            cm, cd, _kind, approx = min(
                                dates, key=lambda x: abs((x[0] * 31 + x[1]) - (pm * 31 + pd)))
                        add_row(cev["title"], cm, cd, cev,
                                r["holiday"], approx, "official-split")
                        first = False
                    continue
                add_row(display, pm, pd, None, r["holiday"], False)
            # مناسبت‌هایی که در جدولِ PDFِ این سال نیامده‌اند (یا ردیفشان در
            # استخراج گم شده) از کاتالوگ تکمیل می‌شوند؛ وگرنه «روز اصناف» و
            # «روز کردستان» در کاتالوگ هستند ولی در هیچ سالی دیده نمی‌شوند.
            base_count = len(rows)
            keys = {(r["solar"][1], r["solar"][2], _canon(r["title"])) for r in rows}
            have = {r.get("eventId") for r in rows if r.get("eventId")}
            for e in catalog["catalog"]:
                if e["id"] in have or e.get("first_year", 9999) > year:
                    continue
                if e.get("calendar") == "unresolved":
                    continue
                etoks = {w for w in _norm(e["title"]).split() if len(w) >= 4}
                if any(_canon(r["title"]) == _canon(e["title"]) or
                       (etoks and etoks <= set(_norm(r["title"]).split())) for r in rows):
                    continue  # همین رویداد با عنوانی دیگر در ردیف‌های PDF هست
                for m, d, kind, approx in event_dates(e, year):
                    ck = (m, d, _canon(e["title"]))
                    if ck in keys:
                        continue
                    keys.add(ck)
                    holiday = bool(e.get("isOfficialHoliday")) and (
                        not e.get("holidayYears") or year in e["holidayYears"])
                    rows.append({"title": e["title"], "solar": [year, m, d],
                                 "gregorian": list(jalali_to_gregorian(year, m, d)),
                                 "lunar": list(islamic_from_jdn(jdn_jalali(year, m, d))),
                                 "holiday": holiday, "approx": approx,
                                 "category": e["category"],
                                 "recurrenceType": e.get("recurrenceType"),
                                 "eventId": e["id"],
                                 "verificationStatus": e.get("verificationStatus") or "unverified",
                                 "origin": e.get("origin") or {
                                     "kind": "catalog", "label": "کاتالوگ", "note": "",
                                     "gregorian": "", "source": "events-master.json"},
                                 "source": "catalog", "year": year})
            rows.sort(key=lambda r: (r["solar"][1], r["solar"][2]))
            return {"year": year, "mode": "data", "rows": rows, "droppedRows": dropped,
                    "addedRows": len(rows) - base_count}

    last = catalog["last_data_year"]
    for e in catalog["catalog"]:
        if e["calendar"] == "unresolved":
            continue
        if year < e["first_year"]:
            continue
        if e["category"] == "official" and year > last:
            if not e.get("in_last_year"):
                continue  # R5: در سالِ آخر حذف شده بود
            if e.get("recent5", 0) < 2:
                continue  # شاهدِ کافیِ تداوم ندارد
        if (e["category"] == "official" and e.get("source") != "canonical-lunar"
                and year >= catalog["first_data_year"]
                and year not in {int(p.stem.split("-")[-1]) for p in DATA.glob("official-calendar-*.json")}):
            # سالِ بدونِ PDF: فقط رسمی‌ای که در ±۳ سالِ مجاور دیده شده (نه احیای مناسبتِ حذف‌شده)
            if not any(abs(y - year) <= 3 for y in e.get("years", [])):
                continue
        holiday_years = e.get("holidayYears") or e.get("holiday_years") or []
        holiday = (year in holiday_years) if holiday_years else e["holiday"]
        for m, d, cal, approx in event_dates(e, year):
            rows.append({"title": e["title"], "solar": [year, m, d],
                         "gregorian": list(jalali_to_gregorian(year, m, d)),
                         "lunar": [], "holiday": holiday, "approx": approx,
                         "category": e["category"], "source": "rule", "year": year,
                         "eventId": e["id"],
                         "recurrenceType": e.get("recurrenceType"),
                         "verificationStatus": ("temporary" if year > last else e.get("verificationStatus")),
                         "origin": e.get("origin")})
    # حذفِ تکرارها
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: (r["solar"][1], r["solar"][2], r["title"])):
        k = (r["solar"][1], r["solar"][2], signature(r["title"]))
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return {"year": year, "mode": "rule", "rows": uniq}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--catalog", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    cat = build_catalog()
    (DATA / "event-catalog.json").write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.catalog:
        print(json.dumps(cat["counts"], ensure_ascii=False), "last", cat["last_data_year"])
    if args.year:
        res = generate(args.year, cat)
        print(f"{args.year}: mode={res['mode']} rows={len(res['rows'])}")
        for r in res["rows"][:8]:
            print(" ", r["solar"], r["title"][:60], r["category"], "تقریبی" if r["approx"] else "")
        if args.out:
            Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
