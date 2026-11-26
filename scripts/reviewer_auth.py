#!/usr/bin/env python3
"""حسابِ بازبینِ محلی با رمز و کلیدِ Ed25519ِ رمزگذاری‌شده.

این احرازِ هویت، «محلی» است: هویت را در همین نصب می‌سازد و ادعای هویتِ دولتی یا
OIDC ندارد. رمزِ عبور هرگز ذخیره نمی‌شود؛ فقط salt و scrypt hash می‌ماند. کلیدِ
خصوصی با همان رمز رمزگذاری می‌شود و سرور فقط پس از ورودِ موفق آن را در حافظه
باز می‌کند. بنابراین بدون رمزِ بازبین، امضای تأیید ساخته نمی‌شود.

    py -3 scripts/reviewer_auth.py register --id reviewer-1 --name "نام بازبین"
    py -3 scripts/reviewer_auth.py list
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

ROOT = Path(__file__).resolve().parents[1]
REVIEWERS_FILE = ROOT / "data" / "review" / "reviewers.json"
KEY_DIR = ROOT / ".review-keys"
AGENT_PREFIXES = ("agent:", "proposal:", "ai:", "bot:", "codebuff:")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def validate_reviewer_id(reviewer_id: str) -> str:
    value = (reviewer_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}", value):
        raise ValueError("شناسهٔ بازبین باید ۳ تا ۶۴ نویسهٔ امن باشد")
    if value.lower().startswith(AGENT_PREFIXES):
        raise ValueError("شناسهٔ عامل/ربات نمی‌تواند بازبین انسانی باشد")
    return value


def _password_hash(password: str, salt: bytes) -> bytes:
    if len(password) < 8:
        raise ValueError("رمزِ بازبین باید حداقل ۸ نویسه باشد")
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=1 << 14,
                          r=8, p=1, dklen=32)


def register(reviewer_id: str, display_name: str, password: str, *,
             reviewers_file: Path | None = None, key_dir: Path | None = None) -> dict:
    """حسابِ بازبین می‌سازد؛ کلیدِ خصوصیِ رمزگذاری‌شده بیرون از git می‌ماند."""
    rid = validate_reviewer_id(reviewer_id)
    name = (display_name or "").strip()
    if len(name) < 2:
        raise ValueError("نامِ نمایشیِ بازبین لازم است")
    reviewers_path = reviewers_file or REVIEWERS_FILE
    keys = key_dir or KEY_DIR
    document = _load(reviewers_path, {"schema": 1, "reviewers": []})
    if any(r.get("id") == rid for r in document.get("reviewers", [])):
        raise ValueError(f"بازبینِ {rid} از قبل ثبت شده است")
    salt = hashlib.sha256((rid + now_iso()).encode("utf-8")).digest()[:16]
    digest = _password_hash(password, salt)
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password.encode("utf-8")),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = "ed25519:" + hashlib.sha256(public_raw).hexdigest()[:16]
    keys.mkdir(parents=True, exist_ok=True)
    key_path = keys / f"{rid}.pem"
    if key_path.exists():
        raise ValueError(f"کلیدِ {rid} از قبل هست")
    key_path.write_bytes(private_pem)
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    record = {
        "id": rid,
        "displayName": name,
        "salt": _b64(salt),
        "passwordHash": _b64(digest),
        "keyId": key_id,
        "publicKey": _b64(public_raw),
        "keyFile": str(key_path.relative_to(ROOT)).replace("\\", "/")
        if key_path.is_relative_to(ROOT) else str(key_path),
        "createdAt": now_iso(),
        "active": True,
    }
    document.setdefault("reviewers", []).append(record)
    _write(reviewers_path, document)
    return record


def load_reviewers(reviewers_file: Path | None = None) -> list[dict]:
    document = _load(reviewers_file or REVIEWERS_FILE, {"reviewers": []})
    return list(document.get("reviewers", []))


def public_reviewers(reviewers_file: Path | None = None) -> list[dict]:
    return [{"id": r["id"], "displayName": r.get("displayName", r["id"])}
            for r in load_reviewers(reviewers_file) if r.get("active", True)]


def owner_of_key(key_id: str, reviewers_file: Path | None = None) -> str | None:
    """مالکِ ثبت‌شدهٔ کلید؛ برای جلوگیری از جعلِ نامِ بازبین روی امضای دیگری."""
    for record in load_reviewers(reviewers_file):
        if record.get("keyId") == key_id:
            return record.get("id")
    return None


def authenticate(reviewer_id: str, password: str, *,
                 reviewers_file: Path | None = None,
                 key_dir: Path | None = None) -> dict:
    record = next((r for r in load_reviewers(reviewers_file)
                   if r.get("id") == reviewer_id and r.get("active", True)), None)
    if record is None or len(password) < 8:
        raise ValueError("شناسه یا رمزِ بازبین نادرست است")
    salt = _unb64(record["salt"])
    expected = _unb64(record["passwordHash"])
    actual = _password_hash(password, salt)
    if not hmac.compare_digest(expected, actual):
        raise ValueError("شناسه یا رمزِ بازبین نادرست است")
    key_path = (key_dir / f"{reviewer_id}.pem") if key_dir else ROOT / record["keyFile"]
    if not key_path.exists():
        raise ValueError("کلیدِ خصوصیِ بازبین در دسترس نیست")
    try:
        private = serialization.load_pem_private_key(
            key_path.read_bytes(), password=password.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise ValueError("رمزِ کلیدِ خصوصی نادرست است") from exc
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("کلیدِ بازبین Ed25519 نیست")
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if _b64(public_raw) != record["publicKey"]:
        raise ValueError("کلیدِ خصوصی با کلیدِ ثبت‌شده نمی‌خواند")
    return {
        "reviewerId": record["id"],
        "displayName": record.get("displayName", record["id"]),
        "keyId": record["keyId"],
        "publicKey": record["publicKey"],
        "privateKey": private,
        "authenticatedAt": now_iso(),
        "assurance": "local-password-and-encrypted-key",
    }


def sign(session: dict, payload: dict) -> str:
    return _b64(session["privateKey"].sign(canonical(payload)))


def verify(public_key_b64: str, payload: dict, signature_b64: str) -> bool:
    try:
        public = Ed25519PublicKey.from_public_bytes(_unb64(public_key_b64))
        public.verify(_unb64(signature_b64), canonical(payload))
        return True
    except Exception:  # noqa: BLE001 - هر خطای رمزنگاری = نامعتبر
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="حساب‌های محلیِ بازبین")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("register")
    p_add.add_argument("--id", required=True)
    p_add.add_argument("--name", required=True)
    sub.add_parser("list")
    args = ap.parse_args()
    if args.cmd == "list":
        for r in public_reviewers():
            print(f"{r['id']} — {r['displayName']}")
        return 0
    if args.cmd == "register":
        password = getpass.getpass("رمزِ بازبین: ")
        again = getpass.getpass("تکرارِ رمز: ")
        if password != again:
            print("رمزها یکی نیستند.", file=sys.stderr)
            return 1
        try:
            record = register(args.id, args.name, password)
        except ValueError as exc:
            print(f"خطا: {exc}", file=sys.stderr)
            return 1
        print(f"بازبین ثبت شد: {record['id']} · {record['keyId']}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
