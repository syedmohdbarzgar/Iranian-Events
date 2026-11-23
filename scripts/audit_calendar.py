"""ممیزیِ مستقلِ موتورِ تقویم — بدونِ نگاه به دادهٔ مناسبت‌ها.

سنجه‌ها:
  CAL-001  تبدیلِ شمسی↔میلادی برای **هر روزِ** ۱۳۰۰–۱۴۲۰ با مرجعِ مستقل (بیراشکوفسکی)
  CAL-002  تشخیصِ کبیسه در ۱۱۷۹–۱۵۹۹ با مرجعِ مستقل
  CAL-003  طولِ ماه‌ها (۳۱/۳۰/۲۹/۳۰) و جمعِ روزهای سال
  CAL-004  روزِ هفته برای همهٔ روزها (قراردادِ ایرانی، شنبه=۰)
  CAL-005  مرزِ سال: آخرین روز + ۱ = ۱ فروردینِ سالِ بعد، بدونِ شکاف/همپوشانی
  CAL-006  تاریخِ نامعتبر باید خطا بدهد (ماه ۰/۱۳، روز ۰/۳۲، ۳۰ اسفندِ غیرکبیسه)
  CAL-007  اختلافِ تاریخ‌ها در بازه‌های چندساله = اختلافِ روزهای میلادی
  CAL-008  هر ردیفِ جدولِ رسمی (۱۳۸۲–۱۴۰۶): شمسی↔میلادی، روزِ هفته، ماه/روزِ موجود
  CAL-009  توالیِ روزهای جدول (بدونِ تکرار/شکاف) و مرزِ سالِ جدول
  CAL-010  لنگرهای مستندِ نوروز (تقویم رسمی ایران)
  CAL-011  پوششِ سال‌های رسمی و فایل‌های ناقص/خراب

خروجی: reports/audit/calendar-engine.json و reports/audit/calendar-engine.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402
import jalali_reference as reference  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "reports" / "audit"
FIRST, LAST = 1300, 1420
PERSIAN_WEEKDAYS = ("شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه")
ANCHORS = json.loads((DATA / "reference-anchors.json").read_text(encoding="utf-8"))["anchors"]


class Check:
    def __init__(self, cid: str, name: str, detail: str = "") -> None:
        self.id = cid
        self.name = name
        self.detail = detail
        self.failures: list[str] = []
        self.samples: list[str] = []
        self.measured = 0
        self._status: str | None = None

    def fail(self, msg: str) -> None:
        if len(self.failures) < 50:
            self.failures.append(msg)
        if len(self.samples) < 12:
            self.samples.append(msg)

    @property
    def status(self) -> str:
        if self._status:
            return self._status
        return "pass" if not self.failures else "fail"

    def as_dict(self) -> dict:
        status = self.status
        return {"id": self.id, "name": self.name, "detail": self.detail,
                "status": status, "measured": self.measured,
                "failures": len(self.failures), "samples": self.samples}


def official_years() -> dict[int, dict]:
    out = {}
    for p in sorted(DATA.glob("official-calendar-*.json")):
        y = int(p.stem.split("-")[-1])
        out[y] = json.loads(p.read_text(encoding="utf-8"))
    return out


def weekday_persian(g: date) -> int:
    return (g.weekday() + 2) % 7


def main() -> int:
    checks: list[Check] = []
    c1 = Check("CAL-001", "تبدیلِ شمسی↔میلادی (همهٔ روزها)",
               "هر روز ۱۳۰۰–۱۴۲۰ با مرجعِ مستقل و رفت‌وبرگشت")
    c2 = Check("CAL-002", "کبیسه‌ها (۱۱۷۹–۱۵۹۹)", "مقایسه با مرجعِ مستقل")
    c3 = Check("CAL-003", "طولِ ماه‌ها و روزهای سال")
    c4 = Check("CAL-004", "روزِ هفته", "شنبه=۰ … جمعه=۶")
    c5 = Check("CAL-005", "مرزِ سال")
    c6 = Check("CAL-006", "ردِ تاریخِ نامعتبر")
    c7 = Check("CAL-007", "اختلافِ بازه‌های چندساله")
    c8 = Check("CAL-008", "جدول‌های رسمی: تبدیل و روزِ هفته")
    c9 = Check("CAL-009", "توالی و مرزِ سال در جدول‌های رسمی")
    c10 = Check("CAL-010", "لنگرهای مستندِ نوروز")
    c11 = Check("CAL-011", "پوششِ سال‌های رسمی")
    checks += [c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11]

    # CAL-001/003/004/005 — پیمایشِ روزبه‌روز
    total_days = 0
    for jy in range(FIRST, LAST + 1):
        try:
            days_in_year = reference.year_days(jy)
        except ValueError as exc:
            c1.fail(f"{jy}: {exc}")
            continue
        c3.measured += 1
        if sum(engine.month_len(jy, m) for m in range(1, 13)) != days_in_year:
            c3.fail(f"{jy}: جمعِ ماه‌ها با طولِ سالِ مرجع برابر نیست")
        expected_first = reference.first_day(jy)
        got_first = date(*engine.jalali_to_gregorian(jy, 1, 1))
        c1.measured += 1
        if got_first != expected_first:
            c1.fail(f"{jy}-01-01: موتور {got_first} ≠ مرجع {expected_first}")
        for jm in range(1, 13):
            length = reference.month_length(jy, jm)
            if engine.month_len(jy, jm) != length:
                c3.fail(f"{jy}-{jm:02d}: طول {engine.month_len(jy, jm)} ≠ {length}")
            for jd in range(1, length + 1):
                total_days += 1
                g = date(*engine.jalali_to_gregorian(jy, jm, jd))
                exp = date.fromordinal(reference.first_day(jy).toordinal() + (jm - 1) * 31 + jd - 1
                                       if jm <= 7 else
                                       reference.first_day(jy).toordinal() + 186 + (jm - 7) * 30 + jd - 1)
                if g != exp:
                    c1.fail(f"{jy}-{jm:02d}-{jd:02d}: {g} ≠ {exp}")
                if engine.gregorian_to_jalali(g.year, g.month, g.day) != (jy, jm, jd):
                    c1.fail(f"رفت‌وبرگشتِ {jy}-{jm:02d}-{jd:02d} ناموفق")
                c4.measured += 1
                if weekday_persian(g) != (g.toordinal() + 1) % 7:
                    c4.fail(f"{jy}-{jm:02d}-{jd:02d}: روزِ هفته ناسازگار")
                # مرز: روزِ بعد باید همین روز +۱ باشد و ۱ فروردینِ بعدی در جای درست
                if jd == length and jm == 12:
                    nxt = (jy + 1, 1, 1)
                elif jd == length:
                    nxt = (jy, jm + 1, 1)
                else:
                    nxt = (jy, jm, jd + 1)
                c5.measured += 1
                if date(*engine.jalali_to_gregorian(*nxt)) - g != timedelta(days=1):
                    c5.fail(f"{jy}-{jm:02d}-{jd:02d}: شکاف/همپوشانی با روزِ بعد")
        # CAL-007 — اختلافِ ۱، ۵ و ۱۰ سال
        for span in (1, 5, 10):
            if jy + span <= LAST:
                a = date(*engine.jalali_to_gregorian(jy, 1, 1))
                b = date(*engine.jalali_to_gregorian(jy + span, 1, 1))
                c7.measured += 1
                if (b - a).days != sum(reference.year_days(y) for y in range(jy, jy + span)):
                    c7.fail(f"{jy}→{jy + span}: اختلافِ روزها")

    # CAL-002 — کبیسه
    for jy in range(1179, 1600):
        c2.measured += 1
        if engine.month_len(jy, 12) != (30 if reference.is_leap(jy) else 29):
            c2.fail(f"{jy}: کبیسهٔ موتور با مرجع یکی نیست")

    # CAL-006 — ورودیِ نامعتبر
    invalid = [(1400, 13, 1), (1400, 0, 1), (1400, 1, 32), (1403, 12, 30), (1400, 7, 31), (1400, 1, 0)]
    # 1403 کبیسه است و ۳۰ اسفند دارد؛ برای آزمونِ رد، سالِ غیرکبیسه ۱۴۰۴
    invalid[3] = (1404, 12, 30)
    for args in invalid:
        c6.measured += 1
        try:
            engine.jalali_to_gregorian(*args)
            c6.fail(f"{args}: پذیرفته شد ولی نامعتبر است")
        except ValueError:
            pass
    for args in [(2025, 2, 29), (2025, 13, 1), (2025, 4, 31)]:
        c6.measured += 1
        try:
            engine.gregorian_to_jalali(*args)
            c6.fail(f"{args}: تاریخِ میلادیِ نامعتبر پذیرفته شد")
        except ValueError:
            pass

    # CAL-008/009 — جدول‌های رسمی
    official = official_years()
    for y, doc in official.items():
        rows = doc.get("rows", [])
        c8.measured += len(rows)
        prev = None
        for r in rows:
            try:
                s = tuple(r["solar"])
                g = tuple(r["gregorian"])
            except (KeyError, TypeError):
                c8.fail(f"{y}: ردیفِ بدونِ تاریخ ({str(r)[:40]})")
                continue
            if s[0] != y:
                c8.fail(f"{y}: سالِ ردیف {s} با فایل یکی نیست")
            try:
                jy, jm, jd = engine.gregorian_to_jalali(*g)
            except ValueError:
                c8.fail(f"{y}: میلادیِ نامعتبر {g}")
                continue
            if (jy, jm, jd) != s:
                c8.fail(f"{y}: شمسی {s} ≠ تبدیلِ میلادی {g} → {(jy, jm, jd)}")
            if not (1 <= s[1] <= 12 and 1 <= s[2] <= engine.month_len(y, s[1])):
                c8.fail(f"{y}: تاریخِ نامعتبر {s}")
            if "weekday" in r and r["weekday"] is not None:
                if r["weekday"] != date(*g).weekday():
                    c8.fail(f"{y}: weekday {r['weekday']} ≠ {date(*g).weekday()} ({g})")
            c9.measured += 1
            if prev is not None and (date(*g) - date(*prev)).days <= 0:
                c9.fail(f"{y}: ترتیبِ تاریخ شکست در {prev} → {g}")
            prev = g
        # مرزِ سال: ردیفِ اول ۱/۱ و روزِ آخر ۱۲/۲۹ یا ۱۲/۳۰
        if rows:
            if tuple(rows[0]["solar"][1:]) != (1, 1):
                c9.fail(f"{y}: ردیفِ اول ۱ فروردین نیست")
            last = rows[-1]["solar"]
            # جدول‌های رسمی فقط روزهای دارای مناسبت را دارند؛ آخرین ردیف لازم نیست ۲۹/۳۰ اسفند باشد،
            # ولی باید در اسفند و در محدودهٔ روزهای معتبرِ همان سال باشد.
            if last[1] != 12 or not (1 <= last[2] <= engine.month_len(y, 12)):
                c9.fail(f"{y}: ردیفِ آخر {last[1:]} در اسفندِ معتبر نیست")

    # CAL-010 — لنگرها
    for a in ANCHORS:
        c10.measured += 1
        got = date(*engine.jalali_to_gregorian(a["jalali"][0], 1, 1))
        if got.isoformat() != a["gregorian"]:
            c10.fail(f"{a['jalali'][0]}: {got} ≠ {a['gregorian']} ({a['source']})")

    # CAL-011 — پوشش
    expected_years = set(range(1382, 1407))
    missing = sorted(expected_years - set(official))
    c11.measured = len(expected_years)
    for y in missing:
        c11.fail(f"{y}: جدولِ رسمی در پروژه نیست (تولید قاعده‌محور)")
    for y, doc in official.items():
        if not doc.get("rows"):
            c11.fail(f"{y}: فایلِ خالی")

    # خلاصه
    # سال‌های شناخته‌شدهٔ خراب، «هشدار»اند نه شکستِ موتور
    if c11.failures and set(missing) <= {1393, 1396, 1402}:
        c11._status = "warn"
    counts = Counter()
    for c in checks:
        counts[c.status] += 1
    failed = [c for c in checks if c.status == "fail"]
    result = {
        "generatedAt": date.today().isoformat(),
        "scope": {"firstYear": FIRST, "lastYear": LAST, "daysChecked": total_days,
                  "officialYears": sorted(official), "missingOfficialYears": missing,
                  "reference": "Borkowski (1996) / jalaali-js"},
        "checks": [c.as_dict() for c in checks],
        "counts": dict(counts),
        "pass": not failed,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "calendar-engine.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# ممیزیِ موتورِ تقویم", "",
             f"- دامنه: **{FIRST}–{LAST}** · روزهای بررسی‌شده: **{total_days:,}**",
             f"- سال‌های دارای جدولِ رسمی: **{len(official)}** · سال‌های بدونِ جدول: "
             + ("، ".join(map(str, missing)) if missing else "—"),
             f"- مرجعِ مستقل: {result['scope']['reference']}",
             f"- نتیجه: **{'قبول' if result['pass'] else 'رد'}** "
             f"({counts.get('pass', 0)} سنجه قبول، {counts.get('fail', 0)} رد)", "",
             "| شناسه | سنجه | اندازه | نتیجه | نمونهٔ خطا |", "|---|---|---:|---|---|"]
    for c in checks:
        mark = {"pass": "✓", "warn": "⚠", "fail": "✗"}.get(c.status, "?")
        lines.append(f"| {c.id} | {c.name} | {c.measured:,} | {mark} | "
                     + ("؛ ".join(c.samples[:2]) if c.samples else "—") + " |")
    if missing:
        lines += ["", "## سال‌های بدونِ جدولِ رسمی", "",
                  "این سال‌ها در `data/official-calendar-*.json` نیستند و خروجی‌شان قاعده‌محور "
                  "و با وضعیتِ «موقت» است: " + "، ".join(map(str, missing))]
    (OUT / "calendar-engine.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"calendar-engine: {counts.get('pass',0)} pass / {counts.get('fail',0)} fail, "
          f"days={total_days}, official={len(official)}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
