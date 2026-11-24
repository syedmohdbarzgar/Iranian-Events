"""آزمون‌های مدلِ تاریخ، مقایسهٔ نسخه‌ها و جریانِ تأیید/بازگردانی (فاز ۶).

همهٔ آزمون‌ها روی پوشهٔ موقت اجرا می‌شوند؛ دادهٔ واقعیِ مخزن دست‌نخورده می‌ماند.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import calendar_engine as engine  # noqa: E402
import history_store as store  # noqa: E402
import ingest_pdf  # noqa: E402
import review_changes as review  # noqa: E402
import revision_diff  # noqa: E402

CATALOG = [
    {"id": "E0001", "title": "آزمون سراسری", "category": "official", "calendar": "solar",
     "recurrenceType": "A", "origin": {"kind": "established", "label": "تاریخِ اعلام",
                                       "note": "سندِ آزمون", "source": "test#1"},
     "verificationStatus": "partially_verified", "solar_dates": [[1, 10]]},
    {"id": "E0002", "title": "رویداد دوم", "category": "official", "calendar": "solar",
     "recurrenceType": "A", "origin": {"kind": "tradition", "label": "سنتی", "note": "", "source": ""},
     "verificationStatus": "traditional", "solar_dates": [[2, 1]]},
    {"id": "E0003", "title": "رویداد سوم", "category": "official", "calendar": "solar",
     "recurrenceType": "A", "origin": None, "verificationStatus": "partially_verified",
     "solar_dates": [[3, 1]]},
]


def row(year: int, m: int, d: int, title: str, page: int = 1, holiday: bool = False) -> dict:
    g = engine.jalali_to_gregorian(year, m, d)
    return {"solar": [year, m, d], "gregorian": list(g), "lunar": [None, None, None],
            "weekday": None, "title": title, "holiday": holiday, "page": page, "derived": []}


def revision(rid: str, year: int, sha: str, *, state: str = "approved",
             at: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "id": rid, "year": year,
        "document": {"file": f"Calendar-{year}.pdf", "sha256": sha, "bytes": 10, "pages": 1},
        "extraction": {"method": "text-layer", "tool": "test", "extractedAt": at,
                       "rowCount": 0, "qcProblems": 0},
        "state": state, "approvedBy": "tester", "approvedAt": at, "note": "",
        "supersedes": None, "supersededBy": None,
    }


class TempStore:
    """مسیرهای store را موقت می‌کند تا آزمون به دادهٔ مخزن دست نزند."""

    NAMES = ("HISTORY_DIR", "REVISION_DIR", "EVENTS_FILE", "OCCURRENCES_FILE",
             "REVISIONS_FILE", "CHANGELOG_FILE", "CHANGES_DIR", "INGEST_DIR")

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.saved = {name: getattr(store, name) for name in self.NAMES}
        self.saved_review = review.CHANGES_DIR
        self.saved_master = store.master_catalog
        history = root / "history"
        store.HISTORY_DIR = history
        store.REVISION_DIR = history / "revisions"
        store.EVENTS_FILE = history / "events.json"
        store.OCCURRENCES_FILE = history / "occurrences.json"
        store.REVISIONS_FILE = history / "revisions" / "index.json"
        store.CHANGELOG_FILE = history / "changelog.json"
        store.CHANGES_DIR = root / "review" / "changes"
        store.INGEST_DIR = root / "review" / "ingest"
        review.CHANGES_DIR = store.CHANGES_DIR
        store.master_catalog = lambda: [dict(e) for e in CATALOG]
        return root

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(store, name, value)
        review.CHANGES_DIR = self.saved_review
        store.master_catalog = self.saved_master
        self.tmp.cleanup()


def install(rows_by_revision: dict[str, tuple[dict, list[dict]]], catalog=CATALOG):
    revisions, rows_map = [], {}
    for rid, (rev, rows) in rows_by_revision.items():
        rev = dict(rev)
        rev["extraction"] = dict(rev["extraction"])
        rev["extraction"]["rowCount"] = len(rows)
        revisions.append(rev)
        rows_map[rid] = rows
        store.save_revision_rows(rid, rev["year"], rows, source=rev["document"])
    store.save_revisions(revisions)
    events, occurrences = store.derive(catalog, revisions, rows_map)
    store.save_history(events, occurrences)
    return revisions, rows_map, events, occurrences


class HistoryModelTest(unittest.TestCase):

    def test_each_year_has_its_own_occurrence(self):
        with TempStore():
            _, _, events, occ = install({
                "R-1404-aaaa": (revision("R-1404-aaaa", 1404, "a" * 64), [
                    row(1404, 1, 10, "آزمون سراسری", 3),
                    row(1404, 2, 1, "رویداد دوم", 4),
                ]),
                "R-1405-bbbb": (revision("R-1405-bbbb", 1405, "b" * 64), [
                    row(1405, 1, 10, "آزمون سراسری", 2),
                ]),
            })
            event = next(e for e in events if e["id"] == "E0001")
            self.assertEqual(event["observedYears"], [1404, 1405])
            self.assertEqual(event["firstObservedYear"], 1404)
            self.assertEqual(event["occurrenceCount"], 2)
            dates = sorted(tuple(o["date"]["solar"]) for o in occ if o["eventId"] == "E0001")
            self.assertEqual(dates, [(1404, 1, 10), (1405, 1, 10)])
            # وقوعِ ۱۴۰۵ به‌تنهایی نباید چیزی برای ۱۴۰۴ بسازد
            self.assertFalse([o for o in occ if o["eventId"] == "E0001" and o["year"] == 1404
                              and o["date"]["solar"] != [1404, 1, 10]])

    def test_no_generalization_without_witness(self):
        with TempStore():
            _, _, events, occ = install({
                "R-1405-bbbb": (revision("R-1405-bbbb", 1405, "b" * 64), [
                    row(1405, 1, 10, "آزمون سراسری", 2),
                ]),
            })
            event = next(e for e in events if e["id"] == "E0001")
            self.assertEqual(event["observedYears"], [1405])
            self.assertEqual(event["firstObservedYear"], 1405)
            self.assertEqual({o["year"] for o in occ}, {1405})

    def test_alias_change_does_not_rewrite_other_year(self):
        with TempStore():
            _, _, events, occ = install({
                "R-1404-aaaa": (revision("R-1404-aaaa", 1404, "a" * 64), [
                    row(1404, 1, 10, "آزمون سراسری", 3),
                ]),
                "R-1405-bbbb": (revision("R-1405-bbbb", 1405, "b" * 64), [
                    row(1405, 1, 10, "آزمون سراسری ملی", 2),
                ]),
            })
            event = next(e for e in events if e["id"] == "E0001")
            self.assertEqual(len(event["aliases"]), 2)
            old = next(o for o in occ if o["eventId"] == "E0001" and o["year"] == 1404)
            new = next(o for o in occ if o["eventId"] == "E0001" and o["year"] == 1405)
            self.assertEqual(old["observedTitle"], "آزمون سراسری")
            self.assertEqual(new["observedTitle"], "آزمون سراسری ملی")

    def test_event_without_witness_remains_visible(self):
        with TempStore():
            _, _, events, occ = install({
                "R-1405-bbbb": (revision("R-1405-bbbb", 1405, "b" * 64), [
                    row(1405, 1, 10, "آزمون سراسری", 2),
                ]),
            })
            missing = next(e for e in events if e["id"] == "E0002")
            self.assertEqual(missing["observedYears"], [])
            self.assertIsNone(missing["firstObservedYear"])
            self.assertFalse([o for o in occ if o["eventId"] == "E0002"])

    def test_validation_catches_orphan_and_tampering(self):
        with TempStore():
            revs, rows_map, events, occ = install({
                "R-1405-bbbb": (revision("R-1405-bbbb", 1405, "b" * 64), [
                    row(1405, 1, 10, "آزمون سراسری", 2),
                    row(1405, 2, 1, "رویداد دوم", 3),
                ]),
            })
            expected = store.derive(CATALOG, revs, rows_map)
            history = {"events": events, "occurrences": [dict(o) for o in occ],
                       "revisions": revs, "changelog": []}
            history["occurrences"][0]["evidence"] = dict(history["occurrences"][0]["evidence"])
            history["occurrences"][0]["evidence"]["revisionId"] = "R-9999-ghost"
            codes = {i["code"] for i in store.validate(history, expected=expected)}
            self.assertIn("OCC_REVISION_MISSING", codes)

            history = {"events": events, "occurrences": [dict(o) for o in occ],
                       "revisions": revs, "changelog": []}
            history["occurrences"][0]["observedTitle"] = "عنوانِ دست‌کاری‌شده"
            codes = {i["code"] for i in store.validate(history, expected=expected)}
            self.assertIn("OCC_NOT_DERIVED", codes)

    def test_draft_revision_never_feeds_history(self):
        with TempStore():
            draft = revision("R-1405-dddd", 1405, "d" * 64, state="draft")
            install({
                "R-1405-bbbb": (revision("R-1405-bbbb", 1405, "b" * 64), [
                    row(1405, 1, 10, "آزمون سراسری", 2),
                ]),
                "R-1405-dddd": (draft, [row(1405, 1, 10, "آزمون سراسری", 2),
                                        row(1405, 2, 1, "رویداد دوم", 3)]),
            })
            occ = store.load_history()["occurrences"]
            self.assertEqual({o["eventId"] for o in occ}, {"E0001"})


class DiffTest(unittest.TestCase):

    def test_all_change_kinds(self):
        old = [row(1405, 1, 1, "روز بزرگداشت الف"), row(1405, 1, 2, "روز بزرگداشت ب"),
               row(1405, 1, 3, "روز بزرگداشت پ"), row(1405, 1, 4, "روز بزرگداشت ت")]
        new = [row(1405, 1, 1, "روز بزرگداشت الف"), row(1405, 1, 2, "روز بزرگداشت ب تازه"),
               row(1405, 1, 5, "روز بزرگداشت پ"), row(1405, 1, 6, "جشنوارهٔ کتاب"),
               row(1405, 1, 7, "همایش ملی سلامت")]
        diff = revision_diff.diff_rows(old, new, year=1405, new_year=1405)
        kinds = {}
        for c in diff["changes"]:
            kinds.setdefault(c["kind"], []).append(c)
        self.assertEqual(kinds["UNCHANGED"][0]["before"]["title"], "روز بزرگداشت الف")
        self.assertEqual(kinds["RENAMED"][0]["after"]["title"], "روز بزرگداشت ب تازه")
        self.assertEqual(kinds["DATE_CHANGED"][0]["after"]["solar"][2], 5)
        self.assertEqual(kinds["REMOVED"][0]["before"]["title"], "روز بزرگداشت ت")
        self.assertEqual({c["after"]["title"] for c in kinds["ADDED"]},
                         {"جشنوارهٔ کتاب", "همایش ملی سلامت"})

    def test_writing_variant_is_not_a_rename(self):
        old = [row(1405, 1, 1, "روز ملی شدن صنعت نفت ایران (1329 ه‍.ش)")]
        new = [row(1405, 1, 1, "روز ملی شدن صنعت نفت ایران ) 1329 هو ش( )تعطیل(")]
        diff = revision_diff.diff_rows(old, new, year=1405)
        self.assertEqual(diff["counts"]["RENAMED"], 0)
        self.assertEqual(diff["counts"]["UNCHANGED"], 1)
        self.assertTrue(diff["changes"][0]["variantOnly"])

    def test_description_change_is_modified(self):
        old = [row(1405, 1, 1, "روز الف")]
        old[0]["description"] = "توضیحِ پیشین"
        new = [row(1405, 1, 1, "روز الف")]
        new[0]["description"] = "توضیحِ تازه"
        diff = revision_diff.diff_rows(old, new, year=1405)
        self.assertEqual(diff["changes"][0]["kind"], "MODIFIED")
        self.assertEqual(diff["changes"][0]["fields"], ["description"])

    def test_removal_from_one_year_keeps_other_years(self):
        with TempStore():
            install({
                "R-1404-aaaa": (revision("R-1404-aaaa", 1404, "a" * 64), [
                    row(1404, 1, 10, "آزمون سراسری", 3),
                    row(1404, 2, 1, "رویداد دوم", 4),
                ]),
                "R-1405-bbbb": (revision("R-1405-bbbb", 1405, "b" * 64), [
                    row(1405, 1, 10, "آزمون سراسری", 2),
                    row(1405, 2, 1, "رویداد دوم", 3),
                ]),
            })
            history = store.load_history()
            active = store.active_revisions(history["revisions"])[1405]
            old_rows = store.load_revision_rows(active)
            new_rows = [row(1405, 1, 10, "آزمون سراسری", 2)]
            rev = revision("R-1405-cccc", 1405, "c" * 64, state="draft", at="2026-02-01T00:00:00Z")
            diff = revision_diff.diff_rows(old_rows, new_rows, year=1405, new_year=1405)
            bundle = {"revision": rev, "rawRows": new_rows, "oldRevisionId": active["id"],
                      "diff": diff, "decisions": {}, "state": "pending",
                      "createdAt": store.now_iso()}
            store.write_json(review.bundle_path("R-1405-cccc"), bundle)
            removed = next(c for c in diff["changes"] if c["kind"] == "REMOVED")
            review.decide("R-1405-cccc", removed["id"], "approve", by="مدیر")
            review.finalize("R-1405-cccc", by="مدیر")
            occ = store.load_history()["occurrences"]
            self.assertFalse([o for o in occ if o["eventId"] == "E0002" and o["year"] == 1405])
            self.assertTrue([o for o in occ if o["eventId"] == "E0002" and o["year"] == 1404])
            self.assertEqual(len([o for o in occ if o["year"] == 1405]), 1)

    def test_holiday_change_is_modified(self):
        old = [row(1405, 1, 1, "روز الف")]
        new = [row(1405, 1, 1, "روز الف", holiday=True)]
        diff = revision_diff.diff_rows(old, new, year=1405)
        change = diff["changes"][0]
        self.assertEqual(change["kind"], "MODIFIED")
        self.assertEqual(change["fields"], ["holiday"])

    def test_cross_year_comparison_is_refused(self):
        with self.assertRaises(ValueError):
            revision_diff.diff_rows([row(1404, 1, 1, "الف")], [row(1405, 1, 1, "الف")],
                                    year=1404, new_year=1405)
        with self.assertRaises(ValueError):
            revision_diff.diff_rows([row(1404, 1, 1, "الف")], [], year=1405)

    def test_duplicates_are_reported(self):
        new = [row(1405, 1, 1, "روز الف"), row(1405, 1, 1, "روز الف")]
        diff = revision_diff.diff_rows([], new, year=1405)
        self.assertEqual(len(diff["duplicates"]), 1)
        self.assertEqual(diff["duplicates"][0]["count"], 2)

    def test_split_fragment_is_hinted(self):
        old = [row(1405, 1, 2, "هجوم مأموران ستم شاهی به مدرسه فیضیه قم و آغاز عملیات فتح‌المبین")]
        new = [row(1405, 1, 2, "هجوم مأموران ستم شاهی")]
        diff = revision_diff.diff_rows(old, new, year=1405)
        added = [c for c in diff["changes"] if c["kind"] == "ADDED"]
        self.assertTrue(added and added[0].get("suspectedSplit"))


class ReviewWorkflowTest(unittest.TestCase):

    def _baseline(self, rows=None):
        rows = rows or [row(1405, 1, 10, "آزمون سراسری", 2),
                        row(1405, 2, 1, "رویداد دوم", 3)]
        install({"R-1405-bbbb": (revision("R-1405-bbbb", 1405, "b" * 64), rows)})
        return store.load_history()

    def _bundle(self, rid: str, rows: list[dict], sha: str = "c" * 64):
        history = store.load_history()
        active = store.active_revisions(history["revisions"])[1405]
        old_rows = store.load_revision_rows(active)
        rev = revision(rid, 1405, sha, state="draft", at="2026-02-01T00:00:00Z")
        rev["extraction"]["rowCount"] = len(rows)
        diff = revision_diff.diff_rows(old_rows, rows, year=1405, new_year=1405)
        bundle = {"revision": rev, "rawRows": rows, "oldRevisionId": active["id"],
                  "diff": diff, "decisions": {}, "state": "pending",
                  "createdAt": store.now_iso()}
        store.write_json(review.bundle_path(rid), bundle)
        return bundle

    def test_approve_rename_and_add_then_revert(self):
        with TempStore():
            self._baseline()
            rows = [row(1405, 1, 10, "آزمون سراسری", 2),
                    row(1405, 2, 1, "رویداد دوم تازه", 3),
                    row(1405, 3, 1, "رویداد سوم", 4)]
            bundle = self._bundle("R-1405-cccc", rows)
            renamed = next(c for c in bundle["diff"]["changes"] if c["kind"] == "RENAMED")
            added = next(c for c in bundle["diff"]["changes"] if c["kind"] == "ADDED")
            review.decide("R-1405-cccc", renamed["id"], "approve", by="مدیر")
            review.decide("R-1405-cccc", added["id"], "approve", by="مدیر")
            result = review.finalize("R-1405-cccc", by="مدیر", note="تأیید آزمون")
            self.assertEqual(result["rows"], 3)
            history = store.load_history()
            active = store.active_revisions(history["revisions"])[1405]
            self.assertEqual(active["id"], "R-1405-cccc")
            self.assertEqual(len(history["occurrences"]), 3)
            self.assertEqual(history["changelog"][-1]["action"], "APPROVE")
            self.assertEqual(len(history["changelog"][-1]["snapshotBefore"]), 2)
            self.assertEqual(store.validate(history, expected=store.rebuild_from_revisions())[0:0], [])
            codes = {i["code"] for i in store.validate(history, expected=store.rebuild_from_revisions())}
            self.assertNotIn("OCC_NOT_DERIVED", codes)

            log = history["changelog"][-1]["id"]
            review.revert_log(log, by="مدیر", note="بازگردانی آزمون")
            after = store.load_history()
            self.assertEqual(len(after["occurrences"]), 2)
            self.assertEqual(after["changelog"][-1]["action"], "REVERT")
            self.assertTrue(store.active_revisions(after["revisions"])[1405]["id"].startswith("R-1405-revert-"))
            codes = {i["code"] for i in store.validate(after, expected=store.rebuild_from_revisions())}
            self.assertNotIn("OCC_NOT_DERIVED", codes)

    def test_rejected_change_is_not_applied(self):
        with TempStore():
            self._baseline()
            rows = [row(1405, 1, 10, "آزمون سراسری", 2),
                    row(1405, 2, 1, "رویداد دوم", 3),
                    row(1405, 3, 1, "رویداد سوم", 4)]
            bundle = self._bundle("R-1405-cccc", rows)
            added = next(c for c in bundle["diff"]["changes"] if c["kind"] == "ADDED")
            review.decide("R-1405-cccc", added["id"], "reject", by="مدیر")
            review.finalize("R-1405-cccc", by="مدیر")
            history = store.load_history()
            self.assertEqual(len(history["occurrences"]), 2)
            self.assertNotIn("E0003", {o["eventId"] for o in history["occurrences"]})

    def test_edit_changes_applied_title(self):
        with TempStore():
            self._baseline()
            rows = [row(1405, 1, 10, "آزمون سراسری", 2),
                    row(1405, 2, 1, "رویداد دوم", 3),
                    row(1405, 3, 1, "عنوانِ خام")]
            bundle = self._bundle("R-1405-cccc", rows)
            added = next(c for c in bundle["diff"]["changes"] if c["kind"] == "ADDED")
            review.decide("R-1405-cccc", added["id"], "edit", by="مدیر",
                          edit={"title": "رویداد سوم"})
            review.finalize("R-1405-cccc", by="مدیر")
            history = store.load_history()
            edited = [o for o in history["occurrences"] if o["eventId"] == "E0003"]
            self.assertEqual(len(edited), 1)
            self.assertEqual(edited[0]["observedTitle"], "رویداد سوم")

    def test_finalize_requires_decision_for_every_human_change(self):
        with TempStore():
            self._baseline()
            rows = [row(1405, 1, 10, "آزمون سراسری", 2),
                    row(1405, 2, 1, "رویداد دوم", 3),
                    row(1405, 3, 1, "رویداد سوم", 4)]
            bundle = self._bundle("R-1405-cccc", rows)
            self.assertTrue(any(c["requiresHuman"] for c in bundle["diff"]["changes"]))
            with self.assertRaises(ValueError):
                review.finalize("R-1405-cccc", by="مدیر")

    def test_same_document_gets_distinct_approved_revision(self):
        with TempStore():
            self._baseline()
            rows = [row(1405, 1, 10, "آزمون سراسری", 2),
                    row(1405, 2, 1, "رویداد دوم", 3),
                    row(1405, 3, 1, "رویداد سوم", 4)]
            self._bundle("R-1405-bbbb", rows, sha="b" * 64)
            added = next(c for c in review.load_bundle("R-1405-bbbb")["diff"]["changes"]
                         if c["kind"] == "ADDED")
            review.decide("R-1405-bbbb", added["id"], "approve", by="مدیر")
            result = review.finalize("R-1405-bbbb", by="مدیر")
            self.assertNotEqual(result["revision"]["id"], "R-1405-bbbb")
            self.assertTrue(result["revision"]["id"].startswith("R-1405-bbbb-review-"))
            history = store.load_history()
            old = next(r for r in history["revisions"] if r["id"] == "R-1405-bbbb")
            self.assertEqual(old["state"], "superseded")
            self.assertEqual(len(history["occurrences"]), 3)

    def test_stale_bundle_is_refused(self):
        with TempStore():
            self._baseline()
            rows = [row(1405, 1, 10, "آزمون سراسری", 2),
                    row(1405, 2, 1, "رویداد دوم", 3),
                    row(1405, 3, 1, "رویداد سوم", 4)]
            self._bundle("R-1405-cccc", rows)
            history = store.load_history()
            newer = revision("R-1405-eeee", 1405, "e" * 64, at="2026-03-01T00:00:00Z")
            store.save_revisions(history["revisions"] + [newer])
            store.save_revision_rows(newer["id"], 1405,
                                     [row(1405, 1, 10, "آزمون سراسری", 2)])
            bundle = review.load_bundle("R-1405-cccc")
            for change in bundle["diff"]["changes"]:
                if change["requiresHuman"]:
                    review.decide("R-1405-cccc", change["id"], "reject", by="مدیر")
            with self.assertRaises(ValueError):
                review.finalize("R-1405-cccc", by="مدیر")


class IngestTest(unittest.TestCase):

    def test_year_detection(self):
        info = ingest_pdf.detect_year("تقویم رسمی سال ۱۴۰۵ هجری شمسی\n۱۴۰۵ فروردین", "Calendar-1405.pdf")
        self.assertEqual(info["filename"], 1405)
        self.assertEqual(info["text"], 1405)
        self.assertFalse(info["conflict"])

    def test_fragment_detection(self):
        self.assertTrue(ingest_pdf.is_fragment(") 1343 هو ش("))
        self.assertFalse(ingest_pdf.is_fragment("عید نوروز"))

    def test_page_locator(self):
        loc = ingest_pdf.page_locator("سربرگ\nعید نوروز و آغاز سال\nپایان", "عید نوروز")
        self.assertEqual(loc["line"], 2)
        self.assertEqual(loc["page"], None)

    def test_real_pdf_extraction(self):
        pdf = ROOT / "PDF" / "Calendar-1405.pdf"
        if not pdf.exists():
            self.skipTest("PDF نمونه موجود نیست")
        revision_data, rows, parsed = ingest_pdf.build_revision(pdf, 1405)
        self.assertEqual(revision_data["year"], 1405)
        self.assertGreater(len(rows), 150)
        self.assertTrue(all(r["solar"][0] == 1405 for r in rows))
        with_locator = sum(1 for r in rows if r.get("locator"))
        self.assertGreater(with_locator / len(rows), 0.5)
        self.assertEqual(revision_data["state"], "draft")
        self.assertTrue(revision_data["document"]["sha256"])


if __name__ == "__main__":
    unittest.main()
