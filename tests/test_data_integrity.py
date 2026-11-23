"""گاردهای یکپارچگیِ داده و گزارش‌های ممیزی.

هدف: جلوگیری از انتشارِ داده‌ای که با manifest/گزارش‌ها یکی نیست، تاریخِ
نامعتبر دارد، رویدادِ بی‌شناسه دارد یا ردیفِ بدونِ تطبیق را پنهان کرده است.
"""
from __future__ import annotations

import json
import hashlib
import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402
import jalali_reference as jr  # noqa: E402


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class DataIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master = load(DATA / "events-master.json")
        cls.events = cls.master["events"]
        cls.official = {}
        for p in DATA.glob("official-calendar-*.json"):
            doc = load(p)
            cls.official[int(doc["year"])] = doc
        cls.years = {}
        for p in (DATA / "years").glob("*.json"):
            if not p.stem.isdigit():
                continue
            doc = load(p)
            if doc.get("mode") == "data":
                cls.years[int(p.stem)] = doc
        cls.manifest = load(ROOT / "reports" / "audit" / "data-manifest.json")

    def test_manifest_counts_match_current_data(self):
        annual_rows = sum(len(d["rows"]) for d in self.years.values())
        unmatched = sum(1 for d in self.years.values() for r in d["rows"] if not r.get("eventId"))
        self.assertEqual(self.manifest["counts"]["uniqueEvents"], len(self.events))
        self.assertEqual(self.manifest["counts"]["annualRows"], annual_rows)
        self.assertEqual(self.manifest["counts"]["annualUnmatchedRows"], unmatched)
        self.assertEqual(self.manifest["counts"]["officialYears"], len(self.official))

    def test_manifest_hashes_are_current(self):
        for rel, expected in self.manifest["dataHashes"].items():
            path = ROOT / rel
            self.assertTrue(path.exists(), rel)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected, rel)

    def test_master_ids_unique_and_status_valid(self):
        ids = [e["id"] for e in self.events]
        self.assertEqual(len(ids), len(set(ids)))
        allowed = {"verified", "partially_verified", "traditional", "unverified", "temporary"}
        self.assertTrue({e.get("verificationStatus") for e in self.events} <= allowed)

    def test_official_rows_are_structurally_valid(self):
        for year, doc in self.official.items():
            dates = [tuple(r["solar"]) for r in doc["rows"]]
            self.assertEqual(len(dates), len(set(dates)), f"{year}: تاریخ تکراری")
            for row in doc["rows"]:
                jy, jm, jd = row["solar"]
                self.assertEqual(jy, year)
                self.assertIn(jm, range(1, 13))
                self.assertIn(jd, range(1, jr.month_length(jy, jm) + 1))
                greg = jr.to_gregorian(jy, jm, jd)
                self.assertEqual(tuple(row["gregorian"]), greg)
                self.assertEqual(row["weekday"], date(*greg).weekday())
                self.assertIsInstance(row["holiday"], bool)
                self.assertTrue((row.get("title") or "").strip())
                self.assertIsInstance(row.get("page"), int)

    def test_year_rows_have_known_event_ids_and_no_duplicate_pair(self):
        known = {e["id"] for e in self.events}
        for year, doc in self.years.items():
            self.assertEqual(doc.get("count"), len(doc["rows"]), str(year))
            pairs = set()
            for row in doc["rows"]:
                eid = row.get("eventId")
                if eid:
                    self.assertIn(eid, known, f"{year} {row['solar']} {eid}")
                    pair = (tuple(row["solar"]), eid)
                    self.assertNotIn(pair, pairs, f"{year}: تکرار {pair}")
                    pairs.add(pair)

    def test_year_rows_carry_status_and_date_certainty(self):
        allowed = {"verified", "partially_verified", "traditional", "unverified", "temporary"}
        for year, doc in self.years.items():
            for row in doc["rows"]:
                self.assertIn(row.get("verificationStatus"), allowed, f"{year} {row}")
                self.assertTrue(row.get("source"), f"{year} {row}")
                self.assertTrue(row.get("sourceRef"), f"{year} {row}")
                if row.get("approx"):
                    self.assertEqual(row.get("dateCertainty"), "approximate", f"{year} {row}")
                if row.get("verificationStatus") != "verified":
                    self.assertNotEqual(row.get("dateCertainty"), "confirmed", f"{year} {row}")
                if not row.get("eventId"):
                    self.assertEqual(row["verificationStatus"], "unverified",
                                     f"{year} ردیفِ بی‌تطبیق نباید verified باشد: {row}")

    def test_web_payload_matches_year_rows(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        marker = "const DATA = "
        self.assertIn(marker, html, "DATA در وب پیدا نشد")
        start = html.index(marker) + len(marker)
        payload, _ = json.JSONDecoder().raw_decode(html[start:])

        def key(row):
            return (tuple(row["solar"]), row["title"], row.get("verificationStatus"),
                    row.get("dateCertainty"), row.get("page"))

        for year, doc in self.years.items():
            web_rows = payload["years"][str(year)]["official"]
            self.assertEqual(len(web_rows), len(doc["rows"]), str(year))
            self.assertEqual(sorted(map(key, web_rows)), sorted(map(key, doc["rows"])), str(year))

    def test_identity_corrections_preserve_history_and_stay_out_of_calendar(self):
        by_id = {e["id"]: e for e in self.events}
        for eid, canonical in (("E0096", "E0426"), ("E0459", "E0370")):
            event = by_id[eid]
            self.assertEqual(event.get("supersededBy"), canonical)
            self.assertTrue(event.get("excludeFromCalendar"))
            self.assertEqual(event.get("verificationStatus"), "unverified")
            self.assertTrue(event["correctionHistory"]["preserved"])
            self.assertTrue(event["correctionHistory"]["source"])
        for doc in self.years.values():
            for row in doc["rows"]:
                self.assertNotIn(row.get("eventId"), {"E0096", "E0459"})

    def test_unmatched_report_is_complete(self):
        report = load(ROOT / "reports" / "audit" / "unmatched.json")
        current = sum(1 for d in self.years.values() for r in d["rows"] if not r.get("eventId"))
        self.assertEqual(report["total"], current)
        self.assertEqual(len(report["rows"]), current)
        self.assertTrue(all(r["disposition"] == "needs_manual_review" for r in report["rows"]))

    def test_review_queue_covers_every_non_verified_event(self):
        queue = load(DATA / "review" / "verification-queue.json")["queue"]
        expected = {e["id"] for e in self.events if e.get("verificationStatus") != "verified"}
        self.assertEqual({r["id"] for r in queue}, expected)

    def test_extraction_years_are_not_published(self):
        for y in (1393, 1396, 1402):
            self.assertNotIn(y, self.official)


if __name__ == "__main__":
    unittest.main()