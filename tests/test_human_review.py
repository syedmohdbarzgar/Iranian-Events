"""آزمون‌های P0/P1 پنلِ بازبینیِ انسانی.

پوشه‌ها و کلیدها موقت‌اند. آزمون‌ها به دادهٔ واقعی یا حسابِ واقعی دست نمی‌زنند.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import calendar_engine as engine  # noqa: E402
import history_store as store  # noqa: E402
import review_audit  # noqa: E402
import review_changes as review  # noqa: E402
import review_model  # noqa: E402
import review_panel  # noqa: E402
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
        self.assertEqual(lunar["startSolar"], [1405, 1, 2])
        self.assertEqual(lunar["conversion"]["from"], "lunar")
        greg = review_model.normalize_period(
            {"start": {"calendar": "gregorian", "date": [2026, 3, 22]}},
            1405, [1405, 1, 1])
        self.assertEqual(greg["startSolar"], [1405, 1, 2])
        self.assertFalse(greg["multiDay"])

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
            self.assertEqual(edited["startSolar"], [1405, 1, 2])
            self.assertEqual(edited["endSolar"], [1405, 1, 4])
            self.assertTrue(edited["multiDay"])
            self.assertEqual(edited["sourceDate"], [1405, 3, 1])
            self.assertEqual(edited["dateConversion"]["algorithm"], review_model.ALGORITHM)
            self.assertEqual(edited["dateConversion"]["version"], review_model.ALGORITHM_VERSION)
            self.assertEqual(edited["conversionAlgorithm"], review_model.ALGORITHM)
            self.assertEqual(edited["conversionVersion"], review_model.ALGORITHM_VERSION)
            decision = review.load_bundle("R-1405-cccc")["decisions"][added["id"]]
            self.assertEqual(decision["auditSeq"], 1)


if __name__ == "__main__":
    unittest.main()
