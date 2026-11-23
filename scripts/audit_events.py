"""ممیزیِ رویدادها و داده‌های تقویمی — کاتالوگ، خروجی هر سال، پک‌های برنامه.

دامنه:
  • `data/events-master.json` (منبع یگانه)
  • `data/official-calendar-*.json` (جدول‌های رسمی ۱۳۸۲–۱۴۰۶)
  • `data/years/1300..1420.json` (تولید هر سال)
  • `app/src/main/assets/events/iran/*_events.json` (+ نسخه‌های en/ckb)
  • `tools/events/calendar-master.json`

خروجی:
  reports/audit/audit.json          — ماشین‌خوان، شامل همهٔ یافته‌ها
  reports/audit/summary.md          — خلاصه به تفکیک شدت/دسته/سال
  reports/audit/years/<year>.md     — گزارش هر سال
  reports/audit/app-assets.md       — پک‌های همراه برنامه
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402
import event_normalize as norm  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "reports" / "audit"
YEARS_DIR = DATA / "years"
APP_PACK_DIR = ROOT.parent / "app" / "src" / "main" / "assets" / "events" / "iran"
FIRST, LAST = 1300, 1420
GENERIC = {"ولادت", "شهادت", "رحلت", "وفات", "میلاد", "روز", "عید", "سالروز", "حضرت",
           "امام", "مراسم", "بزرگداشت", "هجری", "قمری", "شمسی"}
SEVERITY_FA = {"critical": "بحرانی", "major": "مهم", "minor": "جزئی"}


class Audit:
    def __init__(self) -> None:
        self.issues: list[dict] = []
        self.metrics: dict = {}
        self.year_issues: dict[int, list[dict]] = defaultdict(list)
        self.master: dict = {}
        self.years: dict[int, dict] = {}

    def add(self, sev: str, check: str, msg: str, *, event_id: str | None = None,
            title: str | None = None, year: int | None = None) -> None:
        issue = {"severity": sev, "check": check, "message": msg,
                 "eventId": event_id, "title": title, "year": year}
        self.issues.append(issue)
        if year is not None:
            self.year_issues[year].append(issue)


def norm_tokens(title: str) -> set[str]:
    return {w for w in engine._norm(title).split() if len(w) >= 3 and w not in GENERIC}


def mentions(title: str, row_title: str) -> bool:
    """آیا ردیفِ PDF همین رویداد را می‌آورد؟ کلیدِ کانونی اول، وگرنه چند واژهٔ مشترک.

    «عید نوروز» و «آغاز نوروز» یک واژهٔ مشترک دارند؛ تطبیقِ تک‌واژه‌ای آن‌ها را یکی
    می‌کرد و تاریخِ ۱/۲ را با ۱/۱ می‌سنجید. کلیدِ کانونی این اشتباه را نمی‌کند.
    """
    ck = norm.canon_key(title)
    if ck and ck in norm.canon_key(row_title):
        return True
    toks = norm_tokens(title)
    if not toks:
        return False
    hay = engine._norm(row_title)
    hit = sum(1 for t in toks if t in hay)
    return hit >= min(2, len(toks)) if len(toks) > 1 else False


def valid_jalali(m: int, d: int, year: int = 1400) -> bool:
    try:
        return 1 <= m <= 12 and 1 <= d <= 31 and d <= engine.month_len(year, m)
    except ValueError:
        return False


def audit_master(a: Audit) -> None:
    master = json.loads((DATA / "events-master.json").read_text(encoding="utf-8"))
    a.master = master
    events = master["events"]
    a.metrics["masterEvents"] = len(events)
    a.metrics["masterCounts"] = master.get("counts", {})
    a.metrics["masterRecurrence"] = master.get("recurrence_counts", {})
    a.metrics["masterVerification"] = master.get("verification_counts", {})

    required = ("id", "title", "category", "calendar", "recurrenceType", "dateRule",
                "first_year", "sourceName", "verificationStatus", "lastVerifiedAt", "confidence")
    ids = Counter()
    keys = Counter()
    for e in events:
        ids[e.get("id")] += 1
        for field in required:
            if field not in e or e[field] in (None, "") and field not in ("month", "day"):
                a.add("critical", "M-001", f"فیلد الزامی خالی: {field}", event_id=e.get("id"), title=e.get("title"))
        if not e.get("title", "").strip():
            a.add("critical", "M-001", "عنوان خالی", event_id=e.get("id"))
        if e.get("category") not in ("cultural", "religious", "historical", "official", "international"):
            a.add("critical", "M-001", f"دستهٔ نامعتبر: {e.get('category')}", event_id=e.get("id"), title=e.get("title"))
        if e.get("calendar") not in ("solar", "lunar", "gregorian"):
            a.add("critical", "M-001", f"تقویم نامعتبر: {e.get('calendar')}", event_id=e.get("id"), title=e.get("title"))
        key = (e.get("category"), e.get("calendar"), e.get("month"), e.get("day"), norm.canon_key(e.get("title", "")))
        keys[key] += 1
        if not (1200 <= int(e.get("first_year", 0)) <= LAST):
            a.add("critical", "M-006", f"سالِ شروعِ نامعتبر: {e.get('first_year')}", event_id=e.get("id"), title=e.get("title"))
        rec = e.get("recurrenceType")
        if rec == "C" and (e.get("calendar") != "lunar" or not e.get("lunar_dates")):
            a.add("critical", "M-005", "قمری بدونِ تاریخِ قمری", event_id=e.get("id"), title=e.get("title"))
        if rec == "B" and (e.get("calendar") != "gregorian" or not e.get("gregorian_dates")):
            a.add("critical", "M-005", "میلادی بدونِ تاریخِ میلادی", event_id=e.get("id"), title=e.get("title"))
        if rec in ("A", "D") and (e.get("calendar") != "solar" or not e.get("solar_dates")):
            a.add("critical", "M-005", "شمسی بدونِ تاریخِ شمسی", event_id=e.get("id"), title=e.get("title"))
        if rec == "E" and e.get("month") is not None:
            a.add("major", "M-005", "رویدادِ متغیر با ماهِ ثابت ذخیره شده", event_id=e.get("id"), title=e.get("title"))
        if e.get("calendar") == "lunar" and e.get("lunar_dates"):
            m, d = e["lunar_dates"][0]
            if not (1 <= m <= 12 and 1 <= d <= 30):
                a.add("critical", "M-004", f"تاریخِ قمریِ نامعتبر: {m}/{d}", event_id=e.get("id"), title=e.get("title"))
        if e.get("calendar") == "solar" and e.get("solar_dates"):
            m, d = e["solar_dates"][0]
            max_day = 31 if 1 <= m <= 6 else 30
            if not (1 <= m <= 12 and 1 <= d <= max_day):
                a.add("critical", "M-004", f"تاریخِ شمسیِ نامعتبر: {m}/{d}", event_id=e.get("id"), title=e.get("title"))
            if m == 12 and d == 30 and e.get("recurrenceType") in ("A", "D"):
                a.metrics.setdefault("esfand30Events", []).append(e.get("id"))
        if e.get("calendar") == "gregorian" and e.get("gregorian_dates"):
            m, d = e["gregorian_dates"][0]
            if not (1 <= m <= 12 and 1 <= d <= 31):
                a.add("critical", "M-004", f"تاریخِ میلادیِ نامعتبر: {m}/{d}", event_id=e.get("id"), title=e.get("title"))
        if rec == "D" and e.get("occurrenceYear") and e.get("first_year") != e.get("occurrenceYear"):
            a.add("major", "M-006", "سالِ وقوع با سالِ شروع یکی نیست", event_id=e.get("id"), title=e.get("title"))
        if e.get("category") in ("official", "historical", "international") and not e.get("sourceUrl"):
            a.add("major", "M-008", "بدونِ نشانیِ منبع", event_id=e.get("id"), title=e.get("title"))
        if e.get("verificationStatus") == "unverified":
            a.add("major", "M-007", "رویدادِ تأییدنشده", event_id=e.get("id"), title=e.get("title"))
        if e.get("verificationStatus") == "temporary" and e.get("first_year", 0) <= master.get("last_data_year", 1406):
            a.add("minor", "M-009", "وضعیتِ موقت برای رویدادِ درونِ داده", event_id=e.get("id"), title=e.get("title"))
        if re.search(r"(?<![\u0600-\u06FF])ه[‌.\s]*[شق](?![\u0600-\u06FF])|هجری", e.get("title", "")):
            a.add("minor", "M-010", "نشانهٔ تقویمی در عنوان", event_id=e.get("id"), title=e.get("title"))
        if re.search(r"\s{2,}", e.get("title", "")) or \
                e.get("title", "").count("«") != e.get("title", "").count("»"):
            a.add("minor", "M-010", "فاصله/گیومهٔ نامتوازن در عنوان", event_id=e.get("id"), title=e.get("title"))

    for i, n in ids.items():
        if n > 1:
            a.add("critical", "M-002", f"شناسهٔ تکراری: {i} ×{n}")
    for key, n in keys.items():
        if n > 1:
            a.add("critical", "M-003", f"رویدادِ کانونیِ تکراری: {key[4]} ({key[1]} {key[2]}/{key[3]})")


def audit_years(a: Audit) -> None:
    master = a.master
    last_data = master.get("last_data_year", 1406)
    official_files = {int(p.stem.split("-")[-1]) for p in DATA.glob("official-calendar-*.json")}
    a.metrics["officialYears"] = sorted(official_files)
    a.metrics["missingOfficialYears"] = sorted(set(range(1382, 1407)) - official_files)
    counts = {}
    for y in range(FIRST, LAST + 1):
        p = YEARS_DIR / f"{y}.json"
        if not p.exists():
            a.add("critical", "Y-000", f"فایل سالِ {y} نیست", year=y)
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        rows = doc["rows"]
        a.years[y] = doc
        counts[y] = len(rows)
        seen = Counter()
        matched = 0
        cats = Counter()
        for r in rows:
            cats[r.get("category")] += 1
            title = r.get("title", "")
            if not title.strip():
                a.add("critical", "Y-003", "ردیفِ بدونِ عنوان", year=y)
                continue
            if not re.search(r"[آ-ی]", title) or re.fullmatch(r"[\d\s۰-۹چهارشنبه]+", title):
                a.add("critical", "Y-003", f"عنوانِ مخدوش: {title[:40]}", title=title, year=y)
            s = r.get("solar") or []
            if len(s) != 3 or s[0] != y:
                a.add("critical", "Y-001", f"تاریخِ شمسیِ نامعتبر: {s}", title=title, year=y)
                continue
            if not valid_jalali(s[1], s[2], y):
                a.add("critical", "Y-001", f"تاریخِ نامعتبر: {s[1]}/{s[2]}", title=title, year=y)
            try:
                g = tuple(r["gregorian"])
                if engine.gregorian_to_jalali(*g) != (y, s[1], s[2]):
                    a.add("critical", "Y-001", "تبدیلِ میلادی/شمسی ناسازگار", title=title, year=y)
            except (KeyError, ValueError, TypeError):
                a.add("critical", "Y-001", "میلادیِ نامعتبر/ناقص", title=title, year=y)
            key = (s[1], s[2], norm.canon_key(title))
            seen[key] += 1
            if r.get("eventId"):
                matched += 1
            elif doc["mode"] == "data":
                pass
            if r.get("holiday") and not title.strip():
                a.add("critical", "Y-004", "روزِ تعطیل بدونِ رویداد", year=y)
            if y > last_data and r.get("verificationStatus") not in ("temporary", None):
                a.add("major", "Y-005", "سالِ آینده بدونِ وضعیتِ موقت", title=title, year=y)
        for key, n in seen.items():
            if n > 1:
                a.add("critical", "Y-002", f"ردیفِ تکراری: {key[0]}/{key[1]} {key[2]}", year=y)
        # تطبیق با جدولِ رسمی
        if y in official_files:
            raw = json.loads((DATA / f"official-calendar-{y}.json").read_text(encoding="utf-8"))
            dropped = doc.get("droppedRows", 0)
            if len(rows) + dropped < len(raw.get("rows", [])):
                a.add("critical", "Y-007",
                      f"ردیفِ گم‌شده: جدول {len(raw['rows'])} > خروجی {len(rows)} + حذف‌شده {dropped}", year=y)
            if matched < len(rows):
                a.add("minor", "Y-006", f"{len(rows) - matched} ردیف به رویدادِ کاتالوگ وصل نشد", year=y)
        a.metrics.setdefault("yearRows", {})[y] = {"mode": doc["mode"], "count": len(rows),
                                                  "categories": dict(cats), "matched": matched}
    a.metrics["yearCounts"] = counts
    a.metrics["minYear"] = min(counts, key=counts.get) if counts else None
    a.metrics["maxYear"] = max(counts, key=counts.get) if counts else None


def audit_app_packs(a: Audit) -> None:
    packs = norm.load_packs()
    base_names = ["solar", "lunar", "gregorian", "misc", "kurdish"]
    official_years = {int(p.stem.split("-")[-1]): json.loads(p.read_text(encoding="utf-8"))
                      for p in DATA.glob("official-calendar-*.json")}
    row_index = {}
    for y, doc in official_years.items():
        idx = defaultdict(list)
        for r in doc.get("rows", []):
            s = r.get("solar") or []
            if len(s) == 3:
                idx[(s[1], s[2])].append(r)
        row_index[y] = idx
    pack_report = {}
    pending_bad: list[tuple[str, dict, list[int]]] = []
    for name in base_names:
        rows = packs.get(name, [])
        ids = Counter(r.get("id") for r in rows)
        for i, n in ids.items():
            if n > 1:
                a.add("critical", "A-002", f"پک {name}: شناسهٔ تکراری {i} ×{n}")
        dup = Counter((r.get("system"), r.get("month"), r.get("day"), norm.canon_key(r.get("event", "")))
                      for r in rows)
        for key, n in dup.items():
            if n > 1:
                a.add("major", "A-003", f"پک {name}: ردیفِ تکراری {key[3]} ({key[1]}/{key[2]})")
        checked = matched = mismatch = not_printed = 0
        for r in rows:
            system = r.get("system")
            month, day = r.get("month"), r.get("day")
            if system not in ("PERSIAN", "ISLAMIC", "GREGORIAN"):
                a.add("critical", "A-001", f"پک {name}: سیستمِ نامعتبر {system} ({r.get('id')})")
                continue
            if r.get("type") in ("nthWeekday", "lastDayOfMonth"):
                if "weekday" in r and not (0 <= int(r["weekday"]) <= 6):
                    a.add("critical", "A-001", f"پک {name}: weekday نامعتبر ({r.get('id')})")
                if "occurrence" in r and int(r["occurrence"]) not in (-1, 1, 2, 3, 4, 5):
                    a.add("critical", "A-001", f"پک {name}: occurrence نامعتبر ({r.get('id')})")
                continue
            if not isinstance(month, int) or not 1 <= month <= 12:
                a.add("critical", "A-001", f"پک {name}: ماهِ نامعتبر ({r.get('id')})")
                continue
            if not isinstance(day, int) or not 1 <= day <= 31:
                a.add("critical", "A-001", f"پک {name}: روزِ نامعتبر ({r.get('id')})")
                continue
            if system == "ISLAMIC" and not 1 <= day <= 30:
                a.add("critical", "A-001", f"پک {name}: روزِ قمریِ نامعتبر ({r.get('id')})")
            years = r.get("years") or []
            if years != sorted(years):
                a.add("minor", "A-001", f"پک {name}: سال‌ها مرتب نیستند ({r.get('id')})")
            hy = r.get("holidayYears") or []
            if hy and not set(hy) <= set(years):
                a.add("major", "A-001", f"پک {name}: holidayYears بیرون از years ({r.get('id')})")
            # تطبیق با جدول رسمی همان سال روی **تاریخِ همان روز**، نه کل سال:
            # برای قمری مسیرِ محاسباتی ±۱ روز جست‌وجو می‌شود، ولی تأییدِ نهایی فقط
            # تطبیقِ ماه/روزِ خودِ ردیفِ رسمی با پک است.
            bad_years: list[int] = []
            for y in years:
                if y not in official_years:
                    continue
                checked += 1
                found = ok = False
                candidates: list[tuple[int, int]] = []
                if system == "ISLAMIC":
                    got = engine.lunar_occurrence(y, month, day)
                    if got:
                        candidates = [(got[1], got[2] + off) for off in (-1, 0, 1)]
                elif system == "GREGORIAN":
                    for gy in (engine.jalali_to_gregorian(y, 1, 1)[0],
                               engine.jalali_to_gregorian(y, 1, 1)[0] + 1):
                        try:
                            jy, jm, jd = engine.gregorian_to_jalali(gy, month, day)
                        except ValueError:
                            continue
                        if jy == y:
                            candidates.append((jm, jd))
                else:
                    candidates = [(month, day)]
                for cm, cd in candidates:
                    for row in row_index[y].get((cm, cd), []):
                        if not mentions(r.get("event", ""), row.get("title", "")):
                            continue
                        found = True
                        if system == "ISLAMIC":
                            ok = (row.get("lunar") or [0, 0, 0])[1:] == [month, day]
                        elif system == "GREGORIAN":
                            ok = tuple(row.get("gregorian", [0, 0, 0])[1:]) == (month, day)
                        else:
                            ok = (row.get("solar") or [0, 0, 0])[1:] == [month, day]
                        break
                    if found:
                        break
                if not found:
                    # شاید آن سال چاپ نشده؛ اگر در جای دیگری از همان سال آمده، جابه‌جایی است.
                    found_elsewhere = any(mentions(r.get("event", ""), row.get("title", ""))
                                          for row in official_years[y].get("rows", []))
                    if found_elsewhere:
                        mismatch += 1
                        bad_years.append(y)
                    else:
                        not_printed += 1
                elif ok:
                    matched += 1
                else:
                    mismatch += 1
                    bad_years.append(y)
            if bad_years:
                pending_bad.append((name, r, bad_years))
        pack_report[name] = {"entries": len(rows), "checkedYearOccurrences": checked,
                             "matched": matched, "mismatch": mismatch, "notPrinted": not_printed}

        # هم‌خوانیِ نسخه‌های زبانی
        for lang in ("en", "ckb"):
            lp = APP_PACK_DIR / f"{name}_events.{lang}.json"
            if not lp.exists():
                continue
            loc = json.loads(lp.read_text(encoding="utf-8"))
            base_by_id = {r.get("id"): r for r in rows}
            loc_by_id = {r.get("id"): r for r in loc}
            missing = sorted(set(base_by_id) - set(loc_by_id))
            if missing:
                a.add("major", "A-004", f"پک {name}.{lang}: {len(missing)} شناسهٔ غایب (مثلاً {missing[:3]})")
            for i, row in loc_by_id.items():
                b = base_by_id.get(i)
                if not b:
                    continue
                if (b.get("month"), b.get("day"), b.get("system")) != (row.get("month"), row.get("day"), row.get("system")):
                    a.add("critical", "A-004", f"پک {name}.{lang}: تاریخ/سیستم {i} با پایه یکی نیست")
                if (b.get("years") or []) != (row.get("years") or []):
                    a.add("major", "A-004", f"پک {name}.{lang}: years {i} با پایه یکی نیست")
    # سال‌هایی که چندین مناسبتِ ثابت در تاریخِ خودشان در جدول نیامده‌اند، جدولشان
    # درهم‌ادغام است (ردیفِ PDF چند روز را یک‌جا آورده)؛ به‌جای صدها یافتهٔ تکراری،
    # یک یافته برای همان سال ثبت می‌شود و سال‌های سالم ریز‌به‌ریز می‌مانند.
    year_bad: Counter = Counter()
    for _name, _r, bad in pending_bad:
        year_bad.update(set(bad))
    damaged = {y for y, n in year_bad.items() if n >= 6}
    for y in sorted(damaged):
        a.add("major", "Y-008",
              f"جدول رسمی سال {y} درهم‌ادغام است: {year_bad[y]} مناسبتِ ثابت در تاریخِ خودشان نیامدند؛ "
              "ردیف‌های آن سال برای تأییدِ روزانه قابل استناد نیستند.", year=y)
    for name, r, bad in pending_bad:
        left = [y for y in bad if y not in damaged]
        if left:
            a.add("major", "A-005",
                  f"پک {name}/{r.get('id')}: تاریخِ {r.get('month')}/{r.get('day')} در {len(left)} سال با جدول رسمی "
                  f"نمی‌خواند ({left[:5]})", title=r.get("event"))
    a.metrics["appPacks"] = pack_report

    # هم‌پوشانی با کاتالوگ
    master = a.master
    master_keys = {norm.canon_key(e["title"]) for e in master.get("events", [])}
    master_tokens = [norm.title_tokens(e["title"]) for e in master.get("events", [])]

    def covered(title: str) -> bool:
        if norm.canon_key(title) in master_keys:
            return True
        own = norm.title_tokens(title)
        if not own:
            return False
        return max((len(own & other) / len(own) for other in master_tokens), default=0) >= 0.8

    missing = []
    for name in ("solar", "lunar", "gregorian"):
        for r in packs.get(name, []):
            if not covered(r.get("event", "")):
                missing.append({"pack": name, "id": r.get("id"), "title": r.get("event")})
    a.metrics["packMissingFromMaster"] = missing
    for m in missing[:40]:
        a.add("major", "A-006", f"مناسبتِ پک در کاتالوگ نیست: {m['title']}", title=m["title"])

    # tools/events/calendar-master.json
    tp = ROOT.parent / "tools" / "events" / "calendar-master.json"
    if tp.exists():
        tools_rows = json.loads(tp.read_text(encoding="utf-8"))
        ids = Counter(r.get("id") for r in tools_rows)
        for i, n in ids.items():
            if n > 1:
                a.add("critical", "A-007", f"tools/events: شناسهٔ تکراری {i}")
        for r in tools_rows:
            if r.get("system") not in ("PERSIAN", "ISLAMIC", "GREGORIAN"):
                a.add("critical", "A-007", f"tools/events: سیستمِ نامعتبر ({r.get('id')})")
            if "month" in r and not 1 <= int(r["month"]) <= 12:
                a.add("critical", "A-007", f"tools/events: ماهِ نامعتبر ({r.get('id')})")
            vf, vt = r.get("validFrom"), r.get("validTo")
            if vf and vt and vf > vt:
                a.add("major", "A-007", f"tools/events: بازهٔ سال وارونه ({r.get('id')})")
        a.metrics["toolsMaster"] = {"entries": len(tools_rows),
                                   "withValidFrom": sum(1 for r in tools_rows if r.get("validFrom")),
                                   "withValidTo": sum(1 for r in tools_rows if r.get("validTo"))}

    lines = ["# ممیزیِ پک‌های همراه برنامه", "",
             "پک‌های `app/src/main/assets/events/iran/` با جدول‌های رسمی همان سال مقایسه شدند؛ "
             "برای قمری، تاریخِ محاسباتی با روزِ قمریِ ردیفِ رسمی سنجیده شده است.", "",
             "| پک | ردیف | سال-رخداد بررسی‌شده | تطبیق | اختلافِ قمری | چاپ‌نشده |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, r in pack_report.items():
        lines.append(f"| {name} | {r['entries']} | {r['checkedYearOccurrences']} | {r['matched']} | "
                     f"{r['mismatch']} | {r['notPrinted']} |")
    lines += ["", f"- مناسبت‌های پک که در کاتالوگ نیستند: **{len(missing)}**", ""]
    (OUT / "app-assets.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reports(a: Audit) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "years").mkdir(exist_ok=True)
    sev = Counter(i["severity"] for i in a.issues)
    by_check = Counter(i["check"] for i in a.issues)
    total = len(a.issues)

    # گزارش هر سال
    for y in range(FIRST, LAST + 1):
        doc = a.years.get(y)
        if not doc:
            continue
        info = a.metrics.get("yearRows", {}).get(y, {})
        issues = a.year_issues.get(y, [])
        sc = Counter(i["severity"] for i in issues)
        lines = [f"# ممیزیِ سال {y}", "",
                 f"- حالت: **{'جدول رسمی' if doc['mode'] == 'data' else 'قاعده‌محور'}** · ردیف: **{len(doc['rows'])}**",
                 "- دسته‌ها: " + " · ".join(f"{k}: {v}" for k, v in sorted(info.get("categories", {}).items())),
                 f"- ردیف‌های متصل به کاتالوگ: **{info.get('matched', 0)}**",
                 f"- یافته‌ها: بحرانی **{sc.get('critical', 0)}** · مهم **{sc.get('major', 0)}** · جزئی **{sc.get('minor', 0)}**", ""]
        if issues:
            lines += ["| شدت | سنجه | شرح |", "|---|---|---|"]
            for i in issues[:80]:
                lines.append(f"| {SEVERITY_FA[i['severity']]} | {i['check']} | {i['message']} |")
        else:
            lines.append("یافته‌ای ثبت نشد.")
        # ثبتِ صریحِ ردیف‌هایی که تطبیق نگرفتند (نه پنهان‌کردن، نه حذف).
        unmatched = [r for r in doc["rows"] if not r.get("eventId")]
        if unmatched:
            lines += ["", f"## ردیف‌های بدونِ تطبیق ({len(unmatched)})", "",
                      "این ردیف‌ها با تاریخِ جدولِ PDF نمایش داده می‌شوند و دسته/تقویمشان",
                      "از خودِ عنوان استنباط شده است؛ برای تأییدِ نهایی نیاز به منبعِ دستی دارند.", "",
                      "| تاریخ | عنوان |", "|---|---|"]
            for r in unmatched:
                m, d = r["solar"][1], r["solar"][2]
                lines.append(f"| {y}/{m:02d}/{d:02d} | {r['title'][:110]} |")
        (OUT / "years" / f"{y}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # خلاصه
    lines = ["# گزارشِ ممیزیِ تقویم صبا", "",
             f"- تاریخ: **{date.today().isoformat()}** · دامنه: **{FIRST}–{LAST}**",
             f"- رویدادهای کاتالوگ: **{a.metrics.get('masterEvents', 0)}**",
             f"- سال‌های بررسی‌شده: **{len(a.years)}**",
             f"- سال‌های دارای جدول رسمی: **{len(a.metrics.get('officialYears', []))}** · "
             f"بدونِ جدول: {', '.join(map(str, a.metrics.get('missingOfficialYears', []))) or '—'}",
             f"- کل یافته‌ها: **{total}** — بحرانی **{sev.get('critical', 0)}** · "
             f"مهم **{sev.get('major', 0)}** · جزئی **{sev.get('minor', 0)}**", "",
             "## شمارشِ داده", "",
             "| مورد | مقدار |", "|---|---:|",
             f"| رویداد | {a.metrics.get('masterEvents', 0)} |",
             f"| فرهنگی | {a.metrics.get('masterCounts', {}).get('cultural', 0)} |",
             f"| مذهبی | {a.metrics.get('masterCounts', {}).get('religious', 0)} |",
             f"| تاریخی | {a.metrics.get('masterCounts', {}).get('historical', 0)} |",
             f"| رسمی/ملی | {a.metrics.get('masterCounts', {}).get('official', 0)} |",
             f"| بین‌المللی | {a.metrics.get('masterCounts', {}).get('international', 0)} |",
             f"| تأییدشده | {a.metrics.get('masterVerification', {}).get('verified', 0)} |",
             f"| تأییدِ جزئی | {a.metrics.get('masterVerification', {}).get('partially_verified', 0)} |",
             f"| سنتی | {a.metrics.get('masterVerification', {}).get('traditional', 0)} |",
             f"| بدونِ تأیید | {a.metrics.get('masterVerification', {}).get('unverified', 0)} |",
             f"| موقت | {a.metrics.get('masterVerification', {}).get('temporary', 0)} |", "",
             "## یافته‌ها به تفکیک سنجه", "",
             "| سنجه | تعداد |", "|---|---:|"]
    for c, n in by_check.most_common():
        lines.append(f"| {c} | {n} |")
    lines += ["", "## خطاهای بحرانی", ""]
    crit = [i for i in a.issues if i["severity"] == "critical"]
    lines += ([f"- **{i['check']}** — {i['message']}" + (f" — {i['title'][:60]}" if i.get("title") else "")
               for i in crit[:60]] or ["هیچ خطای بحرانی‌ای یافت نشد."])
    lines += ["", "## خطاهای مهم", ""]
    maj = [i for i in a.issues if i["severity"] == "major"]
    lines += ([f"- **{i['check']}** — {i['message']}" + (f" — {i['title'][:60]}" if i.get("title") else "")
               for i in maj[:60]] or ["هیچ خطای مهمی یافت نشد."])
    lines += ["", "## پوششِ سال‌ها", "", "| سال | حالت | ردیف | متصل |", "|---|---|---:|---:|"]
    for y in range(FIRST, LAST + 1):
        info = a.metrics.get("yearRows", {}).get(y)
        if info:
            lines.append(f"| {y} | {'رسمی' if info['mode'] == 'data' else 'قاعده'} | {info['count']} | {info['matched']} |")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    (OUT / "audit.json").write_text(json.dumps({
        "generatedAt": date.today().isoformat(),
        "scope": {"firstYear": FIRST, "lastYear": LAST},
        "metrics": a.metrics,
        "counts": dict(sev),
        "issues": a.issues,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"audit: issues={total} critical={sev.get('critical',0)} major={sev.get('major',0)} "
          f"minor={sev.get('minor',0)} years={len(a.years)}")
    return 1 if sev.get("critical") else 0


def main() -> int:
    a = Audit()
    audit_master(a)
    audit_years(a)
    audit_app_packs(a)
    return write_reports(a)


if __name__ == "__main__":
    raise SystemExit(main())
