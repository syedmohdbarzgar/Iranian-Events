#!/usr/bin/env python3
"""دفترِ تأییدِ امضاشده برای تصمیم‌های هویت (P0-01/P0-02).

تأییدِ انسانی دیگر یک رشتهٔ ثابت در کد یا یک فیلدِ JSON نیست. هر تصمیم یک
«بیانیهٔ» کانونی دارد (شناسه، تصمیم، مقصد، علت، شاهد، اجزا) که SHA-256 آن
محاسبه می‌شود. تأیید، امضای Ed25519 روی همین هش است و کلیدِ عمومی در
``data/history/approvals/trusted-keys.json`` ثبت می‌شود. امضا فقط یکپارچگیِ
رکورد را ثابت می‌کند؛ اگر ثبت‌کنندهٔ رکورد عامل باشد، ``recordedBy`` و
``attestation`` این را صریح می‌گویند و امضا امضای شخصیِ انسان نیست.

قاعده‌ها:

* کلیدِ خصوصی هرگز در مخزن نیست (``.approval-keys/`` ignored است)؛
* دفتر فقط-افزودنی است و هر رکورد هشِ رکوردِ پیشین را در زنجیره دارد؛
* ویرایشِ JSON تصمیم، جابه‌جاییِ رکورد یا امضای جعلی در گیت رد می‌شود؛
* ``revoke`` هم امضاشده است، بنابراین تاریخچهٔ تصمیم حفظ می‌شود.

    py -3 scripts/approval_ledger.py keygen --owner "user:..."
    py -3 scripts/approval_ledger.py sign --all --private .approval-keys/approver.key \
        --approver "user:..." --channel chat --statement "..."
    py -3 scripts/approval_ledger.py verify
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - جریانِ غیرقابل‌تنظیم
        pass

ROOT = Path(__file__).resolve().parents[1]
APPROVAL_DIR = ROOT / "data" / "history" / "approvals"
LEDGER_FILE = APPROVAL_DIR / "identity-approvals.json"
TRUST_FILE = APPROVAL_DIR / "trusted-keys.json"
DEFAULT_PRIVATE_KEY = ROOT / ".approval-keys" / "approver.key"
STATEMENT_KIND = "identity-review-v1"
LEDGER_KIND = "identity-approval-ledger-v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_hex(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


# ───────────────────────────── بیانیهٔ تصمیم ─────────────────────────────

def _normal_evidence(items) -> list[dict]:
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        out.append({
            "revisionId": item.get("revisionId"),
            "page": item.get("page"),
            "year": item.get("year"),
            "observedTitle": item.get("observedTitle"),
        })
    return sorted(out, key=lambda i: (str(i.get("revisionId")), int(i.get("page") or 0),
                                      str(i.get("observedTitle"))))


def _normal_constituents(items) -> list[dict]:
    out = []
    for item in items or []:
        if isinstance(item, dict) and item.get("id"):
            out.append({"id": item["id"], "title": item.get("title", "")})
    return sorted(out, key=lambda i: i["id"])


def decision_statement(entry: dict) -> dict:
    """بیانیهٔ ثابتِ تصمیم؛ هر تغییری در آن، امضای قبلی را باطل می‌کند."""
    return {
        "kind": STATEMENT_KIND,
        "eventId": entry.get("eventId"),
        "decision": entry.get("decision"),
        "target": entry.get("target"),
        "reason": entry.get("reason", ""),
        "constituents": _normal_constituents(entry.get("constituents")),
        "evidence": _normal_evidence(entry.get("evidence")),
        "reviewedBy": entry.get("reviewedBy"),
        "reviewedAt": entry.get("reviewedAt"),
    }


def statement_digest(entry: dict) -> str:
    return sha256_hex(decision_statement(entry))


def signature_payload(record: dict) -> dict:
    payload = {
        "kind": STATEMENT_KIND,
        "action": record.get("action"),
        "eventId": record.get("eventId"),
        "statementSha256": record.get("statementSha256"),
        "approver": record.get("approver"),
        "channel": record.get("channel"),
        "approvedAt": record.get("approvedAt"),
        "keyId": record.get("keyId"),
        "note": record.get("note", ""),
    }
    # رکوردهای قدیمی این فیلدها را ندارند؛ افزودنِ آن‌ها به payload امضای
    # قدیمی را باطل می‌کند. فقط وقتی حاضرند امضا می‌شوند.
    for key in ("recordedBy", "attestation"):
        if record.get(key):
            payload[key] = record[key]
    return payload


# ───────────────────────────── کلیدها ─────────────────────────────

def load_trusted(path: Path | None = None) -> dict:
    data = load_json(path or TRUST_FILE, {"version": 1, "keys": []})
    if not isinstance(data, dict):
        return {"version": 1, "keys": []}
    data.setdefault("keys", [])
    return data


def trusted_key(key_id: str, path: Path | None = None) -> dict | None:
    return next((k for k in load_trusted(path).get("keys", []) if k.get("keyId") == key_id), None)


def generate_key(private_path: Path, *, owner: str, note: str = "") -> dict:
    if private_path.exists():
        raise ValueError(f"کلید از قبل هست: {private_path}")
    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    raw_public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = "ed25519:" + hashlib.sha256(raw_public).hexdigest()[:16]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(private_path, {
        "version": 1,
        "algorithm": "Ed25519",
        "keyId": key_id,
        "privateKey": _b64(raw_private),
        "publicKey": _b64(raw_public),
        "createdAt": now_iso(),
        "owner": owner,
        "note": note,
    })
    try:
        os.chmod(private_path, 0o600)
    except OSError:
        pass
    trust = load_trusted()
    if not any(k.get("keyId") == key_id for k in trust["keys"]):
        trust["keys"].append({
            "keyId": key_id,
            "algorithm": "Ed25519",
            "publicKey": _b64(raw_public),
            "owner": owner,
            "createdAt": now_iso(),
            "note": note,
        })
        write_json(TRUST_FILE, trust)
    return {"keyId": key_id, "publicKey": _b64(raw_public), "privatePath": str(private_path)}


def load_private(path: Path) -> tuple[Ed25519PrivateKey, dict]:
    data = load_json(path, None)
    if not isinstance(data, dict) or not data.get("privateKey"):
        raise ValueError(f"کلیدِ خصوصیِ معتبر نیست: {path}")
    key = Ed25519PrivateKey.from_private_bytes(_unb64(data["privateKey"]))
    return key, data


def sign_bytes(private_path: Path, payload: dict) -> tuple[str, dict]:
    key, meta = load_private(private_path)
    signature = key.sign(canonical_bytes(payload))
    return _b64(signature), meta


def verify_signature(public_b64: str, payload: dict, signature_b64: str) -> bool:
    try:
        public = Ed25519PublicKey.from_public_bytes(_unb64(public_b64))
        public.verify(_unb64(signature_b64), canonical_bytes(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# ───────────────────────────── دفتر ─────────────────────────────

def ledger_document() -> dict:
    data = load_json(LEDGER_FILE, None)
    if data is None:
        return {"version": 1, "kind": LEDGER_KIND, "entries": []}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ValueError("دفترِ تأیید ساختارِ معتبر ندارد")
    return data


def _record_hash(prev_hash: str, record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "recordHash"}
    return sha256_hex({"prevHash": prev_hash, "record": body})


def verify_ledger(entries: list[dict], trust: dict | None = None) -> list[dict]:
    """زنجیره، امضا، کلیدِ موردِ اعتماد و تطابقِ بیانیه را می‌سنجد."""
    trust = trust if trust is not None else load_trusted()
    trusted = {k.get("keyId"): k for k in trust.get("keys", [])}
    issues: list[dict] = []
    prev = ""
    seen_seq: set[int] = set()
    for index, record in enumerate(entries):
        seq = record.get("seq")
        if not isinstance(seq, int) or seq in seen_seq:
            issues.append({"code": "APPROVAL_LEDGER_SEQ", "severity": "error",
                           "message": "شمارهٔ رکوردِ دفتر تکراری/نامعتبر است",
                           "ref": record.get("eventId", "")})
        seen_seq.add(seq)
        if record.get("prevHash") != prev:
            issues.append({"code": "APPROVAL_LEDGER_CHAIN", "severity": "error",
                           "message": "زنجیرهٔ دفترِ تأیید شکسته است",
                           "ref": record.get("eventId", "")})
        expected_hash = _record_hash(prev, record)
        if record.get("recordHash") != expected_hash:
            issues.append({"code": "APPROVAL_LEDGER_HASH", "severity": "error",
                           "message": "هشِ رکورد با محتوای آن نمی‌خواند",
                           "ref": record.get("eventId", "")})
        prev = expected_hash

        key_id = record.get("keyId")
        key = trusted.get(key_id)
        if key is None:
            issues.append({"code": "APPROVAL_KEY_UNTRUSTED", "severity": "error",
                           "message": f"کلیدِ تأیید موردِ اعتماد نیست: {key_id}",
                           "ref": record.get("eventId", "")})
        elif record.get("publicKey") != key.get("publicKey"):
            issues.append({"code": "APPROVAL_KEY_MISMATCH", "severity": "error",
                           "message": "کلیدِ عمومیِ رکورد با کلیدِ موردِ اعتماد یکی نیست",
                           "ref": record.get("eventId", "")})
        if not verify_signature(record.get("publicKey", ""), signature_payload(record),
                                record.get("signature", "")):
            issues.append({"code": "APPROVAL_SIGNATURE", "severity": "error",
                           "message": "امضای رکورد معتبر نیست",
                           "ref": record.get("eventId", "")})
        if record.get("action") not in {"approve", "revoke"}:
            issues.append({"code": "APPROVAL_ACTION", "severity": "error",
                           "message": "کنشِ دفتر ناشناخته است", "ref": record.get("eventId", "")})
        if not record.get("approvedAt") or not record.get("approver"):
            issues.append({"code": "APPROVAL_META", "severity": "error",
                           "message": "زمان/تأییدکننده در رکورد نیست",
                           "ref": record.get("eventId", "")})
        # بیانیه باید با خودِ رکورد هم بخواند
        statement = record.get("statement")
        if not isinstance(statement, dict):
            issues.append({"code": "APPROVAL_STATEMENT", "severity": "error",
                           "message": "بیانیهٔ تصمیم در رکورد نیست", "ref": record.get("eventId", "")})
        elif sha256_hex(statement) != record.get("statementSha256"):
            issues.append({"code": "APPROVAL_STATEMENT", "severity": "error",
                           "message": "هشِ بیانیه با محتوای آن نمی‌خواند",
                           "ref": record.get("eventId", "")})
        elif statement.get("eventId") != record.get("eventId"):
            issues.append({"code": "APPROVAL_STATEMENT", "severity": "error",
                           "message": "بیانیه به هویتِ دیگری اشاره می‌کند",
                           "ref": record.get("eventId", "")})
        if index and seq != entries[index - 1].get("seq", 0) + 1:
            issues.append({"code": "APPROVAL_LEDGER_GAP", "severity": "error",
                           "message": "شمارهٔ رکوردها پیوسته نیست",
                           "ref": record.get("eventId", "")})
    return issues


def append_action(entry: dict, private_path: Path, *, action: str, approver: str,
                  channel: str = "cli", note: str = "", approved_at: str | None = None,
                  recorded_by: str = "agent:codebuff",
                  attestation: str = "agent-recorded-chat-approval") -> dict:
    if action not in {"approve", "revoke"}:
        raise ValueError("کنشِ نامعتبر")
    if not approver.strip():
        raise ValueError("نامِ تأییدکننده لازم است")
    document = ledger_document()
    entries = document["entries"]
    existing = verify_ledger(entries)
    if existing:
        raise ValueError("دفترِ تأیید پیش از افزودن رکورد معتبر نیست: "
                         + ", ".join(sorted({i["code"] for i in existing})))
    statement = decision_statement(entry)
    digest = sha256_hex(statement)
    seq = len(entries) + 1
    prev = entries[-1]["recordHash"] if entries else ""
    record = {
        "seq": seq,
        "action": action,
        "eventId": entry["eventId"],
        "statement": statement,
        "statementSha256": digest,
        "approver": approver.strip(),
        "channel": channel,
        "approvedAt": approved_at or now_iso(),
        "keyId": "",
        "publicKey": "",
        "note": note,
        "recordedBy": recorded_by,
        "attestation": attestation,
        "prevHash": prev,
    }
    meta = load_json(private_path, {})
    record["keyId"] = meta.get("keyId", "")
    record["publicKey"] = meta.get("publicKey", "")
    signature, _ = sign_bytes(private_path, signature_payload(record))
    record["signature"] = signature
    record["recordHash"] = _record_hash(prev, record)
    entries.append(record)
    write_json(LEDGER_FILE, document)
    return record


def latest_records(entries: list[dict] | None = None) -> dict[str, dict]:
    entries = ledger_document()["entries"] if entries is None else entries
    out: dict[str, dict] = {}
    for record in entries:
        out[record.get("eventId", "")] = record
    return out


def attestation_class(record: dict | None) -> str:
    """کلاسِ شاهدِ رکورد؛ این تابع هویتِ شخصی را اثبات نمی‌کند."""
    if not record:
        return "missing"
    recorded_by = str(record.get("recordedBy") or "")
    attestation = str(record.get("attestation") or "")
    if recorded_by.startswith("human:") and attestation.startswith("human-"):
        return "human-signed"
    if "chat" in attestation and recorded_by.startswith("agent:"):
        return "machine-recorded-chat-approval"
    return "machine-recorded"


def approved_at_precision(record: dict | None) -> str:
    """دقتِ زمانِ تأیید؛ نیمه‌شبِ ثبت‌شده تاریخ است، نه زمانِ دقیق."""
    value = str((record or {}).get("approvedAt") or "")
    if not value:
        return "missing"
    if value.endswith("T00:00:00Z"):
        return "date-only"
    return "second"


def attached_approval(entry: dict, record: dict) -> dict:
    return {
        "kind": "human",
        "method": "ed25519",
        "by": record["approver"],
        "at": record["approvedAt"],
        "channel": record.get("channel", ""),
        "note": record.get("note", ""),
        "keyId": record["keyId"],
        "publicKey": record["publicKey"],
        "signature": record["signature"],
        "statementSha256": record["statementSha256"],
        "recordedBy": record.get("recordedBy", ""),
        "attestation": record.get("attestation", ""),
        "ledgerSeq": record["seq"],
        "recordHash": record["recordHash"],
    }


def verify_entry(entry: dict, trust: dict | None = None) -> list[dict]:
    """تأییدِ متصل به یک تصمیم را بدونِ نیاز به دفتر می‌سنجد."""
    approval = entry.get("approval") or {}
    if approval.get("kind") != "human":
        return [{"code": "REVIEW_APPROVAL_MISSING", "severity": "error",
                 "message": "تصمیمِ هویت تأییدِ صریحِ انسانی ندارد",
                 "ref": entry.get("eventId", "")}]
    if approval.get("method") != "ed25519":
        return [{"code": "REVIEW_APPROVAL_UNSIGNED", "severity": "error",
                 "message": "تأیید روشِ امضاشده ندارد", "ref": entry.get("eventId", "")}]
    trust = trust if trust is not None else load_trusted()
    key = trusted_key(approval.get("keyId", ""), None)
    issues: list[dict] = []
    if key is None:
        issues.append({"code": "APPROVAL_KEY_UNTRUSTED", "severity": "error",
                       "message": "کلیدِ تأیید در فهرستِ موردِ اعتماد نیست",
                       "ref": entry.get("eventId", "")})
    elif key.get("publicKey") != approval.get("publicKey"):
        issues.append({"code": "APPROVAL_KEY_MISMATCH", "severity": "error",
                       "message": "کلیدِ عمومیِ تأیید با کلیدِ موردِ اعتماد نمی‌خواند",
                       "ref": entry.get("eventId", "")})
    digest = statement_digest(entry)
    if approval.get("statementSha256") != digest:
        issues.append({"code": "APPROVAL_STATEMENT_MISMATCH", "severity": "error",
                       "message": "تصمیم پس از امضا تغییر کرده است",
                       "ref": entry.get("eventId", "")})
    payload = {
        "kind": STATEMENT_KIND,
        "action": "approve",
        "eventId": entry.get("eventId"),
        "statementSha256": digest,
        "approver": approval.get("by"),
        "channel": approval.get("channel"),
        "approvedAt": approval.get("at"),
        "keyId": approval.get("keyId"),
        "note": approval.get("note", ""),
    }
    for key in ("recordedBy", "attestation"):
        if approval.get(key):
            payload[key] = approval[key]
    if not verify_signature(approval.get("publicKey", ""), payload,
                            approval.get("signature", "")):
        issues.append({"code": "APPROVAL_SIGNATURE", "severity": "error",
                       "message": "امضای تأیید معتبر نیست", "ref": entry.get("eventId", "")})
    return issues


def is_approved(entry: dict, trust: dict | None = None) -> bool:
    return entry.get("active", True) is not False and not verify_entry(entry, trust)


def approvals_for(entries: list[dict], trust: dict | None = None) -> dict[str, dict]:
    """تصمیم‌های دارای تأییدِ معتبر + رکوردِ دفتر؛ تصمیمِ بدونِ امضا کنار گذاشته می‌شود."""
    trust = trust if trust is not None else load_trusted()
    by_event = {e.get("eventId"): e for e in entries if e.get("eventId")}
    out: dict[str, dict] = {}
    for event_id, record in latest_records().items():
        entry = by_event.get(event_id)
        if entry is None:
            continue
        if record.get("action") != "approve":
            continue
        if record.get("statementSha256") != statement_digest(entry):
            continue
        if verify_entry({**entry, "approval": attached_approval(entry, record)}, trust):
            continue
        out[event_id] = record
    return out


# ───────────────────────────── CLI ─────────────────────────────

def _load_reviews() -> list[dict]:
    path = ROOT / "data" / "history" / "identity-reviews.json"
    return list(load_json(path, {"reviews": []}).get("reviews", []))


def main() -> int:
    ap = argparse.ArgumentParser(description="دفترِ تأییدِ امضاشده")
    sub = ap.add_subparsers(dest="cmd", required=True)
    kg = sub.add_parser("keygen", help="ساختِ کلیدِ خصوصی و ثبتِ کلیدِ عمومی")
    kg.add_argument("--private", default=str(DEFAULT_PRIVATE_KEY))
    kg.add_argument("--owner", required=True)
    kg.add_argument("--note", default="")

    sign = sub.add_parser("sign", help="امضای تصمیم‌های فعلی")
    sign.add_argument("--private", default=str(DEFAULT_PRIVATE_KEY))
    sign.add_argument("--approver", required=True)
    sign.add_argument("--channel", default="cli")
    sign.add_argument("--statement", required=True,
                      help="متنِ صریحِ تأیید که در مدرک ثبت می‌شود")
    sign.add_argument("--event", action="append", default=[])
    sign.add_argument("--all", action="store_true")
    sign.add_argument("--note", default="")
    sign.add_argument("--approved-at", default=None,
                      help="زمانِ واقعیِ تأیید انسانی (نه زمانِ امضای ماشینی)")
    sign.add_argument("--recorded-by", default="agent:codebuff")
    sign.add_argument("--attestation", default="agent-recorded-chat-approval")

    revoke = sub.add_parser("revoke", help="پس‌گرفتنِ امضاشدهٔ یک تصمیم")
    revoke.add_argument("--private", default=str(DEFAULT_PRIVATE_KEY))
    revoke.add_argument("--approver", required=True)
    revoke.add_argument("--event", required=True)
    revoke.add_argument("--statement", required=True)
    revoke.add_argument("--note", default="")

    sub.add_parser("verify", help="بررسیِ زنجیره و امضاها")
    sub.add_parser("pending", help="فهرستِ تصمیم‌های بدونِ تأیید")
    args = ap.parse_args()

    if args.cmd == "keygen":
        info = generate_key(Path(args.private), owner=args.owner, note=args.note)
        print(f"keyId={info['keyId']} private={info['privatePath']}")
        return 0

    if args.cmd == "verify":
        entries = ledger_document()["entries"]
        issues = verify_ledger(entries)
        for issue in issues:
            print(f"{issue['severity']}: {issue['code']} {issue['message']} {issue['ref']}")
        print(f"ledger={len(entries)} errors={sum(1 for i in issues if i['severity']=='error')}")
        return 1 if any(i["severity"] == "error" for i in issues) else 0

    reviews = _load_reviews()
    if args.cmd == "pending":
        approved = approvals_for(reviews)
        pending = [e for e in reviews if e.get("eventId") not in approved]
        for entry in pending:
            print(f"{entry.get('eventId')} {statement_digest(entry)[:16]}")
        print(f"pending={len(pending)} approved={len(approved)}")
        return 0

    if args.cmd == "sign":
        wanted = [e for e in reviews if args.all or e.get("eventId") in args.event]
        if not wanted:
            print("تصمیمی برای امضا انتخاب نشد", file=sys.stderr)
            return 2
        for entry in wanted:
            record = append_action(entry, Path(args.private), action="approve",
                                   approver=args.approver, channel=args.channel,
                                   note=args.statement + (" · " + args.note if args.note else ""),
                                   approved_at=args.approved_at,
                                   recorded_by=args.recorded_by,
                                   attestation=args.attestation)
            print(f"approved {entry['eventId']} seq={record['seq']} "
                  f"digest={record['statementSha256'][:16]}")
        return 0

    if args.cmd == "revoke":
        entry = next((e for e in reviews if e.get("eventId") == args.event), None)
        if entry is None:
            print("تصمیم پیدا نشد", file=sys.stderr)
            return 2
        record = append_action(entry, Path(args.private), action="revoke",
                               approver=args.approver, channel="cli",
                               note=args.statement + (" · " + args.note if args.note else ""))
        print(f"revoked {args.event} seq={record['seq']}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
