#!/usr/bin/env python3
"""سرویسِ پنلِ بازبینی: صف، تصمیمِ امضاشده و تأییدِ سال.

سرور فقط لایهٔ HTTP است؛ منطقِ تصمیم/اعمال در ``review_changes`` می‌ماند و این
ماژول هویتِ نشست را به آن وصل می‌کند. تصمیمِ ردیفی و تأییدِ سال دو رکوردِ جداگانه
در دفترِ امضاشده دارند.
"""
from __future__ import annotations

import functools
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import review_audit  # noqa: E402
import review_changes as review  # noqa: E402
import review_model  # noqa: E402
import reviewer_auth  # noqa: E402


class PanelError(ValueError):
    """خطای قابلِ نمایش به کاربر؛ هیچ داده‌ای نباید نیمه‌کاره اعمال شود."""


_MUTATION_LOCK = threading.RLock()


def _serialized(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _MUTATION_LOCK:
            return fn(*args, **kwargs)
    return wrapper


def _actor(session: dict) -> str:
    if not session or not session.get("reviewerId"):
        raise PanelError("نشستِ بازبین معتبر نیست")
    return session["reviewerId"]


def _clean_text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _bundle_from_request(rev_id: str) -> dict:
    if not rev_id:
        raise PanelError("شناسهٔ پیش‌نویس لازم است")
    try:
        return review.load_bundle(rev_id)
    except FileNotFoundError as exc:
        raise PanelError(str(exc)) from exc


def summary_changed(bundle: dict) -> int:
    return len([c for c in (bundle.get("diff") or {}).get("changes", [])
                if c.get("kind") != "UNCHANGED"])


def queue_state() -> dict:
    bundles = review.pending_bundles()
    items = review_model.queue_items(bundles)
    summaries = []
    for bundle in bundles:
        rev = bundle["revision"]
        changes = [c for c in bundle["diff"]["changes"] if c.get("requiresHuman", True)]
        resolved = [c for c in changes
                    if (bundle["decisions"].get(c["id"]) or {}).get("action")
                    in {"approve", "reject"}]
        summary = {
            "revisionId": rev["id"],
            "year": rev["year"],
            "file": rev.get("document", {}).get("file"),
            "state": bundle.get("state"),
            "pages": rev.get("document", {}).get("pages"),
            "rowCount": rev.get("extraction", {}).get("rowCount"),
            "changed": summary_changed(bundle),
            "required": len(changes),
            "resolved": len(resolved),
            "locked": rev["year"] in review_model.LOCKED_YEARS,
            "canFinalize": (review_model.all_requires_human_resolved(bundle)
                            and rev["year"] not in review_model.LOCKED_YEARS
                            and summary_changed(bundle) > 0),
        }
        summary["items"] = [i for i in items if i["revisionId"] == rev["id"]]
        summary["counts"] = review_model.status_counts(summary["items"])
        summaries.append(summary)
    return {
        "generatedAt": review.store.now_iso(),
        "statuses": review_model.STATUS_LABELS,
        "bundles": summaries,
        "counts": review_model.status_counts(items),
        "items": items,
    }


def reviewers() -> list[dict]:
    return reviewer_auth.public_reviewers()


@_serialized
def decide(session: dict, body: dict) -> dict:
    reviewer = _actor(session)
    rev_id = _clean_text(body.get("revision"), 100)
    change_id = _clean_text(body.get("change"), 100)
    action = _clean_text(body.get("action"), 20)
    if action not in {"approve", "reject", "edit", "needs-evidence"}:
        raise PanelError("تصمیمِ نامعتبر است")
    bundle = _bundle_from_request(rev_id)
    change = review.find_change(bundle, change_id)
    if change is None:
        raise PanelError("این تغییر در پیش‌نویس نیست")
    if change_id in (bundle.get("decisions") or {}):
        raise PanelError("برای این تغییر قبلاً تصمیم ثبت شده است؛ تصمیمِ قبلی بازنویسی نمی‌شود")
    reason = _clean_text(body.get("reason") or body.get("note"), 2000)
    evidence = _clean_text(body.get("evidence"), 4000)
    if action in {"reject", "needs-evidence", "edit"} and not reason:
        raise PanelError("رد، اصلاح یا درخواستِ شاهد، دلیلِ مکتوب لازم دارد")
    if action == "needs-evidence" and not evidence:
        raise PanelError("برای «نیازمند شاهد»، شاهد/نشانیِ شاهد را وارد کنید")
    delegated = _clean_text(body.get("delegatedTo"), 80)
    if delegated:
        known = {r["id"] for r in reviewers()}
        if delegated not in known:
            raise PanelError("بازبینِ واگذارشده در این نصب ثبت نشده است")
        if delegated == reviewer:
            raise PanelError("واگذاری به خودِ بازبین معنا ندارد")

    edit = None
    date_meta = None
    if action == "edit":
        edit = {}
        title = _clean_text(body.get("title"), 500)
        if title:
            edit["title"] = title
        if "holiday" in body and body["holiday"] is not None:
            edit["holiday"] = bool(body["holiday"])
        description = body.get("description")
        if description is not None:
            edit["description"] = _clean_text(description, 1000)
        period = body.get("date")
        if period:
            source_row = (change.get("before") or change.get("after") or {})
            fallback = source_row.get("sourceDate") or source_row.get("solar")
            if not fallback:
                raise PanelError("تاریخِ منبع برای اعتبارسنجی در دسترس نیست")
            year = int(bundle["revision"]["year"])
            try:
                date_meta = review_model.normalize_period(period, year, fallback)
            except ValueError as exc:
                raise PanelError(str(exc)) from exc
            edit["start"] = date_meta["startSolar"]
            edit["end"] = date_meta["endSolar"]
            edit["dateMeta"] = date_meta
        if not edit:
            raise PanelError("هیچ اصلاحی وارد نشده است")
    elif body.get("date") is not None:
        raise PanelError("تاریخ فقط همراه با اصلاح مجاز است")

    payload = {
        "revisionId": rev_id,
        "changeId": change_id,
        "itemId": review_model.event_review_id(bundle, change),
        "action": action,
        "reason": reason,
        "evidence": evidence,
        "delegatedTo": delegated or None,
        "edit": edit,
    }
    audit = review_audit.append(session, "decision", payload)
    meta = {
        "reason": reason,
        "evidence": evidence,
        "delegatedTo": delegated or None,
        "reviewerId": reviewer,
        "assurance": session.get("assurance"),
        "auditSeq": audit["seq"],
    }
    if date_meta:
        meta["dateMeta"] = date_meta
    try:
        updated = review.decide(rev_id, change_id, action, by=reviewer,
                                note=reason, edit=edit, meta=meta)
    except (ValueError, FileNotFoundError) as exc:
        _record_abort(session, "decision", rev_id, change_id, exc)
        raise PanelError(f"تصمیم ثبت نشد؛ رکوردِ ناموفق در دفتر علامت خورد: {exc}") from exc
    decision = updated["decisions"].get(change_id, {})
    return {"ok": True, "itemId": payload["itemId"], "auditSeq": audit["seq"],
            "status": review_model.status_for(updated, change)}


def _record_abort(session: dict, action: str, rev_id: str, change_id: str,
                  exc: Exception) -> None:
    try:
        review_audit.append(session, "abort", {
            "attemptedAction": action,
            "revisionId": rev_id,
            "changeId": change_id,
            "reason": str(exc)[:1000],
        })
    except Exception:  # noqa: BLE001 - خودِ دفتر خراب است؛ خطای اصلی را نگه دار
        pass


def approve_all_requires_single_decisions() -> None:
    """تأییدِ گروهیِ کور در پنل وجود ندارد؛ هر ردیف امضای خودش را دارد."""
    raise PanelError("تأییدِ گروهی در پنل غیرفعال است؛ هر ردیف را جداگانه تأیید کنید")


@_serialized
def year_approval(session: dict, body: dict) -> dict:
    reviewer = _actor(session)
    rev_id = _clean_text(body.get("revision"), 100)
    bundle = _bundle_from_request(rev_id)
    if bundle.get("state") in {"applied", "reverted"}:
        raise PanelError("این پیش‌نویس پیش‌تر اعمال شده است")
    year = bundle["revision"]["year"]
    if year in review_model.LOCKED_YEARS:
        raise PanelError(f"سالِ {year} قفل است؛ انتشار/فعال‌سازی ممنوع")
    if summary_changed(bundle) == 0:
        raise PanelError("این پیش‌نویس هیچ تغییرِ قابلِ اعمالی ندارد")
    if not review_model.all_requires_human_resolved(bundle):
        raise PanelError("همهٔ ردیف‌های نیازمندِ تصمیم باید approve یا reject شوند")
    bundle_hash = review_model.approval_bundle_hash(bundle)
    payload = {
        "revisionId": rev_id,
        "year": year,
        "bundleHash": bundle_hash,
        "decisionCount": len(bundle.get("decisions") or {}),
        "note": _clean_text(body.get("note"), 1000),
    }
    # ابتدا امضا ساخته می‌شود ولی هنوز در دفتر نمی‌نشیند؛ اگر finalize
    # شکست بخورد، هیچ year-approval نیمه‌کاره‌ای در تاریخچه نمی‌ماند.
    approval = review_audit.prepare(session, "year-approval", payload)
    try:
        result = review.finalize(rev_id, by=reviewer, note=payload["note"],
                                 signed_approval=approval)
    except (ValueError, FileNotFoundError) as exc:
        _record_abort(session, "year-approval", rev_id, "", exc)
        raise PanelError(f"تأییدِ سال اعمال نشد و در دفتر ثبت نشد: {exc}") from exc
    try:
        review_audit.commit(approval, session)
    except ValueError as exc:
        _record_abort(session, "year-approval-commit", rev_id, "", exc)
        raise PanelError(f"نسخه اعمال شد اما ثبتِ تأییدِ سال در دفتر ناموفق بود: {exc}") from exc
    review_audit.append(session, "finalize", {
        "revisionId": rev_id,
        "year": year,
        "approvedRevisionId": result["revision"]["id"],
        "changelogId": result["entry"]["id"],
        "yearApprovalSeq": approval["seq"],
        "rows": result["rows"],
    })
    return {"ok": True, "revision": result["revision"]["id"],
            "log": result["entry"]["id"], "yearApprovalSeq": approval["seq"]}


@_serialized
def reject_revision(session: dict, body: dict) -> dict:
    reviewer = _actor(session)
    rev_id = _clean_text(body.get("revision"), 100)
    reason = _clean_text(body.get("reason") or body.get("note"), 2000)
    if not reason:
        raise PanelError("ردِ کلِ پیش‌نویس دلیل لازم دارد")
    bundle = _bundle_from_request(rev_id)
    audit = review_audit.append(session, "decision", {
        "revisionId": rev_id, "action": "reject-revision", "reason": reason,
    })
    try:
        review.reject_revision(rev_id, by=reviewer, note=reason)
    except (ValueError, FileNotFoundError) as exc:
        _record_abort(session, "reject-revision", rev_id, "", exc)
        raise PanelError(f"ردِ پیش‌نویس اعمال نشد؛ رکوردِ ناموفق علامت خورد: {exc}") from exc
    return {"ok": True, "auditSeq": audit["seq"], "year": bundle["revision"]["year"]}


@_serialized
def revert(session: dict, body: dict) -> dict:
    reviewer = _actor(session)
    log_id = _clean_text(body.get("log"), 40)
    change_id = _clean_text(body.get("change"), 100)
    if bool(log_id) == bool(change_id):
        raise PanelError("یکی از log یا change لازم است")
    reason = _clean_text(body.get("reason") or body.get("note"), 2000)
    if not reason:
        raise PanelError("بازگردانی دلیل لازم دارد")
    target = {"logId": log_id} if log_id else {"changeId": change_id}
    audit = review_audit.append(session, "revert", {**target, "reason": reason})
    try:
        entry = (review.revert_log(log_id, by=reviewer, note=reason) if log_id
                 else review.revert_change(change_id, by=reviewer, note=reason))
    except (ValueError, FileNotFoundError) as exc:
        _record_abort(session, "revert", rev_id="", change_id=change_id, exc=exc)
        raise PanelError(f"بازگردانی اعمال نشد؛ رکوردِ ناموفق علامت خورد: {exc}") from exc
    return {"ok": True, "log": entry["id"], "revision": entry["revisionId"],
            "auditSeq": audit["seq"]}


def history() -> dict:
    entries = review_audit.load_entries()
    issues = review_audit.verify_file()
    return {
        "entries": entries,
        "integrity": {"ok": not issues, "issues": issues},
    }
