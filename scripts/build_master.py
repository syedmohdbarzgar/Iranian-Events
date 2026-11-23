"""ساختِ فایلِ یگانهٔ رویدادها: data/events-master.json

مراحل:
  ۱) ساختِ کاتالوگِ خام از منابع (PDF/جدول‌های رسمی).
  ۲) اصلاحیهٔ عنوان‌های به‌هم‌ریخته (`data/event-corrections.json`).
  ۳) هم‌ترازیِ تاریخ با پک‌های منتشرشدهٔ برنامه (مرجعِ تاریخِ قمری/شمسی).
  ۴) ادغامِ تکرارها با کلیدِ کانونی.
  ۵) غنی‌سازی: نوعِ تکرار A–E، قاعدهٔ تاریخ، وضعیتِ اعتبار، منبع، اطمینان.
  ۶) اعتبارسنجی و گزارش.

خروجی: data/events-master.json + reports/master-validation.md
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402
import event_normalize as norm  # noqa: E402

DATA = ROOT / "data"
MASTER = DATA / "events-master.json"
REPORT = ROOT / "reports" / "master-validation.md"
VERIFIED_AT = "2026-11-22"

VALID_CATS = {"cultural", "religious", "historical", "official", "international"}
VALID_CALS = {"solar", "lunar", "gregorian"}
CAT_FA = {"cultural": "فرهنگی/رسومی", "religious": "مذهبی", "historical": "تاریخی",
          "official": "رسمی/ملی", "international": "بین‌المللی"}
CAL_FA = {"solar": "شمسی", "lunar": "قمری", "gregorian": "میلادی"}
GENERIC = {"ولادت", "شهادت", "رحلت", "وفات", "میلاد", "روز", "عید", "سالروز", "حضرت",
           "امام", "مراسم", "بزرگداشت", "هجری", "قمری", "شمسی", "ابراهیم", "اسلام"}


def primary(e: dict, cal: str | None = None) -> list[int] | None:
    cal = cal or e.get("calendar", "solar")
    dates = e.get(f"{cal}_dates") or []
    return list(dates[0]) if dates else None


def event_year_from(text: str) -> int | None:
    y = engine.parse_event_year(text or "")
    if y:
        return y
    return norm.entry_year(text or "")


def expected_system(category: str, title: str) -> str:
    """تقویمِ مورد انتظار برای تطبیق با پک؛ جلوی تبدیلِ نادرستِ مناسبتِ جهانی به شمسی را می‌گیرد."""
    if category == "religious":
        return "ISLAMIC"
    if category == "international":
        return "GREGORIAN"
    return "PERSIAN"


def resolve_category(category: str, title: str, pack: dict | None) -> str:
    """دسته را با شاهدِ پک اصلاح می‌کند؛ مثلاً «شهادت بهشتی» که از ردیفِ قمری
    واردِ دستهٔ مذهبی شده ولی سالروزِ شمسی است، تاریخی می‌شود."""
    if not pack:
        return category
    system = pack.get("system")
    year = event_year_from(pack.get("event", ""))
    if system == "PERSIAN":
        if category == "religious" and year:
            return "historical"
        if category == "international" and "جهانی" not in title and "بین‌المللی" not in title:
            return "official"
    elif system == "ISLAMIC" and category in ("official", "religious"):
        return "religious"
    elif system == "GREGORIAN" and category in ("official", "international"):
        return "international"
    return category


def load_wiki_index() -> dict[str, dict]:
    p = DATA / "wikipedia-verification-all.json"
    if not p.exists():
        return {}
    out = {}
    for row in json.loads(p.read_text(encoding="utf-8")):
        key = norm.canon_key(row.get("title", ""))
        if key and key not in out:
            out[key] = row
    return out


def load_official_index() -> tuple[dict[int, dict], dict[int, dict[tuple[int, int], list[dict]]]]:
    years, by_date = {}, {}
    for p in sorted(DATA.glob("official-calendar-*.json")):
        y = int(p.stem.split("-")[-1])
        doc = json.loads(p.read_text(encoding="utf-8"))
        years[y] = doc
        idx: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for r in doc.get("rows", []):
            s = r.get("solar") or []
            if len(s) == 3:
                idx[(s[1], s[2])].append(r)
        by_date[y] = idx
    return years, by_date


def row_mentions(title: str, row_title: str) -> bool:
    tokens = [w for w in norm.title_tokens(title) if w not in GENERIC and len(w) >= 3]
    if not tokens:
        return False
    hay = engine._norm(row_title)
    return any(t in hay for t in tokens)


def main() -> int:
    base = engine._build_catalog_from_sources()
    classif = {}
    p = DATA / "calendar-classification.json"
    if p.exists():
        classif = json.loads(p.read_text(encoding="utf-8"))
    corrections = norm.load_corrections()
    pack_idx = norm.pack_index()
    wiki_idx = load_wiki_index()
    official_years, official_by_date = load_official_index()
    last_data = base["last_data_year"]

    # ---------- ۲/۳) اصلاحِ عنوان و هم‌ترازی با پک ----------
    aligned: list[dict] = []
    aligned_count = changed_dates = 0
    for e in base["catalog"]:
        raw = e.get("raw_title") or e["title"]
        # عنوانِ پایه از قبل پاک‌سازی و تک‌رویدادی شده؛ نباید دوباره از raw بازسازی شود.
        # raw فقط برای سالِ صریح و تشخیصِ عنوانِ چسبیده استفاده می‌شود.
        base_title = engine.clean_title(e["title"])
        aliased = norm.alias_title(base_title)
        if aliased == base_title:
            aliased = norm.alias_title(engine.clean_title(raw))
        title0 = engine.clean_title(aliased)
        titles = [title0]
        for sp in corrections.get("splits", []):
            if sp["match"] in raw:
                titles = sp["titles"]
                break
        for title in titles:
            pack = norm.pack_for(title, pack_idx)
            if pack and "day" not in pack:
                pack = None  # قاعدهٔ نسبی (nthWeekday/lastDayOfMonth) تاریخِ ثابت ندارد
            if not pack:
                # عنوانِ چسبیدهٔ بازمانده را یک‌بار دیگر به نخستین رویدادِ مستقل کوتاه کن و
                # دوباره با پک تطبیق بده (مثلاً «... و روز جوان شهادت آیت‌الله ...»).
                shorter = engine.clean_title(engine.first_clause(title))
                if shorter and shorter != title:
                    title, pack = shorter, norm.pack_for(shorter, pack_idx)
                    if pack and "day" not in pack:
                        pack = None
            category = resolve_category(e["category"], title, pack)
            use_pack = bool(pack) and pack.get("system") == expected_system(category, title)
            if use_pack:
                cal = norm.SYSTEM_CALENDAR[pack["system"]]
                month, day = int(pack["month"]), int(pack["day"])
                title = engine.clean_title(pack["event"])
                aligned_count += 1
            else:
                cal = e.get("calendar", "solar")
                md = primary(e, cal)
                if not md:
                    continue
                month, day = md
            override = next((o for o in corrections.get("date_overrides", [])
                             if o["match"] in title or o["match"] in raw), None)
            if override:
                cal, month, day = override["calendar"], override["month"], override["day"]
                use_pack = False
            before = primary(e)
            if before and [month, day] != before:
                changed_dates += 1
            dates = {f"{cal}_dates": [[month, day]], "solar_dates": [], "lunar_dates": [], "gregorian_dates": []}
            dates[f"{cal}_dates"] = [[month, day]]
            explicit = event_year_from(title) or event_year_from(raw)
            if pack:
                explicit = event_year_from(pack.get("event", "")) or explicit

            first = int(e.get("first_year", 1300))
            if category == "historical" and explicit:
                first = explicit
            elif category in ("official", "religious") and explicit and explicit < first:
                first = explicit
            if category in ("cultural", "religious", "international") and not explicit:
                first = min(first, 1300)

            entry = {
                **{k: v for k, v in e.items() if k not in
                   ("solar_dates", "lunar_dates", "gregorian_dates", "origin")},
                "title": title,
                "raw_title": raw,
                "category": category,
                "calendar": cal,
                **dates,
                "first_year": first,
                "occurrence_year": explicit if category in ("historical", "official") else None,
                "holiday": bool(e.get("holiday")),
                "app_pack": pack.get("id") if pack else None,
                "pack_aligned": use_pack,
            }
            entry["origin"] = engine.event_origin(entry)
            aligned.append(entry)

    # ---------- ۳ب) واردکردنِ مناسبت‌های پک که در استخراجِ PDF نبودند ----------
    # پک‌های منتشرشدهٔ برنامه ۲۴۲ مناسبتِ معتبر دارند که در PDFهای پروژه نیامده‌اند؛
    # حذف‌شدنشان یعنی «مناسبتِ معتبر به دلیلِ نبود در یک سالِ خاص» از تقویم بیفتد.
    existing_pairs = set()
    for e in aligned:
        md = (e["solar_dates"] or e["lunar_dates"] or e["gregorian_dates"] or [[0, 0]])[0]
        existing_pairs.add((norm.canon_key(e["title"]), md[0], md[1]))
    imported = 0
    for pack_name in ("solar", "lunar", "gregorian"):
        for row in norm.load_packs().get(pack_name, []):
            if "day" not in row or "month" not in row:
                continue
            title = engine.clean_title(row.get("event", ""))
            key = norm.canon_key(title)
            if not key or (key, int(row["month"]), int(row["day"])) in existing_pairs:
                continue
            cal = norm.SYSTEM_CALENDAR.get(row.get("system"), "solar")
            if pack_name == "lunar":
                category = "religious"
            elif pack_name == "gregorian":
                category = "international"
            elif any(k in title for k in ("نوروز", "یلدا", "سیزده", "مهرگان", "سده", "تیرگان", "چهارشنبه‌سوری")):
                category = "cultural"
            elif event_year_from(title) and any(title.startswith(k) for k in
                                               ("شهادت", "ولادت", "رحلت", "وفات", "آغاز", "فتح", "قیام",
                                                "عملیات", "سالروز", "تشکیل", "تأسیس")):
                category = "historical"
            else:
                category = "official"
            explicit = event_year_from(title)
            if category == "historical" and explicit:
                first = explicit
            elif category in ("cultural", "religious"):
                first = 1300
            else:
                years = row.get("years") or []
                first = min(years) if years else 1324
            e = {
                "title": title, "raw_title": title, "category": category, "calendar": cal,
                "solar_dates": [[row["month"], row["day"]]] if cal == "solar" else [],
                "lunar_dates": [[row["month"], row["day"]]] if cal == "lunar" else [],
                "gregorian_dates": [[row["month"], row["day"]]] if cal == "gregorian" else [],
                "first_year": first,
                "occurrence_year": explicit if category == "historical" else None,
                "years": sorted(row.get("years") or []),
                "holiday": bool(row.get("holiday")), "holiday_years": sorted(row.get("holidayYears") or []),
                "in_last_year": False, "recent5": 0,
                "app_pack": row.get("id"), "pack_aligned": True, "source": "app-pack",
            }
            e["origin"] = engine.event_origin(e)
            aligned.append(e)
            existing_pairs.add((key, int(row["month"]), int(row["day"])))
            imported += 1

    # ---------- ۴) ادغام ----------
    merged: dict[tuple, dict] = {}
    origin_rank = {"established": 4, "event": 3, "first-seen": 2, "tradition": 1}
    for e in aligned:
        md = (e["solar_dates"] or e["lunar_dates"] or e["gregorian_dates"] or [[0, 0]])[0]
        key = (e["category"], e["calendar"], md[0], md[1], norm.canon_key(e["title"]))
        if key not in merged:
            e["merged_titles"] = [e["title"]]
            merged[key] = e
            continue
        m = merged[key]
        m["years"] = sorted(set(m.get("years", [])) | set(e.get("years", [])))
        m["holiday"] = m.get("holiday") or e.get("holiday")
        m["holiday_years"] = sorted(set(m.get("holiday_years", [])) | set(e.get("holiday_years", [])))
        m["first_year"] = min(m.get("first_year", 1300), e.get("first_year", 1300))
        m["in_last_year"] = m.get("in_last_year") or e.get("in_last_year", False)
        m["recent5"] = max(m.get("recent5", 0), e.get("recent5", 0))
        m["merged_titles"].append(e["title"])
        if origin_rank.get(e["origin"].get("kind"), 0) > origin_rank.get(m["origin"].get("kind"), 0):
            m["origin"] = e["origin"]
        if len(e["title"]) < len(m["title"]):
            m["title"] = e["title"]

    # ---------- ۵) غنی‌سازی ----------
    official_year_list = sorted(official_years)
    enriched = []
    for e in merged.values():
        cat, cal = e["category"], e["calendar"]
        md = primary(e, cal)
        quds = "روز جهانی قدس" in e["title"]
        variants = {tuple(v) for v in (e.get("solar_dates") or e.get("lunar_dates") or e.get("gregorian_dates") or [])}
        if quds:
            rule, rec = "last_friday_of_ramadan", "E"
        elif cat == "historical":
            rule, rec = "anniversary_solar", "D"
        elif cal == "lunar":
            rule, rec = "fixed_lunar", "C"
        elif cal == "gregorian":
            rule, rec = "fixed_gregorian", "B"
        elif cat == "cultural":
            rule, rec = "fixed_solar", "A"
        elif len(variants) > 1:
            rule, rec = "official_variable", "E"
        else:
            rule, rec = "fixed_solar", "A"

        if rec == "E":
            e["default_month"], e["default_day"] = ((None, None) if quds else (md if md else (None, None)))
            month = day = None
        else:
            e.setdefault("default_month", None)
            e.setdefault("default_day", None)
            month, day = (md if md else [None, None])

        # سالِ شروع برپایهٔ شاهد: جهانی از نخستین مشاهده (نه ۱۳۰۰)، رسمی از نخستین
        # سالِ تقویمِ رسمی؛ فرهنگی/مذهبی سنتی از ۱۳۰۰.
        years_list = sorted(set(e.get("years", [])))
        if cat == "international":
            e["first_year"] = min(years_list) if years_list else 1324
        elif cat == "official" and years_list:
            e["first_year"] = min(e.get("first_year", 1382), min(years_list))

        verified: list[int] = []
        deltas: list[int] = []
        for y in official_year_list:
            if y < e.get("first_year", 1300):
                continue
            occ = engine.event_dates(e, y)
            for m, d, occ_cal, _approx in occ:
                offsets = (0,) if occ_cal == "solar" else (-1, 0, 1)
                for off in offsets:
                    for row in official_by_date[y].get((m, d + off), []):
                        if row_mentions(e["title"], row.get("title", "")):
                            if y not in verified:
                                verified.append(y)
                            if occ_cal == "lunar":
                                deltas.append(off)
                            break
                    else:
                        continue
                    break

        wiki = wiki_idx.get(norm.canon_key(e["title"]))
        if cat == "cultural":
            status = "traditional"
        elif verified:
            status = "verified"
        elif e.get("pack_aligned"):
            status = "partially_verified"
        elif e.get("first_year", 1300) > last_data:
            status = "temporary"
        else:
            status = "unverified"
        confidence = {"verified": "بالا", "partially_verified": "متوسط", "traditional": "متوسط",
                      "temporary": "پایین", "unverified": "پایین"}[status]

        if cat == "international":
            source_name = "سازمان ملل متحد — روزهای جهانی و بین‌المللی"
            source_url = "https://www.un.org/en/observances"
            tier = 2
        elif cat == "cultural":
            source_name = "آیین سنتی ایرانی (بدون سند ثبت رسمی)"
            source_url = ""
            tier = 4
        elif wiki and wiki.get("status") == "page_match":
            source_name = f"ویکی‌پدیای فارسی — {wiki.get('page', '')}"
            source_url = wiki.get("url", "")
            tier = 3
        else:
            source_name = "تقویم رسمی ایران — مؤسسهٔ ژئوفیزیک دانشگاه تهران (جدول‌های ۱۳۸۲–۱۴۰۶)"
            source_url = "https://calendar.ut.ac.ir/"
            tier = 1

        notes = []
        if e.get("app_pack"):
            notes.append(f"هم‌تراز با پک {e['app_pack']}")
        if len(e.get("merged_titles", [])) > 1:
            notes.append(f"ادغام {len(e['merged_titles'])} عنوانِ هم‌رویداد")
        if deltas:
            notes.append(f"اختلافِ محاسبه/جدولِ قمری: {sorted(set(deltas))} روز")
        if cat == "religious" and cal != "lunar":
            notes.append("دستهٔ مذهبی با تقویمِ غیرقمری — نیازمند بازبینیِ دسته")
        if not verified and cat in ("official", "historical"):
            notes.append("در جدول‌های رسمیِ موجود تطبیقِ عنوانی پیدا نشد")

        enriched.append({
            "id": None,
            "title": e["title"],
            "description": f"{CAT_FA[cat]} — {CAL_FA[cal]}؛ {rule.replace('_', ' ')}",
            "signature": engine.signature(e["title"]),
            "category": cat,
            "eventCategory": cat,
            "calendar": cal,
            "calendarType": cal,
            "calendar_display": classif.get(e["title"], {}).get("calendar", cal),
            "calendar_basis": classif.get(e["title"], {}).get("basis", ""),
            "calendar_confidence": classif.get(e["title"], {}).get("confidence", ""),
            "calendar_observations": classif.get(e["title"], {}).get("observations", 0),
            "recurrenceType": rec,
            "dateRule": rule,
            "month": month,
            "day": day,
            "default_month": e.get("default_month"),
            "default_day": e.get("default_day"),
            "occurrenceYear": e.get("occurrence_year"),
            "origin": e.get("origin") or {},
            "first_year": e.get("first_year", 1300),
            "years": sorted(set(e.get("years", []))),
            "solar_dates": e.get("solar_dates", []),
            "lunar_dates": e.get("lunar_dates", []),
            "gregorian_dates": e.get("gregorian_dates", []),
            "isOfficialHoliday": bool(e.get("holiday")),
            "holiday": bool(e.get("holiday")),
            "holidayYears": sorted(set(e.get("holiday_years", []))),
            "in_last_year": bool(e.get("in_last_year", False)),
            "recent5": int(e.get("recent5", 0)),
            "source": e.get("source", "pdf-derived"),
            "sourceName": source_name,
            "sourceUrl": source_url,
            "sourcePublicationDate": None,
            "sourceTier": tier,
            "verificationStatus": status,
            "dateCertainty": "confirmed" if status == "verified" else "unconfirmed",
            "verifiedYears": sorted(set(verified)),
            "lastVerifiedAt": VERIFIED_AT,
            "confidence": confidence,
            "notes": "؛ ".join(notes),
            "appPack": e.get("app_pack"),
            "mergedTitles": e.get("merged_titles", []),
        })

    # ---------- شناسهٔ پایدار ----------
    # آخرین گذرِ املا روی همهٔ عنوان‌ها (حتی عنوان‌هایی که از ادغام آمده‌اند).
    for e in enriched:
        e["title"] = engine.normalize_spelling(e["title"])
        if e.get("merged_titles"):
            e["merged_titles"] = [engine.normalize_spelling(t) for t in e["merged_titles"]]
    enriched.sort(key=lambda x: (x["category"], x["title"]))
    for i, e in enumerate(enriched, 1):
        e["id"] = f"E{i:04d}"

    # ---------- ۵.۵) اصلاحیه‌های هویتیِ مستند ----------
    # رکورد حذف نمی‌شود؛ فقط از خروجیِ تقویم کنار گذاشته می‌شود و مقدار قبلی
    # در correctionHistory باقی می‌ماند.
    errors, warnings = [], []
    identity_path = DATA / "event-identity-corrections.json"
    if identity_path.exists():
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        by_id = {e["id"]: e for e in enriched}
        for corr in identity.get("corrections", []):
            target = by_id.get(corr.get("id"))
            if target is None:
                errors.append(f"اصلاحیه برای شناسهٔ ناموجود: {corr.get('id')}")
                continue
            target["correctionHistory"] = {
                "preserved": corr.get("preserved", {}),
                "reason": corr.get("reason", ""),
                "source": corr.get("source", ""),
                "supersededBy": corr.get("supersededBy"),
            }
            target.update(corr.get("set", {}))
            target["supersededBy"] = corr.get("supersededBy")
            if corr.get("supersededBy") not in by_id:
                errors.append(f"جایگزینِ ناموجود برای {corr.get('id')}: {corr.get('supersededBy')}")

    # ---------- ۶) اعتبارسنجی ----------
    ids = [e["id"] for e in enriched]
    if len(ids) != len(set(ids)):
        errors.append("شناسهٔ تکراری")
    keys = Counter((e["category"], e["calendar"], e["month"], e["day"], norm.canon_key(e["title"]))
                   for e in enriched)
    dups = [k for k, n in keys.items() if n > 1 and k[4]]
    for e in enriched:
        if e["category"] not in VALID_CATS:
            errors.append(f"{e['id']} دستهٔ نامعتبر: {e['category']}")
        if e["calendar"] not in VALID_CALS:
            errors.append(f"{e['id']} تقویم نامعتبر: {e['calendar']}")
        if not e["title"].strip():
            errors.append(f"{e['id']} عنوان خالی")
        if not e["origin"].get("label"):
            errors.append(f"{e['id']} اصل ندارد")
        if not (1200 <= e["first_year"] <= 1430):
            errors.append(f"{e['id']} سالِ شروعِ نامعتبر: {e['first_year']}")
        if e["recurrenceType"] == "C" and not e["lunar_dates"]:
            errors.append(f"{e['id']} قمری بدونِ تاریخِ قمری")
        if e["recurrenceType"] in ("A", "D") and not e["solar_dates"]:
            errors.append(f"{e['id']} شمسی بدونِ تاریخِ شمسی")
        if e["recurrenceType"] == "B" and not e["gregorian_dates"]:
            errors.append(f"{e['id']} میلادی بدونِ تاریخِ میلادی")
        if e["recurrenceType"] == "E" and e["month"] is not None:
            errors.append(f"{e['id']} متغیر با ماهِ ثابت")
        if e.get("excludeFromCalendar") and e["verificationStatus"] == "verified":
            errors.append(f"{e['id']} کنارگذاشته اما verified")
        if e["category"] in ("official", "historical") and e["verificationStatus"] == "unverified":
            warnings.append(f"{e['id']} بدونِ تطبیقِ رسمی: {e['title'][:50]}")
        if e["calendar"] == "solar" and e["solar_dates"]:
            try:
                engine.jalali_to_gregorian(1400, *e["solar_dates"][0])
            except ValueError:
                errors.append(f"{e['id']} تاریخِ شمسیِ نامعتبر: {e['solar_dates'][0]}")
        if re.search(r"(?<![\u0600-\u06FF])ه[‌.\s]*[شق](?![\u0600-\u06FF])|هجری", e["title"]):
            warnings.append(f"{e['id']} نشانهٔ تقویمی در عنوان: {e['title'][:50]}")

    counts = Counter(e["category"] for e in enriched)
    cal_counts = Counter(e["calendar"] for e in enriched)
    rec_counts = Counter(e["recurrenceType"] for e in enriched)
    status_counts = Counter(e["verificationStatus"] for e in enriched)
    master = {
        "version": 2,
        "note": "منبع یگانهٔ رویدادها؛ ساخته‌شده با scripts/build_master.py (نسخهٔ ۲ — ممیزی ۱۳۰۰–۱۴۲۰)",
        "first_data_year": base["first_data_year"],
        "last_data_year": base["last_data_year"],
        "supported_years": [1300, 1420],
        "generatedAt": VERIFIED_AT,
        "counts": dict(counts),
        "calendar_counts": dict(cal_counts),
        "recurrence_counts": dict(rec_counts),
        "verification_counts": dict(status_counts),
        "duplicate_signatures": [f"{k[0]}/{k[1]}/{k[2]}/{k[3]}/{k[4]}" for k in dups],
        "errors": errors,
        "warnings": warnings,
        "events": enriched,
    }
    MASTER.write_text(json.dumps(master, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# اعتبارسنجی فایل یگانهٔ رویدادها (نسخهٔ ۲)", "",
             f"- رویدادها: **{len(enriched)}** (پیش از ادغام: {len(aligned)})",
             f"- هم‌ترازی با پک برنامه: **{aligned_count}** · تاریخِ اصلاح‌شده: **{changed_dates}**",
             "- دسته‌ها: " + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())),
             "- تقویم: " + " · ".join(f"{k}: {v}" for k, v in sorted(cal_counts.items())),
             "- نوع تکرار: " + " · ".join(f"{k}: {v}" for k, v in sorted(rec_counts.items())),
             "- وضعیت اعتبار: " + " · ".join(f"{k}: {v}" for k, v in sorted(status_counts.items())),
             f"- تکرارِ کانونیِ باقی‌مانده: **{len(dups)}**",
             f"- خطا: **{len(errors)}** · هشدار: **{len(warnings)}**", ""]
    if errors:
        lines += ["## خطاها", ""] + [f"- {x}" for x in errors[:100]]
    if warnings:
        lines += ["", "## هشدارها (نیازمند بازبینی)", ""] + [f"- {x}" for x in warnings[:80]]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"events-master.json: {len(enriched)} events (from {len(aligned)}), "
          f"aligned={aligned_count}, dateChanges={changed_dates}, "
          f"errors={len(errors)}, warnings={len(warnings)}, dups={len(dups)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
