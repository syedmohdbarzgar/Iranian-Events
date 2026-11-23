"""تست‌های خودکارِ چندساله — موتور، کاتالوگ و خروجی سال‌ها.

اجرا: `py -3 -m unittest discover -s tests` از پوشهٔ calendars-final.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402
import event_normalize as norm  # noqa: E402
import jalali_reference as reference  # noqa: E402

DATA = ROOT / "data"
FIRST, LAST = 1300, 1420


def all_days(first: int, last: int):
    for y in range(first, last + 1):
        for m in range(1, 13):
            for d in range(1, engine.month_len(y, m) + 1):
                yield y, m, d


class ConversionTest(unittest.TestCase):
    def test_every_day_matches_independent_reference(self):
        """CAL-001: همهٔ ۴۴٬۱۹۵ روز با الگوریتم بیراشکوفسکی یکی است و برگشت‌پذیر است."""
        count = 0
        for y, m, d in all_days(FIRST, LAST):
            g = engine.jalali_to_gregorian(y, m, d)
            self.assertEqual(g, reference.to_gregorian(y, m, d), f"{y}/{m}/{d}")
            self.assertEqual(engine.gregorian_to_jalali(*g), (y, m, d))
            count += 1
        self.assertGreater(count, 44_000)

    def test_gregorian_round_trip_across_century(self):
        g = date(1921, 3, 21)
        while g <= date(2042, 3, 20):
            self.assertEqual(engine.jalali_to_gregorian(*engine.gregorian_to_jalali(g.year, g.month, g.day)),
                             (g.year, g.month, g.day))
            g += timedelta(days=97)


class LeapAndMonthTest(unittest.TestCase):
    def test_leap_years_match_reference(self):
        """CAL-002: کبیسه در ۱۱۷۹–۱۵۹۹."""
        for y in range(1179, 1600):
            self.assertEqual(engine.month_len(y, 12) == 30, reference.is_leap(y), y)

    def test_month_lengths(self):
        """CAL-003: ۳۱/۳۰/۲۹-۳۰ و جمعِ سال."""
        for y in (1300, 1348, 1382, 1403, 1404, 1420):
            lengths = [engine.month_len(y, m) for m in range(1, 13)]
            self.assertEqual(lengths[:6], [31] * 6)
            self.assertEqual(lengths[6:11], [30] * 5)
            self.assertIn(lengths[11], (29, 30))
            self.assertEqual(sum(lengths), 366 if reference.is_leap(y) else 365)

    def test_invalid_month_and_day(self):
        for args in ((1400, 0, 1), (1400, 13, 1), (1400, 1, 0), (1400, 1, 32), (1400, 7, 31)):
            with self.assertRaises(ValueError):
                engine.jalali_to_gregorian(*args)
        with self.assertRaises(ValueError):
            engine.month_len(1400, 13)


class CalendarRulesTest(unittest.TestCase):
    def test_weekday_for_every_day(self):
        """CAL-004: روزِ هفته با تقویم میلادیِ همان روز یکی است."""
        for y, m, d in all_days(FIRST, LAST):
            g = date(*engine.jalali_to_gregorian(y, m, d))
            self.assertEqual(g.weekday(), date(*engine.jalali_to_gregorian(y, m, d)).weekday())

    def test_anchor_dates(self):
        """CAL-010: لنگرهای نوروز."""
        anchors = json.loads((DATA / "reference-anchors.json").read_text(encoding="utf-8"))["anchors"]
        for a in anchors:
            g = a["gregorian"]
            expected = tuple(int(x) for x in g.split("-")) if isinstance(g, str) else tuple(g)
            self.assertEqual(engine.jalali_to_gregorian(a["jalali"][0], 1, 1), expected, a["jalali"][0])

    def test_year_boundaries_have_no_gap(self):
        """CAL-005: آخرین روز + ۱ = ۱ فروردینِ سالِ بعد."""
        for y in range(FIRST, LAST):
            last = date(*engine.jalali_to_gregorian(y, 12, engine.month_len(y, 12)))
            first = date(*engine.jalali_to_gregorian(y + 1, 1, 1))
            self.assertEqual(first - last, timedelta(days=1), y)

    def test_date_differences_across_years(self):
        """CAL-007: اختلافِ تاریخ = اختلافِ روزِ میلادی در بازه‌های چندساله."""
        pairs = [((1300, 1, 1), (1420, 12, 29)), ((1382, 3, 14), (1406, 1, 1)),
                 ((1399, 12, 30), (1400, 1, 1)), ((1348, 10, 11), (1404, 10, 11))]
        for a, b in pairs:
            da = date(*engine.jalali_to_gregorian(*a))
            db = date(*engine.jalali_to_gregorian(*b))
            diff = (db - da).days
            jdn_a = engine.jdn_jalali(*a)
            jdn_b = engine.jdn_jalali(*b)
            self.assertEqual(jdn_b - jdn_a, diff, (a, b))

    def test_lunar_occurrence_is_consistent(self):
        """CAL-012: هر تاریخِ قمری یک روزِ شمسیِ درست می‌دهد (اختلافِ JDN مضربِ ۷ نیست، فقط پیوستگی)."""
        for y in range(1382, 1407):
            for lm in (1, 6, 9, 10, 12):
                for ld in (1, 15, 29):
                    got = engine.lunar_occurrence(y, lm, ld)
                    if got is None:
                        continue
                    self.assertEqual(got[0], y)
                    self.assertTrue(1 <= got[1] <= 12 and 1 <= got[2] <= engine.month_len(y, got[1]))


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master = json.loads((DATA / "events-master.json").read_text(encoding="utf-8"))
        cls.events = cls.master["events"]

    def test_required_fields_and_unique_ids(self):
        """CAL-013: ۱۸ فیلدِ توافق‌شده و شناسهٔ یگانه."""
        required = ("id", "title", "description", "calendar", "dateRule", "month", "day",
                    "occurrenceYear", "category", "recurrenceType", "isOfficialHoliday",
                    "sourceName", "sourceUrl", "sourcePublicationDate", "verificationStatus",
                    "lastVerifiedAt", "confidence", "notes")
        ids = set()
        for e in self.events:
            self.assertTrue(set(required) <= set(e), e.get("id"))
            self.assertNotIn(e["id"], ids)
            ids.add(e["id"])

    def test_no_canonical_duplicates(self):
        seen = {}
        for e in self.events:
            key = (e["category"], e["calendar"], e.get("month"), e.get("day"),
                   norm.canon_key(e["title"]))
            self.assertNotIn(key, seen, f"{e['id']} ↔ {seen.get(key)}")
            seen[key] = e["id"]

    def test_recurrence_rules_consistent(self):
        for e in self.events:
            rec = e["recurrenceType"]
            if rec == "C":
                self.assertEqual(e["calendar"], "lunar", e["id"])
                self.assertTrue(e["lunar_dates"], e["id"])
            elif rec == "B":
                self.assertEqual(e["calendar"], "gregorian", e["id"])
                self.assertTrue(e["gregorian_dates"], e["id"])
            elif rec in ("A", "D"):
                self.assertEqual(e["calendar"], "solar", e["id"])
                self.assertTrue(e["solar_dates"], e["id"])
            elif rec == "E":
                self.assertIsNone(e.get("month"), e["id"])

    def test_holidays_have_a_category(self):
        for e in self.events:
            if e.get("isOfficialHoliday"):
                self.assertIn(e["category"],
                              ("official", "religious", "cultural", "historical", "international"), e["id"])

    def test_sources_for_verified_rows(self):
        for e in self.events:
            if e["verificationStatus"] == "verified":
                self.assertTrue(e.get("sourceName"), e["id"])
                self.assertTrue(e.get("lastVerifiedAt"), e["id"])


class YearOutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = engine.build_catalog()

    def test_generated_years_are_valid_and_unique(self):
        """CAL-014: هر ردیفِ هر سال تاریخِ معتبر، تبدیلِ درست و بدونِ تکرار."""
        for y in (1300, 1320, 1348, 1382, 1399, 1403, 1406, 1407, 1420):
            rows = engine.generate(y, self.catalog)["rows"]
            self.assertGreater(len(rows), 100, y)
            seen = set()
            for r in rows:
                jy, jm, jd = r["solar"]
                self.assertEqual(jy, y)
                self.assertTrue(1 <= jm <= 12 and 1 <= jd <= engine.month_len(y, jm), r["title"])
                self.assertEqual(engine.gregorian_to_jalali(*r["gregorian"]), (jy, jm, jd))
                key = (jm, jd, norm.canon_key(r["title"]))
                self.assertNotIn(key, seen, f"{y}: {r['title']}")
                seen.add(key)
                if r["holiday"]:
                    self.assertTrue(r["title"].strip())

    def test_future_years_are_temporary(self):
        """سال‌های بدونِ تقویمِ رسمی وضعیتِ «موقت» دارند، نه «تأییدشده»."""
        for y in (1408, 1415, 1420):
            for r in engine.generate(y, self.catalog)["rows"]:
                self.assertEqual(r.get("verificationStatus"), "temporary", f"{y}: {r['title']}")

    def test_data_years_are_not_temporary(self):
        for y in (1382, 1406):
            for r in engine.generate(y, self.catalog)["rows"]:
                self.assertNotEqual(r.get("verificationStatus"), "temporary", f"{y}: {r['title']}")

    def test_quds_day_is_friday(self):
        for y in range(1382, 1421):
            rows = engine.generate(y, self.catalog)["rows"]
            q = next((r for r in rows if r["title"] == "روز جهانی قدس"), None)
            if q:
                self.assertEqual(date(*q["gregorian"]).weekday(), 4, y)


class PackTest(unittest.TestCase):
    def test_pack_rows_have_valid_shape(self):
        for name, rows in norm.load_packs().items():
            ids = set()
            for r in rows:
                self.assertIn(r["system"], ("PERSIAN", "ISLAMIC", "GREGORIAN"), r.get("id"))
                self.assertNotIn(r["id"], ids, f"{name}: {r['id']}")
                ids.add(r["id"])
                self.assertIsInstance(r["event"], str)
                self.assertTrue(r["event"].strip())
                if r.get("type") in ("nthWeekday", "lastDayOfMonth"):
                    continue
                self.assertTrue(1 <= r["month"] <= 12, r["id"])
                self.assertTrue(1 <= r["day"] <= 31, r["id"])
                self.assertTrue(r.get("years"), r["id"])

    def test_app_pack_years_cover_holiday_years(self):
        for name, rows in norm.load_packs().items():
            for r in rows:
                if r.get("holidayYears"):
                    self.assertTrue(set(r["holidayYears"]) <= set(r["years"]), f"{name}: {r['id']}")


if __name__ == "__main__":
    unittest.main()
