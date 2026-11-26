"""آزمون‌های P0/P1 پنلِ بازبینیِ انسانی.

پوشه‌ها و کلیدها موقت‌اند. آزمون‌ها به دادهٔ واقعی یا حسابِ واقعی دست نمی‌زنند.
"""
from __future__ import annotations

import copy
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import calendar_engine as engine  # noqa: E402
import history_store as store  # noqa: E402
import review_audit  # noqa: E402
import review_changes as review  # noqa: E402
import review_model  # noqa: E402
import review_panel  # noqa: E402
import review_server  # noqa: E402
import reviewer_auth  # noqa: E402
import revision_diff  # noqa: E402

CATALOG = [
    {"id": "E0001", "title": "آزمون سراسری", "category": "official", "calendar": "solar",
     "recurrenceType": "A", "origin": {"kind": "established", "label": "سند", "note": "",
                                       "source": "test#1"},
     "verificationStatus": "partially_verified", "solar_dates": [[1, 10]]},
    {"id": "E0002", "title": "رویداد دوم", "category": "official", "calendar": "solar",
     "recurrenceType": "A", "origin": {"kind": "tradition", "label": "سنتی", "note": "",
                                       "source": ""},
     "verificationStatus": "traditional", "solar_dates": [[2, 1]]},
    {"id": "E0003", "title": "رویداد سوم", "category": "official", "calendar": "solar",
     "recurrenceType": "A", "origin": None, "verificationStatus": "partially_verified",
     "solar_dates": [[3, 1]]},
]


def row(year: int, m: int, d: int, title: str, page: int = 1) -> dict:
    return {"solar": [year, m, d], "gregorian": list(engine.jalali_to_gregorian(year, m, d)),
            "lunar": [None, None, None], "weekday": None, "title": title,
            "holiday": False, "page": page, "derived": []}


def revision(rid: str, year: int, sha: str) -> dict:
    return {
        "id": rid, "year": year,
        "document": {"file": f"Calendar-{year}.pdf", "sha256": sha, "bytes": 10,
                     "pages": 2, "storedPath": f"PDF/Calendar-{year}.pdf"},
        "extraction": {"method": "text-layer", "tool": "test", "extractedAt": "2026-01-01T00:00:00Z",
                       "rowCount": 0, "rawRowCount": 0, "qcProblems": 0},
        "state": "approved", "approvedBy": "tester", "approvedAt": "2026-01-01T00:00:00Z",
        "note": "", "approval": {"kind": "human", "method": "test", "by": "tester",
                                 "at": "2026-01-01T00:00:00Z", "note": ""},
        "supersedes": None, "supersededBy": None,
    }


class TempReview:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.saved_store = {n: getattr(store, n) for n in (
            "HISTORY_DIR", "REVISION_DIR", "EVENTS_FILE", "OCCURRENCES_FILE",
            "REVISIONS_FILE", "CHANGELOG_FILE", "IDENTITY_REVIEWS_FILE", "CHANGES_DIR",
            "INGEST_DIR")}
        self.saved_review_dir = review.CHANGES_DIR
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
        store.master_catalog = lambda: [copy.deepcopy(e) for e in CATALOG]
        self.saved_audit = review_audit.AUDIT_FILE
        self.saved_reviewers = reviewer_auth.REVIEWERS_FILE
        self.saved_keys = reviewer_auth.KEY_DIR
        review_audit.AUDIT_FILE = root / "review" / "review-audit-log.json"
        reviewer_auth.REVIEWERS_FILE = root / "review" / "reviewers.json"
        reviewer_auth.KEY_DIR = root / ".review-keys"
        self.root = root
        self.reviewers_file = reviewer_auth.REVIEWERS_FILE
        self.audit_file = review_audit.AUDIT_FILE
        return self

    def __exit__(self, *exc):
        for name, value in self.saved_store.items():
            setattr(store, name, value)
        review.CHANGES_DIR = self.saved_review_dir
        store.master_catalog = self.saved_master
        review_audit.AUDIT_FILE = self.saved_audit
        reviewer_auth.REVIEWERS_FILE = self.saved_reviewers
        reviewer_auth.KEY_DIR = self.saved_keys
        self.tmp.cleanup()


