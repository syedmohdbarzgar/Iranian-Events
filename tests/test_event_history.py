"""آزمون‌های مدلِ تاریخ، مقایسهٔ نسخه‌ها و جریانِ تأیید/بازگردانی (فاز ۶).

همهٔ آزمون‌ها روی پوشهٔ موقت اجرا می‌شوند؛ دادهٔ واقعیِ مخزن دست‌نخورده می‌ماند.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import approval_ledger  # noqa: E402
import calendar_engine as engine  # noqa: E402
import history_store as store  # noqa: E402
import ingest_pdf  # noqa: E402
import review_changes as review  # noqa: E402
import review_server  # noqa: E402
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
        "approval": {"kind": "human", "method": "test", "by": "tester", "at": at,
                     "note": ""},
        "supersedes": None, "supersededBy": None,
    }


class TempStore:
    """مسیرهای store را موقت می‌کند تا آزمون به دادهٔ مخزن دست نزند."""

    NAMES = ("HISTORY_DIR", "REVISION_DIR", "EVENTS_FILE", "OCCURRENCES_FILE",
             "REVISIONS_FILE", "CHANGELOG_FILE", "IDENTITY_REVIEWS_FILE",
             "CHANGES_DIR", "INGEST_DIR")
    APPROVAL_NAMES = ("APPROVAL_DIR", "LEDGER_FILE", "TRUST_FILE")

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
        store.IDENTITY_REVIEWS_FILE = history / "identity-reviews.json"
        store.CHANGES_DIR = root / "review" / "changes"
        store.INGEST_DIR = root / "review" / "ingest"
        review.CHANGES_DIR = store.CHANGES_DIR
        store.master_catalog = lambda: [dict(e) for e in CATALOG]
        self.saved_approval = {name: getattr(approval_ledger, name)
                               for name in self.APPROVAL_NAMES}
        approval_ledger.APPROVAL_DIR = history / "approvals"
        approval_ledger.LEDGER_FILE = approval_ledger.APPROVAL_DIR / "ledger.json"
        approval_ledger.TRUST_FILE = approval_ledger.APPROVAL_DIR / "trusted-keys.json"
        return root

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(store, name, value)
        for name, value in self.saved_approval.items():
            setattr(approval_ledger, name, value)
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
            before = store.load_history()
            with self.assertRaises(ValueError):
                review.finalize("R-1405-cccc", by="مدیر")
            after = store.load_history()
            self.assertEqual(len(after["occurrences"]), len(before["occurrences"]))
            self.assertEqual(len(after["revisions"]), len(before["revisions"]))
            self.assertEqual(after["changelog"], before["changelog"])

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

    def test_pdf_pages_have_no_phantom_trailing_page(self):
        pdf = ROOT / "PDF" / "Calendar-1405.pdf"
        if not pdf.exists():
            self.skipTest("PDF نمونه موجود نیست")
        pages = ingest_pdf.page_texts(pdf)
        self.assertEqual(len(pages), 17)
        self.assertTrue(pages[-1].strip())

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


class OcrLinkTest(unittest.TestCase):
    """OCR باید واقعاً به ردیف/تاریخ تبدیل شود، نه فقط ذخیره شود."""

    TEXT = ("۲ فروردین ۱۴۰۵ عید نوروز تعطیل\n"
            "۵ فروردین ۱۴۰۵ زادروز زرتشت\n"
            "جشن بهاری بدون تاریخ\n"
            "۱۴۰۵/۰۱/۱۳ سیزده‌بدر تعطیل")

    def test_ocr_metadata_keeps_engine_page_and_image_hash(self):
        rows = ingest_pdf.parse_ocr_page(
            self.TEXT, 1405, 17,
            ocr_meta={"engine": "tesseract.js", "lang": "fas", "confidence": 61,
                      "image": "reports/ocr/images/page-017.png", "imageSha256": "a" * 64})
        self.assertTrue(rows)
        self.assertEqual(rows[0]["ocr"]["engine"], "tesseract.js")
        self.assertEqual(rows[0]["ocr"]["page"], 17)
        self.assertEqual(rows[0]["ocr"]["imageSha256"], "a" * 64)
        self.assertEqual(rows[0]["ocr"]["line"], 1)

    def test_explicit_ocr_dates_become_rows(self):
        rows = ingest_pdf.parse_ocr_page(self.TEXT, 1405, 18)
        self.assertEqual([r["solar"] for r in rows],
                         [[1405, 1, 2], [1405, 1, 5], [1405, 1, 13]])
        first = rows[0]
        self.assertEqual(first["title"], "عید نوروز")
        self.assertTrue(first["holiday"])
        self.assertTrue(first["needsReview"])
        self.assertIn("ocr-row", first["flags"])
        self.assertLess(first["confidence"], 0.8)
        self.assertEqual(first["page"], 18)
        self.assertEqual(first["gregorian"], list(engine.jalali_to_gregorian(1405, 1, 2)))

    def test_ocr_without_explicit_date_never_invents_a_row(self):
        self.assertEqual(ingest_pdf.parse_ocr_page("عید نوروز تعطیل", 1405, 18), [])

    def test_ocr_merge_does_not_overwrite_text_layer(self):
        base = [row(1405, 1, 2, "عید نوروز", 18)]
        base[0]["source"] = "text-layer"
        ocr = ingest_pdf.parse_ocr_page(self.TEXT, 1405, 18)
        merged = ingest_pdf.merge_ocr_rows(base, ocr)
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0]["title"], "عید نوروز")
        self.assertEqual(merged[0]["source"], "text-layer")

    def test_real_pdf_uses_injected_ocr_text(self):
        pdf = ROOT / "PDF" / "Calendar-1405.pdf"
        if not pdf.exists():
            self.skipTest("PDF نمونه موجود نیست")
        revision_data, rows, _ = ingest_pdf.build_revision(
            pdf, 1405, ocr_texts={17: self.TEXT})
        extraction = revision_data["extraction"]
        self.assertEqual(extraction["method"], "mixed")
        self.assertEqual(extraction["ocrRows"], 3)
        self.assertEqual(extraction["ocrPagesParsed"], [17])
        ocr_rows = [r for r in rows if str(r.get("source", "")).startswith("ocr")]
        self.assertEqual(len(ocr_rows), 3)
        self.assertTrue(all(r["needsReview"] for r in ocr_rows))
        self.assertTrue(all(r["solar"][0] == 1405 for r in ocr_rows))


class ApprovalProvenanceTest(unittest.TestCase):

    def test_missing_approval_is_an_error(self):
        rev = revision("R-1405-aaaa", 1405, "a" * 64)
        rev.pop("approval")
        codes = {i["code"] for i in store.validate(
            {"events": [], "occurrences": [], "revisions": [rev], "changelog": []})}
        self.assertIn("REV_APPROVAL_MISSING", codes)

    def test_baseline_cannot_pose_as_human_approval(self):
        rev = revision("R-1405-aaaa", 1405, "a" * 64)
        rev["approvedBy"] = store.BASELINE_ACTOR
        rev["approval"] = {"kind": "human", "method": "review", "by": "x", "at": "now"}
        codes = {i["code"] for i in store.validate(
            {"events": [], "occurrences": [], "revisions": [rev], "changelog": []})}
        self.assertIn("REV_HUMAN_ACTOR", codes)

    def test_finalize_records_human_origin(self):
        with TempStore():
            install({"R-1405-bbbb": (revision("R-1405-bbbb", 1405, "b" * 64), [
                row(1405, 1, 10, "آزمون سراسری", 2)])})
            rows = [row(1405, 1, 10, "آزمون سراسری", 2),
                    row(1405, 2, 1, "رویداد دوم", 3)]
            rev = revision("R-1405-cccc", 1405, "c" * 64, state="draft")
            diff = revision_diff.diff_rows([row(1405, 1, 10, "آزمون سراسری", 2)], rows,
                                           year=1405, new_year=1405)
            store.write_json(review.bundle_path("R-1405-cccc"), {
                "revision": rev, "rawRows": rows, "oldRevisionId": "R-1405-bbbb",
                "diff": diff, "decisions": {}, "state": "pending",
                "createdAt": store.now_iso()})
            added = next(c for c in diff["changes"] if c["kind"] == "ADDED")
            review.decide("R-1405-cccc", added["id"], "approve", by="مدیر")
            result = review.finalize("R-1405-cccc", by="مدیر")
            approval = result["revision"]["approval"]
            self.assertEqual(approval["kind"], "human")
            self.assertEqual(approval["method"], "review")
            self.assertEqual(approval["by"], "مدیر")


class IdentityReviewTest(unittest.TestCase):

    TITLE = ("عنوانِ ساختگیِ بسیار بلند برای آزمونِ ردیفِ چسبیده که هیچ تطبیقِ کاتالوگی "
             "ندارد و باید به‌عنوانِ هویتِ ردیفی بماند")

    def _signed(self, entry: dict) -> dict:
        """تصمیم را با کلیدِ موقتِ آزمون امضا می‌کند؛ تأییدِ بدونِ امضا معتبر نیست."""
        if entry.get("active") is False:
            return entry
        key = store.HISTORY_DIR.parent / "approval-key.json"
        if not key.exists():
            approval_ledger.generate_key(key, owner="user:test")
        record = approval_ledger.append_action(
            entry, key, action="approve", approver="user:test", channel="test")
        return {**entry, "active": True,
                "approval": approval_ledger.attached_approval(entry, record)}

    def _derive(self, review_entry: dict):
        rev = revision("R-1405-bbbb", 1405, "b" * 64)
        rows = [row(1405, 1, 10, self.TITLE, 2)]
        store.save_revision_rows(rev["id"], 1405, rows)
        signed = self._signed(review_entry)
        reviews = {signed["eventId"]: signed}
        return store.derive(CATALOG, [rev], {rev["id"]: rows}, identity_reviews=reviews)

    def test_keep_documents_without_merging(self):
        with TempStore():
            eid = store.synthetic_event_id(store.identity_key(self.TITLE))
            events, occ = self._derive({
                "eventId": eid, "decision": "keep-merged-row",
                "reason": "چند رویداد در یک سطر", "evidence": [],
                "constituents": [{"id": "E0001", "title": "آزمون سراسری"}],
                "reviewedBy": "مدیر", "reviewedAt": "2026-01-01T00:00:00Z"})
            ev = next(e for e in events if e["id"] == eid)
            self.assertFalse(ev["needsReview"])
            self.assertEqual(ev["review"]["decision"], "keep-merged-row")
            self.assertEqual({o["eventId"] for o in occ}, {eid})

    def test_disabled_review_is_reversible(self):
        with TempStore():
            eid = store.synthetic_event_id(store.identity_key(self.TITLE))
            events, _ = self._derive({
                "eventId": eid, "active": False, "decision": "keep-merged-row",
                "reason": "آزمونِ خاموشی", "evidence": [],
                "constituents": [], "reviewedBy": "مدیر",
                "reviewedAt": "2026-01-01T00:00:00Z"})
            ev = next(e for e in events if e["id"] == eid)
            self.assertTrue(ev["needsReview"])
            self.assertNotIn("review", ev)

    def test_map_uses_explicit_target(self):
        with TempStore():
            eid = store.synthetic_event_id(store.identity_key(self.TITLE))
            events_, occ = self._derive({
                "eventId": eid, "decision": "map", "target": "E0001",
                "reason": "همان رویداد با شاهد", "evidence": [],
                "constituents": [{"id": "E0001", "title": "آزمون سراسری"}],
                "reviewedBy": "مدیر", "reviewedAt": "2026-01-01T00:00:00Z"})
            self.assertFalse([e for e in events_ if e["id"] == eid])
            self.assertEqual({o["eventId"] for o in occ}, {"E0001"})

    def test_review_requires_explicit_human_approval(self):
        with TempStore():
            eid = store.synthetic_event_id(store.identity_key(self.TITLE))
            entry = {"eventId": eid, "decision": "keep-merged-row",
                     "reason": "آزمون", "evidence": [{"revisionId": "R-1405-bbbb", "page": 2}],
                     "reviewedBy": "مدیر", "reviewedAt": "2026-01-01T00:00:00Z"}
            codes = {i["code"] for i in store.validate(
                {"events": [{"id": eid}], "occurrences": [],
                 "revisions": [revision("R-1405-bbbb", 1405, "b" * 64)], "changelog": []},
                identity_reviews=[entry])}
            self.assertIn("REVIEW_APPROVAL_MISSING", codes)

    def test_unknown_target_is_reported(self):
        with TempStore():
            eid = store.synthetic_event_id(store.identity_key(self.TITLE))
            entry = {"eventId": eid, "decision": "map", "target": "E9999",
                     "reason": "آزمون", "evidence": [{"revisionId": "R-1405-bbbb", "page": 2}],
                     "reviewedBy": "مدیر", "reviewedAt": "2026-01-01T00:00:00Z"}
            codes = {i["code"] for i in store.validate(
                {"events": [{"id": "E0001"}], "occurrences": [],
                 "revisions": [revision("R-1405-bbbb", 1405, "b" * 64)], "changelog": []},
                identity_reviews=[entry])}
            self.assertIn("REVIEW_TARGET_MISSING", codes)


class ApprovalSecurityTest(unittest.TestCase):
    """P0-02/P0-05: تأییدِ JSONی و امضای جعلی نباید از گیت بگذرد."""

    TITLE = IdentityReviewTest.TITLE

    def _entry(self):
        return {
            "eventId": store.synthetic_event_id(store.identity_key(self.TITLE)),
            "decision": "keep-merged-row", "target": None,
            "reason": "آزمونِ امنیتِ تأیید",
            "constituents": [], "evidence": [],
            "reviewedBy": "proposal:test", "reviewedAt": "2026-01-01T00:00:00Z",
        }

    def _signed(self):
        entry = self._entry()
        key = store.HISTORY_DIR.parent / "approval-key.json"
        approval_ledger.generate_key(key, owner="user:test")
        record = approval_ledger.append_action(
            entry, key, action="approve", approver="user:test", channel="test")
        return {**entry, "active": True,
                "approval": approval_ledger.attached_approval(entry, record)}

    def test_unsigned_human_claim_is_rejected(self):
        with TempStore():
            entry = dict(self._entry(), active=True,
                         approval={"kind": "human", "by": "user:forged",
                                   "at": "2026-01-01T00:00:00Z"})
            codes = {i["code"] for i in approval_ledger.verify_entry(entry)}
            self.assertIn("REVIEW_APPROVAL_UNSIGNED", codes)
            self.assertFalse(approval_ledger.is_approved(entry))

    def test_edited_decision_invalidates_signature(self):
        with TempStore():
            entry = self._signed()
            self.assertTrue(approval_ledger.is_approved(entry))
            entry["reason"] = "علتِ عوض‌شده پس از امضا"
            codes = {i["code"] for i in approval_ledger.verify_entry(entry)}
            self.assertIn("APPROVAL_STATEMENT_MISMATCH", codes)
            self.assertFalse(approval_ledger.is_approved(entry))

    def test_forged_approval_does_not_reach_derived_data(self):
        with TempStore():
            fake = dict(self._entry(), active=True,
                        approval={"kind": "human", "method": "ed25519",
                                  "by": "user:forged", "at": "2026-01-01T00:00:00Z",
                                  "keyId": "ed25519:forged", "publicKey": "AAAA",
                                  "signature": "AAAA", "statementSha256": "0" * 64})
            rev = revision("R-1405-bbbb", 1405, "b" * 64)
            rows = [row(1405, 1, 10, self.TITLE, 2)]
            store.save_revision_rows(rev["id"], 1405, rows)
            events, _ = store.derive(CATALOG, [rev], {rev["id"]: rows},
                                     identity_reviews={fake["eventId"]: fake})
            ev = next(e for e in events if e["id"] == fake["eventId"])
            self.assertTrue(ev["needsReview"])
            self.assertNotIn("review", ev)

    def test_ledger_tamper_and_untrusted_key_are_detected(self):
        with TempStore():
            signed = self._signed()
            document = approval_ledger.ledger_document()
            document["entries"][0]["note"] = "دست‌کاری"
            approval_ledger.write_json(approval_ledger.LEDGER_FILE, document)
            codes = {i["code"] for i in approval_ledger.verify_ledger(
                approval_ledger.ledger_document()["entries"])}
            self.assertIn("APPROVAL_LEDGER_HASH", codes)
            approval_ledger.TRUST_FILE.unlink()
            codes = {i["code"] for i in approval_ledger.verify_entry(signed)}
            self.assertIn("APPROVAL_KEY_UNTRUSTED", codes)


class UploadSecurityTest(unittest.TestCase):

    @staticmethod
    def valid_pdf() -> bytes:
        source = ROOT / "PDF" / "Calendar-1405.pdf"
        if source.exists():
            return source.read_bytes()
        import pymupdf
        doc = pymupdf.open()
        doc.new_page()
        return doc.tobytes()

    def test_rejects_non_pdf_and_bad_magic(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                review_server.save_upload("x.txt", b"%PDF-1.7 data", Path(tmp))
            with self.assertRaises(ValueError):
                review_server.save_upload("x.pdf", b"not a pdf", Path(tmp))

    def test_rejects_corrupt_pdf_with_valid_magic(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                review_server.save_upload("broken.pdf", b"%PDF-1.7\n" + b"x" * 200, Path(tmp))

    def test_rejects_oversized_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(review_server, "MAX_UPLOAD", 64):
                with self.assertRaises(ValueError):
                    review_server.save_upload("big.pdf", self.valid_pdf(), Path(tmp))

    def test_sanitizes_name_and_never_touches_pdf_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.valid_pdf()
            target = review_server.save_upload("../../evil name.pdf", payload, Path(tmp))
            self.assertEqual(target.parent, Path(tmp))
            self.assertNotIn("..", target.name)
            self.assertTrue(target.name.endswith("evil_name.pdf"))
            self.assertEqual(target.read_bytes(), payload)
            again = review_server.save_upload("evil name.pdf", payload, Path(tmp))
            self.assertEqual(again, target)
            self.assertFalse((ROOT / "PDF" / "evil_name.pdf").exists())

    def test_multipart_parser(self):
        body = (b'--X\r\nContent-Disposition: form-data; name="year"\r\n\r\n1405\r\n'
                b'--X\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n'
                b'Content-Type: application/pdf\r\n\r\n%PDF-1.7 x\r\n--X--\r\n')
        fields = review_server.parse_multipart(body, "multipart/form-data; boundary=X")
        self.assertEqual(fields["year"], (None, b"1405"))
        self.assertEqual(fields["file"][0], "a.pdf")
        self.assertEqual(fields["file"][1], b"%PDF-1.7 x")


if __name__ == "__main__":
    unittest.main()
