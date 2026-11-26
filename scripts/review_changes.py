"""بازبینی، تأیید/رد، اصلاح و بازگردانیِ تغییراتِ نسخه‌ها (فاز ۴ چک‌لیست).

هیچ تغییر خودکاری اعمال نمی‌شود. جریان:

    ingest_pdf.py  →  پیش‌نویس در data/review/changes/<rev>.json
    review_changes.py decide …  →  تصمیمِ انسانی برای هر تغییر
    review_changes.py finalize …  →  ساختِ نسخهٔ تأییدشده + ChangeLog
    review_changes.py revert …   →  بازگردانیِ یک تأیید یا یک تغییر

هر ورودیِ ChangeLog عکسِ وضعیتِ پیش/پسِ همان سال را نگه می‌دارد؛ بنابراین
بازگردانی، داده را واقعاً به حالتِ پیشین برمی‌گرداند، نه فقط برچسب عوض کند.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402
import review_audit  # noqa: E402
import review_model  # noqa: E402
import reviewer_auth  # noqa: E402
import revision_diff  # noqa: E402

CHANGES_DIR = store.CHANGES_DIR
AGENT_PREFIXES = ("agent:", "proposal:", "ai:", "bot:", "codebuff:")


def _human_actor(value: str) -> str:
    actor = (value or "").strip()
    if not actor:
        raise ValueError("هویتِ بازبین لازم است")
    if actor.lower().startswith(AGENT_PREFIXES):
        raise ValueError("عامل/ربات نمی‌تواند تأییدِ انسانی ثبت کند")
    return actor


# ───────────────────────────── ابزارِ پیش‌نویس ─────────────────────────────

def bundle_path(rev_id: str) -> Path:
    return CHANGES_DIR / f"{rev_id}.json"


def load_bundle(rev_id: str) -> dict:
    path = bundle_path(rev_id)
    if not path.exists():
        raise FileNotFoundError(f"پیش‌نویسِ {rev_id} یافت نشد")
    return store.load_json(path, {})


def save_bundle(bundle: dict) -> None:
    store.write_json(bundle_path(bundle["revision"]["id"]), bundle)


def pending_bundles(year: int | None = None) -> list[dict]:
    out = []
    for path in sorted(CHANGES_DIR.glob("*.json")):
        bundle = store.load_json(path, {})
        if bundle.get("state") not in {"pending", "in-review"}:
            continue
        if year is not None and bundle["revision"]["year"] != year:
            continue
        out.append(bundle)
    return out


def find_change(bundle: dict, change_id: str) -> dict | None:
    for change in bundle["diff"]["changes"]:
        if change["id"] == change_id:
            return change
    return None


def _validate_edit(edit: dict, year: int) -> dict:
    out: dict = {}
    if "title" in edit and edit["title"] is not None:
        title = str(edit["title"]).strip()
        if len(title) < 3:
            raise ValueError("عنوانِ اصلاح‌شده کوتاه‌تر از حدِ مجاز است")
        out["title"] = title
    if "solar" in edit and edit["solar"] is not None:
        try:
            y, m, d = (int(x) for x in edit["solar"])
        except Exception as exc:  # noqa: BLE001
            raise ValueError("تاریخِ شمسی باید [سال، ماه، روز] باشد") from exc
        if y != year or not 1 <= m <= 12 or not 1 <= d <= 31:
            raise ValueError(f"تاریخِ نامعتبر: {y}-{m}-{d}")
        import calendar_engine as engine
        if d > engine.month_len(y, m):
            raise ValueError(f"روزِ {d} در ماهِ {m} سالِ {y} وجود ندارد")
        out["solar"] = [y, m, d]
    if "holiday" in edit:
        out["holiday"] = bool(edit["holiday"])
    if "description" in edit and edit["description"] is not None:
        out["description"] = str(edit["description"])[:1000]
    if "note" in edit:
        out["note"] = str(edit["note"])[:500]
    for key in ("start", "end"):
        if key in edit and edit[key] is not None:
            out[key] = review_model.validate_solar(year, edit[key])
    if "dateMeta" in edit and edit["dateMeta"] is not None:
        meta = edit["dateMeta"]
        if not isinstance(meta, dict):
            raise ValueError("dateMeta باید شیء باشد")
        out["dateMeta"] = {
            "source": meta.get("source"),
            "conversion": meta.get("conversion"),
            "startSolar": meta.get("startSolar"),
            "endSolar": meta.get("endSolar"),
            "multiDay": bool(meta.get("multiDay")),
        }
    if "start" in out and "end" in out and tuple(out["end"]) < tuple(out["start"]):
        raise ValueError("پایانِ بازه پیش از شروع است")
    return out


def decide(rev_id: str, change_id: str, action: str, *, by: str, note: str = "",
           edit: dict | None = None, meta: dict | None = None) -> dict:
    if action not in {"approve", "reject", "edit", "needs-evidence"}:
        raise ValueError("action باید approve/reject/edit/needs-evidence باشد")
    by = _human_actor(by)
    bundle = load_bundle(rev_id)
    if bundle.get("state") in {"applied", "reverted"}:
        raise ValueError(f"این پیش‌نویس پیش‌تر اعمال شده است ({bundle['state']})")
    change = find_change(bundle, change_id)
    if change is None:
        raise ValueError(f"تغییرِ {change_id} در این پیش‌نویس نیست")
    if change_id in bundle.get("decisions", {}):
        raise ValueError("برای این تغییر قبلاً تصمیم امضاشده ثبت شده است؛ "
                         "تصمیمِ قبلی قابلِ بازنویسی نیست")
    payload = {"action": action, "by": by, "at": store.now_iso(), "note": note.strip()}
    if action == "edit":
        if not edit:
            raise ValueError("برای edit، --title/--solar/--holiday لازم است")
        payload["edit"] = _validate_edit(edit, bundle["revision"]["year"])
        payload["action"] = "approve"
        payload["edited"] = True
    elif edit:
        raise ValueError("edit فقط با action=edit مجاز است")
    if meta:
        for key in ("reason", "evidence", "delegatedTo", "dateMeta", "reviewerId",
                    "assurance", "auditSeq"):
            if key in meta and meta[key] is not None:
                payload[key] = meta[key]
    bundle["decisions"][change_id] = payload
    bundle["state"] = "in-review"
    save_bundle(bundle)
    return bundle


def approve_all(rev_id: str, *, by: str, note: str = "", include_unchanged: bool = True) -> dict:
    by = _human_actor(by)
    bundle = load_bundle(rev_id)
    if bundle.get("state") in {"applied", "reverted"}:
        raise ValueError("این پیش‌نویس پیش‌تر اعمال شده است")
    for change in bundle["diff"]["changes"]:
        if change["kind"] == "UNCHANGED" and not include_unchanged:
            continue
        bundle["decisions"].setdefault(change["id"], {
            "action": "approve", "by": by.strip(), "at": store.now_iso(),
            "note": note.strip() or "تأییدِ گروهی",
        })
    bundle["state"] = "in-review"
    save_bundle(bundle)
    return bundle


def _row_key(row: dict) -> tuple:
    return (row.get("title"), tuple(row.get("solar") or []), row.get("page"))


def _apply_edit(row: dict | None, edit: dict | None) -> dict | None:
    if row is None or not edit:
        return row
    out = copy.deepcopy(row)
    import calendar_engine as engine
    if "sourceDate" not in out:
        out["sourceDate"] = copy.deepcopy(out.get("solar"))
        out["sourceLunar"] = copy.deepcopy(out.get("lunar"))
        out["sourceGregorian"] = copy.deepcopy(out.get("gregorian"))
        out["sourceTitle"] = out.get("titleRaw") or out.get("title")
    if "title" in edit:
        out["title"] = edit["title"]
    if "solar" in edit:
        y, m, d = edit["solar"]
        out["solar"] = [y, m, d]
        out["gregorian"] = list(engine.jalali_to_gregorian(y, m, d))
        out["lunar"] = [None, None, None]
        out["derived"] = sorted(set(list(out.get("derived") or []) + ["gregorian", "lunar"]))
        out["edited"] = True
    if "start" in edit:
        out["startSolar"] = list(edit["start"])
        out["endSolar"] = list(edit.get("end") or edit["start"])
        out["multiDay"] = out["startSolar"] != out["endSolar"]
        out["solar"] = list(out["startSolar"])
        out["gregorian"] = list(engine.jalali_to_gregorian(*out["startSolar"]))
        out["lunar"] = [None, None, None]
        out["derived"] = sorted(set(list(out.get("derived") or []) + ["gregorian", "lunar"]))
        out["edited"] = True
    if edit.get("dateMeta"):
        conversion = copy.deepcopy(edit["dateMeta"].get("conversion")) or {}
        out["dateConversion"] = conversion
        out["dateSource"] = copy.deepcopy(edit["dateMeta"].get("source"))
        out["conversionAlgorithm"] = conversion.get("algorithm")
        out["conversionVersion"] = conversion.get("version")
    if "holiday" in edit:
        out["holiday"] = bool(edit["holiday"])
        out["edited"] = True
    if "description" in edit:
        out["description"] = edit["description"]
        out["edited"] = True
    if edit.get("note"):
        out["reviewNote"] = edit["note"]
    return out


def resolve_rows(old_rows: list[dict], diff: dict, decisions: dict) -> list[dict]:
    """ردیف‌های سال را از نسخهٔ پیشین + تصمیم‌های انسانی می‌سازد."""
    result = [copy.deepcopy(r) for r in old_rows]
    index = {_row_key(r): i for i, r in enumerate(result)}
    for change in diff["changes"]:
        decision = decisions.get(change["id"]) or {}
        if change["kind"] == "UNCHANGED":
            continue
        if decision.get("action") != "approve":
            continue
        after = _apply_edit(change.get("after"), decision.get("edit"))
        before = change.get("before")
        if change["kind"] == "ADDED":
            if after and _row_key(after) not in index:
                index[_row_key(after)] = len(result)
                result.append(after)
        elif change["kind"] == "REMOVED":
            if before and _row_key(before) in index:
                idx = index.pop(_row_key(before))
                result[idx] = None
        else:
            if before and _row_key(before) in index:
                idx = index.pop(_row_key(before))
                result[idx] = after
                if after:
                    index[_row_key(after)] = idx
    cleaned = [r for r in result if r is not None]
    cleaned.sort(key=lambda r: ((r.get("solar") or [0, 0, 0])[1] or 0,
                                (r.get("solar") or [0, 0, 0])[2] or 0,
                                r.get("title", "")))
    return cleaned


def _validate_rows(rows: list[dict], year: int) -> None:
    import calendar_engine as engine
    for row in rows:
        solar = row.get("solar") or [None, None, None]
        if solar[0] != year or len(solar) != 3 or None in solar[1:]:
            raise ValueError(f"ردیفِ سالِ نادرست: {solar} — {row.get('title', '')[:50]}")
        if not 1 <= solar[1] <= 12 or not 1 <= solar[2] <= engine.month_len(year, solar[1]):
            raise ValueError(f"تاریخِ نامعتبر: {solar}")
        for key in ("startSolar", "endSolar"):
            if row.get(key) is not None:
                value = row[key]
                if (not isinstance(value, list) or len(value) != 3 or value[0] != year
                        or not 1 <= value[1] <= 12
                        or not 1 <= value[2] <= engine.month_len(year, value[1])):
                    raise ValueError(f"{key} نامعتبر: {value}")
        if row.get("startSolar") and row.get("endSolar"):
            if tuple(row["endSolar"]) < tuple(row["startSolar"]):
                raise ValueError("پایانِ بازه پیش از شروع است")
            if bool(row.get("multiDay")) != (row["startSolar"] != row["endSolar"]):
                raise ValueError("نشانهٔ چندروزه با بازه نمی‌خواند")
        if not store.row_is_event(row.get("title", "")):
            raise ValueError(f"عنوانِ نامعتبر: {row.get('title', '')!r}")


# ───────────────────────────── تأیید و اعمال ─────────────────────────────

def _snapshot_files(paths: list[Path]) -> dict[Path, tuple[bool, bytes | None]]:
    return {p: (p.exists(), p.read_bytes() if p.exists() else None) for p in paths}


def _restore_files(snapshot: dict[Path, tuple[bool, bytes | None]]) -> None:
    """بازگرداندنِ فایل‌های یک finalizeِ نیمه‌کاره پس از خطای ذخیره‌سازی."""
    for path, (existed, data) in snapshot.items():
        try:
            if existed and data is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            elif path.exists():
                path.unlink()
        except OSError:
            pass


def finalize(rev_id: str, *, by: str, note: str = "",
             signed_approval: dict | None = None) -> dict:
    by = _human_actor(by)
    bundle = load_bundle(rev_id)
    revision = bundle["revision"]
    if bundle.get("state") in {"applied", "reverted"}:
        raise ValueError("این پیش‌نویس پیش‌تر اعمال شده است")
    unresolved = [c["id"] for c in bundle["diff"]["changes"]
                  if c.get("requiresHuman", True)
                  and (bundle["decisions"].get(c["id"]) or {}).get("action")
                  not in {"approve", "reject"}]
    if unresolved:
        raise ValueError("تصمیمِ انسانی برای این تغییرها ثبت نشده: " + ", ".join(unresolved[:8]))
    signed_by = None
    if signed_approval is not None:
        trusted = {r["keyId"]: r["publicKey"] for r in reviewer_auth.load_reviewers()
                   if r.get("active", True)}
        issues = review_audit.verify_entry(signed_approval, trusted)
        if issues:
            raise ValueError("تأییدِ سال امضای معتبر ندارد: " + issues[0]["code"])
        payload = signed_approval.get("payload") or {}
        if signed_approval.get("action") != "year-approval":
            raise ValueError("رکوردِ امضاشده تأییدِ سال نیست")
        if payload.get("revisionId") != rev_id or payload.get("year") != revision["year"]:
            raise ValueError("تأییدِ امضاشده به این پیش‌نویس/سال تعلق ندارد")
        if payload.get("bundleHash") != review_model.approval_bundle_hash(bundle):
            raise ValueError("تصمیم‌ها پس از تأییدِ سال تغییر کرده‌اند؛ تأیید را تکرار کنید")
        signed_by = signed_approval.get("actor") or {}
        if signed_by.get("reviewerId") != by:
            raise ValueError("تأییدکنندهٔ سال با امضاکننده یکی نیست")
    year = revision["year"]
    if year in review_model.LOCKED_YEARS:
        raise ValueError(f"سالِ {year} قفل است؛ بستهٔ بازبینیِ آن نباید فعال/منتشر شود")
    history = store.load_history()
    current = store.active_revisions(history["revisions"]).get(year)
    if bundle.get("oldRevisionId") != (current["id"] if current else None):
        raise ValueError("نسخهٔ فعالِ این سال از زمانِ ساختِ پیش‌نویس عوض شده؛ "
                         "دوباره ingest کنید و تغییرات را روی نسخهٔ تازه بسنجید")
    old_rows = store.load_revision_rows(current) if current else []
    rows = resolve_rows(old_rows, bundle["diff"], bundle["decisions"])
    _validate_rows(rows, year)

    approved = copy.deepcopy(revision)
    if current and approved["id"] == current["id"]:
        # همان PDFِ مبنا دوباره استخراج شده؛ نباید نسخهٔ مبنا را بازنویسی کند.
        n = 1 + sum(1 for r in history["revisions"]
                    if r["id"].startswith(f"{current['id']}-review-"))
        approved["id"] = f"{current['id']}-review-{n:02d}"
        approved["extraction"]["reviewedFrom"] = current["id"]
    approved["state"] = "approved"
    approved["approvedBy"] = by
    approved["approvedAt"] = store.now_iso()
    approved["approval"] = {
        "kind": "human",
        "method": "ed25519-review" if signed_approval else "review",
        "by": by,
        "at": approved["approvedAt"],
        "note": note.strip() or "تأییدِ انسانیِ تغییرات",
    }
    if signed_approval:
        approved["approval"].update({
            "reviewerId": signed_by.get("reviewerId"),
            "keyId": signed_by.get("keyId"),
            "publicKey": signed_approval.get("publicKey"),
            "signature": signed_approval.get("signature"),
            "auditSeq": signed_approval.get("seq"),
            "auditRecordHash": signed_approval.get("recordHash"),
            "bundleHash": (signed_approval.get("payload") or {}).get("bundleHash"),
            "assurance": "local-key-signature",
        })
    approved["note"] = note.strip() or "تأییدِ انسانیِ تغییرات"
    approved["supersedes"] = current["id"] if current else None
    approved["review"] = {
        "changes": len(bundle["diff"]["changes"]),
        "approved": sum(1 for d in bundle["decisions"].values() if d.get("action") == "approve"),
        "rejected": sum(1 for d in bundle["decisions"].values() if d.get("action") == "reject"),
        "edited": sum(1 for d in bundle["decisions"].values() if d.get("edited")),
        "decisions": bundle["decisions"],
    }
    approved["extraction"]["reviewedRowCount"] = len(rows)
    if current:
        current["state"] = "superseded"
        current["supersededBy"] = approved["id"]

    revisions = [r for r in history["revisions"] if r["id"] != approved["id"]] + [approved]
    # چند فایل پشتِ سرِ هم نوشته می‌شوند؛ اگر یکی شکست بخورد، وضعیتِ پیش از
    # تلاش برمی‌گردد و هیچ نسخه/تاریخچهٔ نیمه‌کاره نمی‌ماند. قطعِ برق در
    # میانهٔ همین چند میلی‌ثانیه همچنان با بازگردانیِ پشتیبان درمان می‌شود.
    snapshot = _snapshot_files([
        store.REVISIONS_FILE, store.CHANGELOG_FILE, store.EVENTS_FILE,
        store.OCCURRENCES_FILE, store.IDENTITY_REVIEWS_FILE,
        bundle_path(rev_id), store.REVISION_DIR / f"{approved['id']}.json",
    ])
    try:
        store.save_revisions(revisions)
        store.save_revision_rows(approved["id"], year, rows, source=approved["document"])
        bundle["state"] = "applied"
        bundle["appliedAt"] = approved["approvedAt"]
        save_bundle(bundle)

        entry = {
            "id": f"L-{len(history['changelog']) + 1:05d}",
            "at": approved["approvedAt"],
            "action": "APPROVE",
            "actor": by,
            "year": year,
            "revisionId": approved["id"],
            "bundleId": rev_id,
            "supersedes": current["id"] if current else None,
            "changeIds": [c["id"] for c in bundle["diff"]["changes"]],
            "decisions": {k: v.get("action") for k, v in bundle["decisions"].items()},
            "note": note.strip(),
            "snapshotBefore": old_rows,
            "snapshotAfter": rows,
        }
        history["changelog"].append(entry)
        store.save_changelog(history["changelog"])
        rebuild_canonical()
    except Exception:
        _restore_files(snapshot)
        raise
    return {"entry": entry, "revision": approved, "rows": len(rows)}


def reject_revision(rev_id: str, *, by: str, note: str = "") -> dict:
    by = _human_actor(by)
    bundle = load_bundle(rev_id)
    bundle["state"] = "rejected"
    bundle["rejectedBy"] = by
    bundle["rejectedAt"] = store.now_iso()
    bundle["rejectionNote"] = note.strip()
    save_bundle(bundle)
    return bundle


def rebuild_canonical() -> tuple[int, int]:
    events, occurrences = store.rebuild_from_revisions()
    store.save_history(events, occurrences)
    return len(events), len(occurrences)


# ───────────────────────────── بازگردانی ─────────────────────────────

def _append_revert(year: int, rows: list[dict], previous_rows: list[dict], *,
                   by: str, note: str, restores: str, source_rev: dict | None,
                   change_id: str | None = None) -> dict:
    history = store.load_history()
    current = store.active_revisions(history["revisions"]).get(year)
    if current is None:
        raise ValueError(f"نسخهٔ فعالی برای سالِ {year} نیست")
    n = 1 + sum(1 for r in history["revisions"] if r["id"].startswith(f"R-{year}-revert-"))
    rid = f"R-{year}-revert-{n:02d}"
    rev = {
        "id": rid,
        "year": year,
        "document": copy.deepcopy(current["document"]),
        "extraction": {
            "method": "manual-revert",
            "tool": "review_changes.py",
            "extractedAt": store.now_iso(),
            "rowCount": len(rows),
            "rawRowCount": len(rows),
            "sourceKind": "revert",
            "ocrPages": [],
            "qcProblems": 0,
        },
        "state": "approved",
        "approvedBy": by.strip(),
        "approvedAt": store.now_iso(),
        "approval": {
            "kind": "human",
            "method": "revert",
            "by": by.strip(),
            "at": store.now_iso(),
            "note": note.strip() or "بازگردانی",
        },
        "note": note.strip() or "بازگردانی",
        "supersedes": current["id"],
        "supersededBy": None,
        "restores": restores,
        "restoresChange": change_id,
    }
    current["state"] = "superseded"
    current["supersededBy"] = rid
    revisions = [r for r in history["revisions"] if r["id"] != rid] + [rev]
    store.save_revisions(revisions)
    store.save_revision_rows(rid, year, rows, source=rev["document"])
    entry = {
        "id": f"L-{len(history['changelog']) + 1:05d}",
        "at": rev["approvedAt"],
        "action": "REVERT",
        "actor": by.strip(),
        "year": year,
        "revisionId": rid,
        "supersedes": current["id"],
        "restoresLogId": restores,
        "restoresChange": change_id,
        "changeIds": [change_id] if change_id else [],
        "decisions": {},
        "note": note.strip(),
        "snapshotBefore": previous_rows,
        "snapshotAfter": rows,
    }
    history["changelog"].append(entry)
    store.save_changelog(history["changelog"])
    rebuild_canonical()
    return entry


def revert_log(log_id: str, *, by: str, note: str = "") -> dict:
    by = _human_actor(by)
    history = store.load_history()
    entry = next((e for e in history["changelog"] if e["id"] == log_id), None)
    if entry is None:
        raise ValueError(f"ورودیِ {log_id} در ChangeLog نیست")
    if entry["action"] != "APPROVE":
        raise ValueError("فقط تأییدها با --log بازگردانی می‌شوند")
    year = entry["year"]
    current = store.active_revisions(history["revisions"]).get(year)
    previous_rows = store.load_revision_rows(current) if current else []
    return _append_revert(year, copy.deepcopy(entry["snapshotBefore"]), previous_rows,
                          by=by, note=note or f"بازگردانیِ {log_id}", restores=log_id,
                          source_rev=current)


def revert_change(change_id: str, *, by: str, note: str = "") -> dict:
    by = _human_actor(by)
    history = store.load_history()
    log = next((e for e in reversed(history["changelog"])
                if e["action"] == "APPROVE" and change_id in e.get("changeIds", [])), None)
    if log is None:
        raise ValueError(f"تغییری با شناسهٔ {change_id} در تاریخچهٔ تأییدها نیست")
    bundle_id = log.get("bundleId") or log["revisionId"]
    bundle = load_bundle(bundle_id) if bundle_path(bundle_id).exists() else None
    change = find_change(bundle, change_id) if bundle else None
    if change is None:
        raise ValueError("جزئیاتِ تغییر در پیش‌نویسِ بایگانی‌شده نیست")
    year = log["year"]
    current = store.active_revisions(history["revisions"]).get(year)
    rows = store.load_revision_rows(current) if current else []
    before, after = change.get("before"), change.get("after")
    result = [copy.deepcopy(r) for r in rows]
    if change["kind"] == "ADDED":
        result = [r for r in result if _row_key(r) != _row_key(after)]
    elif change["kind"] == "REMOVED":
        if before and all(_row_key(r) != _row_key(before) for r in result):
            result.append(copy.deepcopy(before))
    else:
        replaced = False
        for i, row in enumerate(result):
            if _row_key(row) == _row_key(after):
                result[i] = copy.deepcopy(before)
                replaced = True
                break
        if not replaced and before:
            result.append(copy.deepcopy(before))
    result.sort(key=lambda r: ((r.get("solar") or [0, 0, 0])[1] or 0,
                               (r.get("solar") or [0, 0, 0])[2] or 0, r.get("title", "")))
    return _append_revert(year, result, rows, by=by,
                          note=note or f"بازگردانیِ تغییرِ {change_id}",
                          restores=log["id"], source_rev=current, change_id=change_id)


# ───────────────────────────── CLI ─────────────────────────────

def _print_bundle(bundle: dict, full: bool = False) -> None:
    rev = bundle["revision"]
    print(f"\n{rev['id']} — سال {rev['year']} — {rev['document']['file']} — "
          f"وضعیت {bundle['state']}")
    print(f"سند: {rev['document']['sha256'][:16]}… · {rev['extraction']['rowCount']} ردیف · "
          f"روش {rev['extraction']['method']}")
    counts = bundle["diff"]["counts"]
    print("شمارش:", " · ".join(f"{k}={v}" for k, v in counts.items() if v))
    if bundle["diff"]["duplicates"]:
        print(f"تکراری‌ها: {len(bundle['diff']['duplicates'])} گروه")
    for change in bundle["diff"]["changes"]:
        if not full and change["kind"] == "UNCHANGED":
            continue
        before = (change.get("before") or {}).get("title", "—")
        after = (change.get("after") or {}).get("title", "—")
        decision = bundle["decisions"].get(change["id"], {}).get("action", "-")
        print(f"  [{change['id']}] {change['kind']:12s} {change['dateKey']}  {decision}")
        if change["kind"] != "ADDED":
            print(f"      پیش: {before[:90]}")
        if change["kind"] != "REMOVED":
            print(f"      پس : {after[:90]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="بازبینی و اعمالِ تغییراتِ نسخه‌های تقویم")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="پیش‌نویس‌های در انتظار")
    p_list.add_argument("--year", type=int)
    p_show = sub.add_parser("show", help="نمایشِ یک پیش‌نویس")
    p_show.add_argument("--revision", required=True)
    p_show.add_argument("--all", action="store_true", help="نمایشِ UNCHANGEDها هم")
    p_dec = sub.add_parser("decide", help="ثبتِ تصمیم برای یک تغییر")
    p_dec.add_argument("--revision", required=True)
    p_dec.add_argument("--change", required=True)
    p_dec.add_argument("--action", required=True,
                       choices=["approve", "reject", "edit", "needs-evidence"])
    p_dec.add_argument("--title")
    p_dec.add_argument("--solar", help="سال-ماه-روز")
    p_dec.add_argument("--holiday", choices=["true", "false"])
    p_dec.add_argument("--description", help="توضیحِ اصلاح‌شده برای همان سال")
    p_dec.add_argument("--note", default="")
    p_dec.add_argument("--by", required=True)
    p_all = sub.add_parser("approve-all", help="تأییدِ گروهی با ثبتِ تصمیمِ مدیر")
    p_all.add_argument("--revision", required=True)
    p_all.add_argument("--by", required=True)
    p_all.add_argument("--note", default="")
    p_fin = sub.add_parser("finalize", help="اعمالِ تأییدشده‌ها")
    p_fin.add_argument("--revision", required=True)
    p_fin.add_argument("--by", required=True)
    p_fin.add_argument("--note", default="")
    p_rej = sub.add_parser("reject", help="ردِ کلِ پیش‌نویس")
    p_rej.add_argument("--revision", required=True)
    p_rej.add_argument("--by", required=True)
    p_rej.add_argument("--note", default="")
    p_rev = sub.add_parser("revert", help="بازگردانیِ یک تأیید یا یک تغییر")
    p_rev.add_argument("--log")
    p_rev.add_argument("--change")
    p_rev.add_argument("--by", required=True)
    p_rev.add_argument("--note", default="")
    sub.add_parser("status", help="خلاصهٔ وضعیت")
    args = ap.parse_args()

    try:
        if args.cmd == "list":
            bundles = pending_bundles(args.year)
            if not bundles:
                print("پیش‌نویسِ در انتظاری نیست.")
            for bundle in bundles:
                _print_bundle(bundle)
            return 0
        if args.cmd == "show":
            _print_bundle(load_bundle(args.revision), full=args.all)
            return 0
        if args.cmd == "decide":
            edit = {}
            if args.title:
                edit["title"] = args.title
            if args.solar:
                edit["solar"] = [int(x) for x in args.solar.replace("/", "-").split("-")]
            if args.holiday:
                edit["holiday"] = args.holiday == "true"
            if args.description is not None:
                edit["description"] = args.description
            if args.note and args.action == "edit":
                edit["note"] = args.note
            decide(args.revision, args.change, args.action, by=args.by, note=args.note, edit=edit or None)
            print(f"{args.change}: {args.action} ثبت شد.")
            return 0
        if args.cmd == "approve-all":
            bundle = approve_all(args.revision, by=args.by, note=args.note)
            print(f"{len(bundle['decisions'])} تصمیم ثبت شد؛ finalize را اجرا کنید.")
            return 0
        if args.cmd == "finalize":
            result = finalize(args.revision, by=args.by, note=args.note)
            print(f"تأیید شد: {result['revision']['id']} · {result['rows']} ردیف · "
                  f"ChangeLog {result['entry']['id']}")
            return 0
        if args.cmd == "reject":
            reject_revision(args.revision, by=args.by, note=args.note)
            print("پیش‌نویس رد شد؛ دادهٔ اصلی تغییر نکرد.")
            return 0
        if args.cmd == "revert":
            if bool(args.log) == bool(args.change):
                print("یکی از --log یا --change لازم است.", file=sys.stderr)
                return 2
            entry = (revert_log(args.log, by=args.by, note=args.note) if args.log
                     else revert_change(args.change, by=args.by, note=args.note))
            print(f"بازگردانی ثبت شد: {entry['id']} · نسخهٔ {entry['revisionId']}")
            return 0
        if args.cmd == "status":
            history = store.load_history()
            active = store.active_revisions(history["revisions"])
            print(f"نسخه‌های فعال: {len(active)} سال · هویت‌ها: {len(history['events'])} · "
                  f"وقوع‌ها: {len(history['occurrences'])} · ChangeLog: {len(history['changelog'])}")
            print("پیش‌نویس‌های در انتظار:", len(pending_bundles()))
            return 0
    except (ValueError, FileNotFoundError) as exc:
        print(f"خطا: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