def install_baseline() -> dict:
    base = revision("R-1405-bbbb", 1405, "b" * 64)
    rows = [row(1405, 1, 10, "آزمون سراسری", 2), row(1405, 2, 1, "رویداد دوم", 3)]
    base["extraction"]["rowCount"] = len(rows)
    store.save_revision_rows(base["id"], 1405, rows, source=base["document"])
    store.save_revisions([base])
    events, occurrences = store.derive(CATALOG, [base], {base["id"]: rows})
    store.save_history(events, occurrences)
    return base


def make_bundle(rid: str, rows: list[dict]) -> dict:
    history = store.load_history()
    active = store.active_revisions(history["revisions"])[1405]
    old_rows = store.load_revision_rows(active)
    rev = revision(rid, 1405, "c" * 64)
    rev["state"] = "draft"
    rev["extraction"]["rowCount"] = len(rows)
    diff = revision_diff.diff_rows(old_rows, rows, year=1405, new_year=1405)
    bundle = {"revision": rev, "rawRows": rows, "oldRevisionId": active["id"],
              "diff": diff, "decisions": {}, "state": "pending",
              "createdAt": store.now_iso()}
    store.write_json(review.bundle_path(rid), bundle)
    return bundle


def session_for(temp: TempReview, reviewer_id: str = "reviewer-1") -> dict:
    reviewer_auth.register(reviewer_id, f"بازبین {reviewer_id}", "correct horse battery")
    return reviewer_auth.authenticate(reviewer_id, "correct horse battery",
                                      reviewers_file=temp.reviewers_file,
                                      key_dir=reviewer_auth.KEY_DIR)


