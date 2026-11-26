#!/usr/bin/env python3
"""دفترِ فقط-افزودنیِ تصمیم‌های پنل بازبینی، با زنجیرهٔ هش و امضای Ed25519.

هر تصمیم/تأییدِ سال/بازگردانی یک رکوردِ امضاشده است. حذف، جابه‌جایی، تکرار یا
ویرایشِ رکورد در verify آشکار می‌شود؛ کلیدِ عمومی باید در فهرستِ بازبینان باشد،
وگرنه امضای خودساخته معتبر نیست.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402
import review_model  # noqa: E402
import reviewer_auth  # noqa: E402

AUDIT_FILE = ROOT / "data" / "review" / "review-audit-log.json"
AUDIT_HEAD_FILE = ROOT / "data" / "review" / "review-audit-head.json"
ACTIONS = {"decision", "year-approval", "finalize", "revert", "delegate"}
_APPEND_LOCK = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load(path: Path) -> dict:
    if not path.exists():
        return {"schema": 1, "kind": "human-review-audit-v1", "entries": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("entries", [])
    return data


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def head_path(file: Path | None = None) -> Path:
    if file is None:
        return AUDIT_HEAD_FILE
    return file.with_name(file.stem + "-head.json")


def _head_payload(entry: dict) -> dict:
    return {"seq": entry["seq"], "recordHash": entry["recordHash"]}


def _verify_head(file: Path | None, entries: list[dict],
                 trusted: dict[str, str]) -> list[dict]:
    path = head_path(file)
    if not path.exists():
        return ([{"code": "AUDIT_HEAD_MISSING", "ref": "",
                  "message": "سرِ امضاشدهٔ دفتر نیست؛ احتمال قطع/بازگردانی"}]
                if entries else [])
    try:
        head = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return [{"code": "AUDIT_HEAD_INVALID", "message": "سرِ دفتر خوانا نیست", "ref": ""}]
    if not entries:
        return [{"code": "AUDIT_HEAD_ORPHAN", "message": "سرِ دفتر بدونِ رکورد است", "ref": ""}]
    if head.get("seq") != entries[-1].get("seq") or \
            head.get("recordHash") != entries[-1].get("recordHash"):
        return [{"code": "AUDIT_TRUNCATED", "message": "سرِ دفتر با آخرین رکورد نمی‌خواند",
                 "ref": ""}]
    actor = head.get("actor") or {}
    public_key = trusted.get(actor.get("keyId"))
    if public_key is None or head.get("publicKey") != public_key:
        return [{"code": "AUDIT_HEAD_KEY", "message": "کلیدِ سرِ دفتر مورد اعتماد نیست",
                 "ref": actor.get("reviewerId", "")}]
    body = {k: v for k, v in head.items() if k not in {"publicKey", "signature"}}
    if not reviewer_auth.verify(public_key, body, head.get("signature", "")):
        return [{"code": "AUDIT_HEAD_SIGNATURE", "message": "امضای سرِ دفتر معتبر نیست",
                 "ref": actor.get("reviewerId", "")}]
    return []


def _body(seq: int, action: str, actor: dict, at: str, payload: dict, prev: str) -> dict:
    return {
        "seq": seq,
        "action": action,
        "actor": {"reviewerId": actor["reviewerId"],
                  "displayName": actor.get("displayName", actor["reviewerId"]),
                  "keyId": actor["keyId"]},
        "at": at,
        "payload": payload,
        "prevHash": prev,
    }


def _record_hash(body: dict) -> str:
    # هش روی بدنهٔ بدونِ خودِ recordHash محاسبه می‌شود؛ امضا روی بدنه+هش است.
    return review_model.sha256_hex({k: v for k, v in body.items() if k != "recordHash"})


def _signed_payload(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k not in {"publicKey", "signature"}}


def _trusted(reviewers_file: Path | None = None) -> dict[str, str]:
    return {r["keyId"]: r["publicKey"] for r in reviewer_auth.load_reviewers(reviewers_file)
            if r.get("active", True)}


def verify_entry(entry: dict, trusted: dict[str, str]) -> list[dict]:
    """یک رکورد را بدونِ نیاز به زنجیره/شمارهٔ کامل می‌سنجد."""
    actor = entry.get("actor") or {}
    public_key = trusted.get(actor.get("keyId"))
    if public_key is None:
        return [{"code": "AUDIT_KEY_UNTRUSTED", "message": "کلیدِ بازبین مورد اعتماد نیست",
                 "ref": actor.get("reviewerId", "")}]
    if entry.get("publicKey") != public_key:
        return [{"code": "AUDIT_KEY_MISMATCH", "message": "کلیدِ رکورد با بازبین نمی‌خواند",
                 "ref": actor.get("reviewerId", "")}]
    owner = reviewer_auth.owner_of_key(actor.get("keyId", ""))
    if owner and owner != actor.get("reviewerId"):
        return [{"code": "AUDIT_ACTOR_KEY", "message": "نامِ بازبین با مالکِ کلید نمی‌خواند",
                 "ref": actor.get("reviewerId", "")}]
    body = _signed_payload(entry)
    if entry.get("recordHash") != _record_hash(body):
        return [{"code": "AUDIT_HASH", "message": "هشِ رکورد نمی‌خواند",
                 "ref": actor.get("reviewerId", "")}]
    if not reviewer_auth.verify(public_key, body, entry.get("signature", "")):
        return [{"code": "AUDIT_SIGNATURE", "message": "امضای رکورد معتبر نیست",
                 "ref": actor.get("reviewerId", "")}]
    return []


def verify_entries(entries: list[dict], trusted: dict[str, str]) -> list[dict]:
    issues: list[dict] = []
    prev = ""
    seen: set[int] = set()
    for index, entry in enumerate(entries):
        seq = entry.get("seq")
        label = entry.get("actor", {}).get("reviewerId", "")
        if not isinstance(seq, int) or seq in seen:
            issues.append({"code": "AUDIT_SEQ", "message": "شمارهٔ رکورد تکراری/نامعتبر",
                           "ref": label})
        elif index and seq != entries[index - 1].get("seq", 0) + 1:
            issues.append({"code": "AUDIT_GAP", "message": "شمارهٔ زنجیره پیوسته نیست",
                           "ref": label})
        seen.add(seq)
        if entry.get("prevHash") != prev:
            issues.append({"code": "AUDIT_CHAIN", "message": "زنجیرهٔ دفتر شکسته است",
                           "ref": label})
        body = _signed_payload(entry)
        expected = _record_hash(body)
        if entry.get("recordHash") != expected:
            issues.append({"code": "AUDIT_HASH", "message": "هشِ رکورد نمی‌خواند",
                           "ref": label})
        public_key = trusted.get(entry.get("actor", {}).get("keyId"))
        if public_key is None:
            issues.append({"code": "AUDIT_KEY_UNTRUSTED", "message": "کلیدِ بازبین مورد اعتماد نیست",
                           "ref": label})
        elif entry.get("publicKey") != public_key:
            issues.append({"code": "AUDIT_KEY_MISMATCH", "message": "کلیدِ رکورد با بازبین نمی‌خواند",
                           "ref": label})
        elif (reviewer_auth.owner_of_key(entry.get("actor", {}).get("keyId", ""))
              not in {None, entry.get("actor", {}).get("reviewerId")}):
            issues.append({"code": "AUDIT_ACTOR_KEY", "message": "نامِ بازبین با مالکِ کلید نمی‌خواند",
                           "ref": label})
        elif not reviewer_auth.verify(public_key, body, entry.get("signature", "")):
            issues.append({"code": "AUDIT_SIGNATURE", "message": "امضای رکورد معتبر نیست",
                           "ref": label})
        if entry.get("action") not in ACTIONS:
            issues.append({"code": "AUDIT_ACTION", "message": "کنشِ دفتر ناشناخته است",
                           "ref": label})
        if not entry.get("at") or not entry.get("payload"):
            issues.append({"code": "AUDIT_META", "message": "زمان/دادهٔ رکورد ناقص است",
                           "ref": label})
        prev = expected
    return issues


def append(session: dict, action: str, payload: dict, *, file: Path | None = None,
           reviewers_file: Path | None = None) -> dict:
    if action not in ACTIONS:
        raise ValueError("کنشِ دفتر نامعتبر است")
    if not isinstance(payload, dict) or not payload:
        raise ValueError("دادهٔ رکورد لازم است")
    path = file or AUDIT_FILE
    with _APPEND_LOCK:
        document = _load(path)
        entries = document["entries"]
        trusted = _trusted(reviewers_file)
        issues = verify_entries(entries, trusted) + _verify_head(path, entries, trusted)
        if issues:
            raise ValueError("دفتر پیش از افزودن معتبر نیست: "
                             + ", ".join(sorted({i["code"] for i in issues})))
        prev = entries[-1]["recordHash"] if entries else ""
        body = _body(len(entries) + 1, action, session, now_iso(), payload, prev)
        body["recordHash"] = _record_hash(body)
        entry = {**body, "publicKey": session["publicKey"],
                 "signature": reviewer_auth.sign(session, body)}
        entries.append(entry)
        _write(path, document)
        head_body = {**_head_payload(entry),
                     "actor": entry["actor"], "at": entry["at"]}
        _write(head_path(path), {**head_body, "publicKey": session["publicKey"],
                                 "signature": reviewer_auth.sign(session, head_body)})
        return entry


def load_entries(file: Path | None = None) -> list[dict]:
    return list(_load(file or AUDIT_FILE).get("entries", []))


def verify_file(file: Path | None = None, reviewers_file: Path | None = None) -> list[dict]:
    entries = load_entries(file)
    trusted = _trusted(reviewers_file)
    return verify_entries(entries, trusted) + _verify_head(file, entries, trusted)


def verify_revision_approvals(file: Path | None = None,
                              reviewers_file: Path | None = None) -> list[dict]:
    """هر نسخهٔ panel-approved باید به رکوردِ امضاشدهٔ سال و همان هش گره خورده باشد."""
    entries = load_entries(file)
    trusted = _trusted(reviewers_file)
    by_seq = {e.get("seq"): e for e in entries}
    issues: list[dict] = []
    for rev in store.load_history().get("revisions", []):
        approval = rev.get("approval") or {}
        if approval.get("method") != "ed25519-review":
            continue
        label = rev.get("id", "")
        entry = by_seq.get(approval.get("auditSeq"))
        if entry is None:
            issues.append({"code": "REV_APPROVAL_MISSING",
                           "message": "نسخه تأییدِ امضاشده دارد اما رکوردش در دفتر نیست",
                           "ref": label})
            continue
        issues.extend(verify_entry(entry, trusted))
        if entry.get("action") != "year-approval":
            issues.append({"code": "REV_APPROVAL_ACTION", "ref": label,
                           "message": "رکوردِ تأیید از نوع year-approval نیست"})
        payload = entry.get("payload") or {}
        if entry.get("recordHash") != approval.get("auditRecordHash"):
            issues.append({"code": "REV_APPROVAL_HASH", "ref": label,
                           "message": "هشِ تأییدِ نسخه با دفتر نمی‌خواند"})
        if entry.get("publicKey") != approval.get("publicKey"):
            issues.append({"code": "REV_APPROVAL_KEY", "ref": label,
                           "message": "کلیدِ تأییدِ نسخه با دفتر نمی‌خواند"})
        if entry.get("signature") != approval.get("signature"):
            issues.append({"code": "REV_APPROVAL_SIGNATURE", "ref": label,
                           "message": "امضای تأییدِ نسخه با دفتر نمی‌خواند"})
        if (entry.get("actor") or {}).get("reviewerId") != approval.get("reviewerId"):
            issues.append({"code": "REV_APPROVAL_ACTOR", "ref": label,
                           "message": "بازبینِ تأییدِ نسخه با دفتر نمی‌خواند"})
        if payload.get("bundleHash") != approval.get("bundleHash"):
            issues.append({"code": "REV_APPROVAL_BUNDLE", "ref": label,
                           "message": "هشِ تصمیم‌های تأییدشده با دفتر نمی‌خواند"})
        if approval.get("reviewerId") != rev.get("approvedBy"):
            issues.append({"code": "REV_APPROVAL_APPROVER", "ref": label,
                           "message": "تأییدکنندهٔ نسخه با بازبینِ امضا یکی نیست"})
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="ممیزیِ دفترِ بازبینی انسانی")
    ap.add_argument("--file", type=Path)
    ap.add_argument("--reviewers", type=Path)
    args = ap.parse_args()
    issues = verify_file(args.file, args.reviewers)
    issues += verify_revision_approvals(args.file, args.reviewers)
    if issues:
        for issue in issues[:20]:
            print(f"{issue['code']}: {issue['message']} — {issue.get('ref', '')}")
        print(f"audit gate=FAIL issues={len(issues)}")
        return 1
    print(f"audit gate=PASS entries={len(load_entries(args.file))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