class DateAndStatusTest(unittest.TestCase):

    def test_period_keeps_source_and_detects_multi_day(self):
        p = review_model.normalize_period(
            {"start": {"calendar": "solar", "date": [1405, 1, 10]},
             "end": {"calendar": "solar", "date": [1405, 1, 12]}},
            1405, [1405, 1, 1])
        self.assertEqual(p["startSolar"], [1405, 1, 10])
        self.assertEqual(p["endSolar"], [1405, 1, 12])
        self.assertTrue(p["multiDay"])
        self.assertEqual(p["source"]["calendar"], "solar")
        self.assertEqual(p["conversion"]["algorithm"], review_model.ALGORITHM)
        self.assertEqual(p["conversion"]["version"], review_model.ALGORITHM_VERSION)

    def test_lunar_and_gregorian_are_converted_with_metadata(self):
        lunar = review_model.normalize_period(
            {"start": {"calendar": "lunar", "date": [1447, 10, 2]}},
            1405, [1405, 1, 1])
        self.assertEqual(lunar["startSolar"], [1405, 1, 1])
        self.assertEqual(lunar["source"]["startCalendar"], "lunar")
        self.assertEqual(lunar["conversion"]["from"], "lunar")
        greg = review_model.normalize_period(
            {"start": {"calendar": "gregorian", "date": [2026, 3, 22]}},
            1405, [1405, 1, 1])
        self.assertEqual(greg["startSolar"], [1405, 1, 2])
        self.assertFalse(greg["multiDay"])

    def test_lunar_year_must_match_the_converted_solar_date(self):
        self.assertEqual(review_model.lunar_to_solar(1405, [1447, 10, 2]),
                         [1405, 1, 1])
        with self.assertRaises(ValueError):
            review_model.lunar_to_solar(1405, [1446, 10, 2])
        with self.assertRaises(ValueError):
            review_model.lunar_to_solar(1405, [1447, 13, 1])
        with self.assertRaises(ValueError):
            review_model.lunar_to_solar(1405, [1447, 10, 31])

    def test_lunar_boundary_dates_round_trip_inside_the_solar_year(self):
        for solar in ([1405, 1, 1], [1405, 6, 31], [1405, 12, 29]):
            lunar = list(review_model.lunar_from_solar(*solar))
            self.assertEqual(review_model.lunar_to_solar(1405, lunar), solar)

    def test_start_and_end_keep_independent_calendars(self):
        p = review_model.normalize_period(
            {"start": {"calendar": "lunar", "date": [1447, 10, 2]},
             "end": {"calendar": "gregorian", "date": [2026, 3, 24]}},
            1405, [1405, 1, 1])
        self.assertEqual(p["startSolar"], [1405, 1, 1])
        self.assertEqual(p["endSolar"], [1405, 1, 4])
        self.assertEqual(p["source"]["startCalendar"], "lunar")
        self.assertEqual(p["source"]["endCalendar"], "gregorian")
        self.assertEqual(p["conversion"]["startFrom"], "lunar")
        self.assertEqual(p["conversion"]["endFrom"], "gregorian")

    def test_invalid_day_month_and_reverse_period_are_refused(self):
        with self.assertRaises(ValueError):
            review_model.validate_solar(1405, [1405, 12, engine.month_len(1405, 12) + 1])
        with self.assertRaises(ValueError):
            review_model.validate_solar(1405, [1405, 13, 1])
        with self.assertRaises(ValueError):
            review_model.normalize_period(
                {"start": {"calendar": "solar", "date": [1405, 2, 2]},
                 "end": {"calendar": "solar", "date": [1405, 1, 1]}},
                1405, [1405, 1, 1])

    def test_six_statuses_are_distinct(self):
        bundle = {"revision": {"id": "R", "year": 1405, "document": {"sha256": "x"}},
                  "state": "pending", "decisions": {},
                  "diff": {"changes": [{"id": "C1", "kind": "MODIFIED",
                                        "requiresHuman": True, "before": {"solar": [1405, 1, 1]},
                                        "after": {"solar": [1405, 1, 1]}}]}}
        self.assertEqual(review_model.status_for(bundle, bundle["diff"]["changes"][0]),
                         review_model.STATUS_PENDING)
        bundle["decisions"]["C1"] = {"action": "needs-evidence"}
        self.assertEqual(review_model.status_for(bundle, bundle["diff"]["changes"][0]),
                         review_model.STATUS_NEEDS_EVIDENCE)
        bundle["decisions"]["C1"] = {"action": "reject"}
        self.assertEqual(review_model.status_for(bundle, bundle["diff"]["changes"][0]),
                         review_model.STATUS_REJECTED)
        bundle["decisions"]["C1"] = {"action": "approve"}
        self.assertEqual(review_model.status_for(bundle, bundle["diff"]["changes"][0]),
                         review_model.STATUS_APPROVED)
        bundle["decisions"]["C1"] = {"action": "approve", "edited": True}
        self.assertEqual(review_model.status_for(bundle, bundle["diff"]["changes"][0]),
                         review_model.STATUS_CORRECTED)
        bundle["diff"]["changes"][0]["requiresHuman"] = False
        bundle["decisions"] = {}
        self.assertEqual(review_model.status_for(bundle, bundle["diff"]["changes"][0]),
                         review_model.STATUS_DRAFT)

    def test_stable_id_does_not_depend_on_diff_order_or_decision(self):
        bundle = {"revision": {"id": "R-1405-x", "year": 1405,
                               "document": {"sha256": "a" * 64}},
                  "decisions": {},
                  "diff": {"changes": [
                      {"id": "C1", "kind": "ADDED", "dateKey": "01-01",
                       "after": {"page": 2, "titleRaw": "رویداد", "solar": [1405, 1, 1]}},
                      {"id": "C2", "kind": "REMOVED", "dateKey": "01-02",
                       "before": {"page": 3, "titleRaw": "دیگر", "solar": [1405, 1, 2]}},
                  ]}}
        first = review_model.event_review_id(bundle, bundle["diff"]["changes"][0])
        bundle["diff"]["changes"].reverse()
        bundle["decisions"]["C1"] = {"action": "approve"}
        second = review_model.event_review_id(bundle, bundle["diff"]["changes"][1])
        self.assertEqual(first, second)
        self.assertRegex(first, r"^H-[0-9A-F]{16}$")


class AuthAndAuditTest(unittest.TestCase):

    def test_agent_names_cannot_register_or_confirm(self):
        with self.assertRaises(ValueError):
            reviewer_auth.validate_reviewer_id("agent:fake-human")
        with self.assertRaises(ValueError):
            review._human_actor("ai:auto")
        with self.assertRaises(ValueError):
            review._human_actor("")

    def test_password_and_key_signature(self):
        with TempReview() as temp:
            session = session_for(temp)
            self.assertEqual(session["reviewerId"], "reviewer-1")
            self.assertTrue(session["keyId"].startswith("ed25519:"))
            payload = {"x": "y"}
            signature = reviewer_auth.sign(session, payload)
            self.assertTrue(reviewer_auth.verify(session["publicKey"], payload, signature))
            self.assertFalse(reviewer_auth.verify(session["publicKey"], {"x": "z"}, signature))
            with self.assertRaises(ValueError):
                reviewer_auth.authenticate("reviewer-1", "wrong password",
                                           reviewers_file=temp.reviewers_file,
                                           key_dir=reviewer_auth.KEY_DIR)

    def test_audit_chain_detects_edit_delete_reorder_and_duplicate(self):
        with TempReview() as temp:
            session = session_for(temp)
            review_audit.append(session, "decision", {"revisionId": "R", "action": "approve"})
            review_audit.append(session, "decision", {"revisionId": "R", "action": "reject"})
            entries = review_audit.load_entries(temp.audit_file)
            trusted = {session["keyId"]: session["publicKey"]}
            self.assertEqual(review_audit.verify_entries(entries, trusted), [])

            edited = copy.deepcopy(entries)
            edited[0]["payload"]["action"] = "reject"
            codes = {i["code"] for i in review_audit.verify_entries(edited, trusted)}
            self.assertIn("AUDIT_HASH", codes)

            deleted = [copy.deepcopy(entries[1])]
            codes = {i["code"] for i in review_audit.verify_entries(deleted, trusted)}
            self.assertIn("AUDIT_CHAIN", codes)

            reordered = [copy.deepcopy(entries[1]), copy.deepcopy(entries[0])]
            codes = {i["code"] for i in review_audit.verify_entries(reordered, trusted)}
            self.assertTrue({"AUDIT_CHAIN", "AUDIT_GAP"} & codes)

            duplicated = [copy.deepcopy(entries[0]), copy.deepcopy(entries[0])]
            codes = {i["code"] for i in review_audit.verify_entries(duplicated, trusted)}
            self.assertIn("AUDIT_SEQ", codes)

    def test_signed_head_detects_tail_truncation(self):
        with TempReview() as temp:
            session = session_for(temp)
            review_audit.append(session, "decision", {"revisionId": "R", "action": "approve"})
            review_audit.append(session, "decision", {"revisionId": "R", "action": "reject"})
            self.assertEqual(review_audit.verify_file(temp.audit_file, temp.reviewers_file), [])
            document = json.loads(temp.audit_file.read_text(encoding="utf-8"))
            document["entries"] = document["entries"][:-1]
            temp.audit_file.write_text(json.dumps(document), encoding="utf-8")
            codes = {i["code"] for i in review_audit.verify_file(
                temp.audit_file, temp.reviewers_file)}
            self.assertIn("AUDIT_TRUNCATED", codes)

    def test_self_signed_key_outside_roster_is_not_trusted(self):
        with TempReview() as temp:
            session = session_for(temp)
            entry = review_audit.append(session, "decision", {"revisionId": "R",
                                                               "action": "approve"})
            self.assertTrue(review_audit.verify_entry(entry, {session["keyId"]: session["publicKey"]}) == [])
            codes = {i["code"] for i in review_audit.verify_entry(entry, {"ed25519:other": "x"})}
            self.assertIn("AUDIT_KEY_UNTRUSTED", codes)


class PanelFlowTest(unittest.TestCase):

    def _complete(self, temp: TempReview, session: dict, rid: str = "R-1405-cccc",
                  action: str = "approve") -> dict:
        install_baseline()
        bundle = make_bundle(rid, [row(1405, 1, 10, "آزمون سراسری", 2),
                                   row(1405, 2, 1, "رویداد دوم", 3),
                                   row(1405, 3, 1, "رویداد سوم", 4)])
        for change in bundle["diff"]["changes"]:
            if change.get("requiresHuman"):
                review_panel.decide(session, {"revision": rid, "change": change["id"],
                                              "action": action,
                                              "reason": "بررسیِ سند" if action == "reject" else ""})
        return review.load_bundle(rid)

    def test_locked_years_cannot_be_finalized_even_with_empty_packet(self):
        with TempReview() as temp:
            session = session_for(temp)
            install_baseline()
            rev = revision("R-1393-locked", 1393, "d" * 64)
            rev["state"] = "draft"
            bundle = {"revision": rev, "rawRows": [], "oldRevisionId": None,
                      "diff": {"changes": [], "counts": {}, "duplicates": []},
                      "decisions": {}, "state": "pending", "createdAt": store.now_iso()}
            store.write_json(review.bundle_path("R-1393-locked"), bundle)
            with self.assertRaises(review_panel.PanelError):
                review_panel.year_approval(session, {"revision": "R-1393-locked"})
            with self.assertRaises(ValueError):
                review.finalize("R-1393-locked", by="reviewer-1")
            self.assertIn(1393, review_model.LOCKED_YEARS)

    def test_unapproved_row_is_not_published(self):
        with TempReview() as temp:
            session = session_for(temp)
            install_baseline()
            make_bundle("R-1405-cccc", [row(1405, 1, 10, "آزمون سراسری", 2),
                                        row(1405, 2, 1, "رویداد دوم", 3),
                                        row(1405, 3, 1, "رویداد سوم", 4)])
            before = store.load_history()
            with self.assertRaises(review_panel.PanelError):
                review_panel.year_approval(session, {"revision": "R-1405-cccc"})
            after = store.load_history()
            self.assertEqual(len(after["occurrences"]), len(before["occurrences"]))
            self.assertEqual(after["changelog"], before["changelog"])
            self.assertEqual(review_audit.load_entries(), [])

    def test_signed_year_approval_and_bundle_hash_gate(self):
        with TempReview() as temp:
            session = session_for(temp)
            bundle = self._complete(temp, session)
            self.assertTrue(review_model.all_requires_human_resolved(bundle))
            result = review_panel.year_approval(session, {"revision": "R-1405-cccc",
                                                           "note": "تأیید مستقل سال"})
            self.assertTrue(result["revision"].startswith("R-1405-"))
            entries = review_audit.load_entries()
            self.assertEqual([e["action"] for e in entries], ["decision"] * sum(
                1 for c in bundle["diff"]["changes"] if c.get("requiresHuman")) +
                ["year-approval", "finalize"])
            year_entry = next(e for e in entries if e["action"] == "year-approval")
            self.assertEqual(review_audit.verify_entry(
                year_entry, {session["keyId"]: session["publicKey"]}), [])
            history = store.load_history()
            active = store.active_revisions(history["revisions"])[1405]
            self.assertEqual(active["approval"]["method"], "ed25519-review")
            self.assertEqual(active["approval"]["auditSeq"], year_entry["seq"])
            self.assertEqual(active["approval"]["signature"], year_entry["signature"])
            self.assertEqual(active["approval"]["bundleHash"],
                             review_model.approval_bundle_hash(bundle))
            history["revisions"] = [
                ({**rev, "approval": {**rev["approval"], "signature": "forged"}}
                 if rev["id"] == result["revision"] else rev)
                for rev in history["revisions"]]
            store.save_revisions(history["revisions"])
            codes = {i["code"] for i in review_audit.verify_revision_approvals()}
            self.assertIn("REV_APPROVAL_SIGNATURE", codes)

    def test_bundle_changed_after_year_approval_is_refused(self):
        with TempReview() as temp:
            session = session_for(temp)
            bundle = self._complete(temp, session)
            year_entry = review_audit.append(session, "year-approval", {
                "revisionId": "R-1405-cccc", "year": 1405,
                "bundleHash": review_model.approval_bundle_hash(bundle)})
            # تصمیمِ یکی از ردیف‌ها پس از امضا تغییر کند؛ امضا نباید معتبر بماند.
            changed = next(c for c in bundle["diff"]["changes"] if c.get("requiresHuman"))
            dirty = review.load_bundle("R-1405-cccc")
            dirty["decisions"][changed["id"]]["action"] = "reject"
            review.save_bundle(dirty)
            with self.assertRaises(ValueError):
                review.finalize("R-1405-cccc", by="reviewer-1",
                                signed_approval=year_entry)

    def test_needs_evidence_is_not_treated_as_resolved(self):
        with TempReview() as temp:
            session = session_for(temp)
            install_baseline()
            bundle = make_bundle("R-1405-cccc", [row(1405, 1, 10, "آزمون سراسری", 2),
                                                 row(1405, 2, 1, "رویداد دوم", 3),
                                                 row(1405, 3, 1, "رویداد سوم", 4)])
            change = next(c for c in bundle["diff"]["changes"] if c.get("requiresHuman"))
            review_panel.decide(session, {"revision": "R-1405-cccc", "change": change["id"],
                                          "action": "needs-evidence", "reason": "شاهد کافی نیست",
                                          "evidence": "صفحهٔ ۲ سطر ۴"})
            self.assertFalse(review_model.all_requires_human_resolved(
                review.load_bundle("R-1405-cccc")))
            with self.assertRaises(review_panel.PanelError):
                review_panel.year_approval(session, {"revision": "R-1405-cccc"})

    def test_date_edit_preserves_source_and_legal_period(self):
        with TempReview() as temp:
            session = session_for(temp)
            install_baseline()
            bundle = make_bundle("R-1405-cccc", [row(1405, 1, 10, "آزمون سراسری", 2),
                                                 row(1405, 2, 1, "رویداد دوم", 3),
                                                 row(1405, 3, 1, "عنوان خام", 4)])
            added = next(c for c in bundle["diff"]["changes"] if c["kind"] == "ADDED")
            review_panel.decide(session, {
                "revision": "R-1405-cccc", "change": added["id"], "action": "edit",
                "reason": "اصلاح از سند",
                "date": {"start": {"calendar": "lunar", "date": [1447, 10, 2]},
                         "end": {"calendar": "solar", "date": [1405, 1, 4]}},
                "title": "عنوان درست"})
            for change in review.load_bundle("R-1405-cccc")["diff"]["changes"]:
                if change.get("requiresHuman") and change["id"] != added["id"]:
                    review_panel.decide(session, {"revision": "R-1405-cccc",
                                                  "change": change["id"],
                                                  "action": "reject", "reason": "بیرون از دامنه"})
            result = review_panel.year_approval(session, {"revision": "R-1405-cccc"})
            self.assertTrue(result["ok"])
            active = store.active_revisions(store.load_history()["revisions"])[1405]
            rows = store.load_revision_rows(active)
            edited = next(r for r in rows if r.get("title") == "عنوان درست")
            self.assertEqual(edited["startSolar"], [1405, 1, 1])
            self.assertEqual(edited["endSolar"], [1405, 1, 4])
            self.assertTrue(edited["multiDay"])
            self.assertEqual(edited["sourceDate"], [1405, 3, 1])
            self.assertEqual(edited["dateConversion"]["algorithm"], review_model.ALGORITHM)
            self.assertEqual(edited["dateConversion"]["version"], review_model.ALGORITHM_VERSION)
            self.assertEqual(edited["conversionAlgorithm"], review_model.ALGORITHM)
            self.assertEqual(edited["conversionVersion"], review_model.ALGORITHM_VERSION)
            decision = review.load_bundle("R-1405-cccc")["decisions"][added["id"]]
            self.assertEqual(decision["auditSeq"], 1)

    def test_duplicate_decision_is_refused_without_a_second_audit_record(self):
        with TempReview() as temp:
            session = session_for(temp)
            install_baseline()
            bundle = make_bundle("R-1405-cccc", [row(1405, 1, 10, "آزمون سراسری", 2),
                                                 row(1405, 2, 1, "رویداد دوم", 3),
                                                 row(1405, 3, 1, "رویداد سوم", 4)])
            change = next(c for c in bundle["diff"]["changes"] if c.get("requiresHuman"))
            body = {"revision": "R-1405-cccc", "change": change["id"], "action": "approve"}
            review_panel.decide(session, body)
            with self.assertRaises(review_panel.PanelError):
                review_panel.decide(session, body)
            saved = review.load_bundle("R-1405-cccc")
            self.assertEqual(list(saved["decisions"]), [change["id"]])
            actions = [e["action"] for e in review_audit.load_entries()]
            self.assertEqual(actions.count("decision"), 1)

    def test_failed_decision_storage_leaves_no_decision_and_records_abort(self):
        with TempReview() as temp:
            session = session_for(temp)
            install_baseline()
            bundle = make_bundle("R-1405-cccc", [row(1405, 1, 10, "آزمون سراسری", 2),
                                                 row(1405, 2, 1, "رویداد دوم", 3),
                                                 row(1405, 3, 1, "رویداد سوم", 4)])
            change = next(c for c in bundle["diff"]["changes"] if c.get("requiresHuman"))
            with mock.patch.object(review, "decide", side_effect=ValueError("disk full")):
                with self.assertRaises(review_panel.PanelError):
                    review_panel.decide(session, {"revision": "R-1405-cccc",
                                                   "change": change["id"],
                                                   "action": "approve"})
            self.assertNotIn(change["id"], review.load_bundle("R-1405-cccc")["decisions"])
            actions = [e["action"] for e in review_audit.load_entries()]
            self.assertEqual(actions, ["decision", "abort"])
            self.assertEqual(review_audit.verify_file(temp.audit_file, temp.reviewers_file), [])

    def test_storage_failure_during_finalize_rolls_back_history(self):
        with TempReview() as temp:
            session = session_for(temp)
            self._complete(temp, session)
            before = store.load_history()
            before_bundle = review.load_bundle("R-1405-cccc")
            with mock.patch.object(store, "save_changelog",
                                   side_effect=ValueError("disk full")):
                with self.assertRaises(review_panel.PanelError):
                    review_panel.year_approval(session, {"revision": "R-1405-cccc"})
            after = store.load_history()
            self.assertEqual([r["id"] for r in after["revisions"]],
                             [r["id"] for r in before["revisions"]])
            self.assertEqual(after["changelog"], before["changelog"])
            self.assertEqual(after["events"], before["events"])
            self.assertEqual(after["occurrences"], before["occurrences"])
            self.assertEqual(review.load_bundle("R-1405-cccc")["state"],
                             before_bundle["state"])
            self.assertNotIn("year-approval",
                             [e["action"] for e in review_audit.load_entries()])

    def test_failed_year_approval_is_not_written_to_the_audit(self):
        with TempReview() as temp:
            session = session_for(temp)
            self._complete(temp, session)
            with mock.patch.object(review, "finalize", side_effect=ValueError("write failed")):
                with self.assertRaises(review_panel.PanelError):
                    review_panel.year_approval(session, {"revision": "R-1405-cccc"})
            actions = [e["action"] for e in review_audit.load_entries()]
            self.assertNotIn("year-approval", actions)
            self.assertIn("abort", actions)
            self.assertEqual(review.load_bundle("R-1405-cccc")["state"], "in-review")

    def test_year_approval_cannot_be_repeated(self):
        with TempReview() as temp:
            session = session_for(temp)
            self._complete(temp, session)
            review_panel.year_approval(session, {"revision": "R-1405-cccc"})
            with self.assertRaises(review_panel.PanelError):
                review_panel.year_approval(session, {"revision": "R-1405-cccc"})
            self.assertEqual(sum(1 for e in review_audit.load_entries()
                                 if e["action"] == "year-approval"), 1)

    def test_concurrent_reviewers_cannot_decide_the_same_item_twice(self):
        with TempReview() as temp:
            first = session_for(temp, "reviewer-a")
            second = session_for(temp, "reviewer-b")
            install_baseline()
            bundle = make_bundle("R-1405-cccc", [row(1405, 1, 10, "آزمون سراسری", 2),
                                                 row(1405, 2, 1, "رویداد دوم", 3),
                                                 row(1405, 3, 1, "رویداد سوم", 4)])
            change = next(c for c in bundle["diff"]["changes"] if c.get("requiresHuman"))
            barrier = threading.Barrier(2)

            def act(session):
                barrier.wait(timeout=5)
                try:
                    review_panel.decide(session, {"revision": "R-1405-cccc",
                                                   "change": change["id"],
                                                   "action": "approve"})
                    return "ok"
                except review_panel.PanelError:
                    return "rejected"

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = sorted(pool.map(act, [first, second]))
            self.assertEqual(results, ["ok", "rejected"])
            self.assertEqual(len(review.load_bundle("R-1405-cccc")["decisions"]), 1)
            self.assertEqual(sum(1 for e in review_audit.load_entries()
                                 if e["action"] == "decision"), 1)
            self.assertEqual(review_audit.verify_file(temp.audit_file, temp.reviewers_file), [])

    def test_audit_prepare_cannot_land_on_a_changed_chain(self):
        with TempReview() as temp:
            session = session_for(temp)
            prepared = review_audit.prepare(session, "year-approval",
                                            {"revisionId": "R", "year": 1405})
            review_audit.append(session, "decision", {"revisionId": "R", "action": "approve"})
            with self.assertRaises(ValueError):
                review_audit.commit(prepared, session)
            self.assertEqual(len(review_audit.load_entries()), 1)

    def test_origin_token_and_expired_session_are_rejected(self):
        handler = object.__new__(review_server.Handler)
        handler.headers = {"Origin": "https://evil.example"}
        self.assertFalse(handler._origin_ok())
        handler.headers = {"Origin": "http://localhost:8765"}
        self.assertTrue(handler._origin_ok())
        handler.headers = {"X-Review-Token": "wrong"}
        self.assertFalse(handler._token_ok())
        handler.headers = {"X-Review-Token": review_server.TOKEN}
        self.assertTrue(handler._token_ok())
        handler.headers = {"Cookie": f"review_csrf={review_server.TOKEN}"}
        self.assertTrue(handler._token_ok())
        token = "expired-test-token"
        review_server.SESSIONS[token] = {"expires": time.time() - 1}
        handler.headers = {"X-Review-Session": token}
        self.assertIsNone(handler._session())
        self.assertNotIn(token, review_server.SESSIONS)

    def test_http_login_sets_csrf_cookie_that_can_load_a_pdf(self):
        with TempReview() as temp:
            install_baseline()
            session = session_for(temp)
            pdf = ROOT / "PDF" / "Calendar-1405.pdf"
            if not pdf.exists():
                self.skipTest("PDF نمونه در دسترس نیست")
            rid = "R-1405-http"
            rev = revision(rid, 1405, store.sha256_file(pdf))
            rev["document"]["pages"] = 17
            rev["document"]["storedPath"] = "PDF/Calendar-1405.pdf"
            review.save_bundle({"revision": rev, "rawRows": [], "oldRevisionId": None,
                                "diff": {"changes": [], "counts": {}, "duplicates": []},
                                "decisions": {}, "state": "pending", "createdAt": store.now_iso()})
            review_server.SESSIONS.clear()
            server = ThreadingHTTPServer(("127.0.0.1", 0), review_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                body = json.dumps({"reviewer": session["reviewerId"],
                                   "password": "correct horse battery"})
                conn.request("POST", "/api/login", body,
                             {"X-Review-Token": review_server.TOKEN,
                              "Content-Type": "application/json"})
                response = conn.getresponse()
                self.assertEqual(response.status, 200, response.read().decode("utf-8"))
                response.read()
                cookies = [v for k, v in response.getheaders()
                           if k.lower() == "set-cookie"]
                self.assertTrue(any(c.startswith("review_csrf=") for c in cookies))
                cookie_header = "; ".join(c.split(";", 1)[0] for c in cookies)
                conn.request("GET", f"/api/pdf?revision={rid}&page=1",
                             headers={"Cookie": cookie_header})
                pdf_response = conn.getresponse()
                data = pdf_response.read()
                self.assertEqual(pdf_response.status, 200)
                self.assertTrue(data.startswith(b"%PDF-"))
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                review_server.SESSIONS.clear()

    def test_private_keys_and_local_roster_are_gitignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".review-keys/", ignored)
        self.assertIn("data/review/reviewers.json", ignored)


if __name__ == "__main__":
    unittest.main()
