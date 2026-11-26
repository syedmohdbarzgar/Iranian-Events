#!/usr/bin/env python3
"""سرورِ محلیِ پنلِ بازبینیِ انسانی.

فقط روی ``127.0.0.1`` گوش می‌دهد. صفحه بدونِ ورودِ بازبین، صف را نشان نمی‌دهد؛
نشست با کوکیِ HttpOnly و توکنِ CSRF محافظت می‌شود. PDF فقط از سندِ همان پیش‌نویس
و با بررسیِ هش سرو می‌شود. هیچ منطقِ تأییدی در این فایل تکرار نشده است.

    py -3 scripts/reviewer_auth.py register --id reviewer-1 --name "نام"
    py -3 scripts/review_server.py --port 8765
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import secrets
import sys
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402
import ingest_pdf  # noqa: E402
import review_changes as review  # noqa: E402
import review_panel  # noqa: E402
import reviewer_auth  # noqa: E402

TOKEN = secrets.token_urlsafe(24)
MAX_BODY = 32 << 20
MAX_UPLOAD = 30 << 20
SESSION_TTL = 12 * 3600
UPLOAD_DIR = store.REVIEW_DIR / "uploads"
PANEL_FILE = ROOT / "web" / "review-panel.html"
SESSIONS: dict[str, dict] = {}
LOGIN_FAILS: dict[str, list[float]] = {}


def save_upload(filename: str, data: bytes, directory: Path | None = None) -> Path:
    """فایلِ بارگذاری‌شده را فقط در پوشهٔ پیش‌نویس‌ها ذخیره می‌کند."""
    original = Path(filename or "").name
    if not original.lower().endswith(".pdf"):
        raise ValueError("فقط فایلِ PDF پذیرفته می‌شود")
    if not data.startswith(b"%PDF-"):
        raise ValueError("امضای فایل PDF نیست")
    if len(data) < 32:
        raise ValueError("فایلِ PDF خالی/ناقص است")
    if len(data) > MAX_UPLOAD:
        raise ValueError(f"حجمِ فایل بیش از {MAX_UPLOAD // (1 << 20)} مگابایت است")
    try:
        import pymupdf  # noqa: PLC0415 - اعتبارسنجیِ اختیاری اما در دسترس
        document = pymupdf.open(stream=data, filetype="pdf")
        if document.needs_pass or document.page_count < 1:
            raise ValueError("PDF رمزدار یا بدونِ صفحه است")
        document.close()
    except ImportError:
        if b"%%EOF" not in data[-2048:]:
            raise ValueError("PDF ناقص است (EOF ندارد)") from None
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"PDF قابل خواندن نیست: {type(exc).__name__}") from None
    target_dir = directory or UPLOAD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", original)[:80] or "calendar.pdf"
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    target = target_dir / f"{digest[:16]}-{safe}"
    if target.exists():
        return target
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


def parse_multipart(body: bytes, content_type: str) -> dict[str, tuple[str | None, bytes]]:
    """تجزیهٔ حداقلیِ multipart/form-data بدونِ کتابخانهٔ منسوخِ cgi."""
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        raise ValueError("boundary ندارد")
    boundary = b"--" + m.group(1).encode("latin-1")
    out: dict[str, tuple[str | None, bytes]] = {}
    for part in body.split(boundary)[1:]:
        if part.startswith(b"--"):
            break
        part = part.lstrip(b"\r\n")
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = head.decode("utf-8", "replace")
        nm = re.search(r'name="([^"]*)"', headers)
        if not nm:
            continue
        fm = re.search(r'filename="([^"]*)"', headers)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        out[nm.group(1)] = (fm.group(1) if fm else None, data)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "CalendarReviewPanel/2.0"

    def log_message(self, *args):  # noqa: D401 - خاموشیِ لاگِ پیش‌فرض
        return

    # ── پاسخ‌ها ──────────────────────────────────────────────────────────
    def _send(self, code: int, body: bytes, content_type: str,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, payload: dict, extra: dict[str, str] | None = None) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", extra)

    def _html(self) -> None:
        page = PANEL_FILE.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
        csp = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
               "frame-src 'self'; object-src 'self'; base-uri 'none'; form-action 'self'")
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8",
                   {"Content-Security-Policy": csp, "X-Frame-Options": "SAMEORIGIN"})

    # ── امنیت ────────────────────────────────────────────────────────────
    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            host = urlparse(origin).hostname
        except ValueError:
            return False
        return host in {"127.0.0.1", "localhost", "::1"}

    def _token_ok(self) -> bool:
        return hmac.compare_digest(self.headers.get("X-Review-Token", ""), TOKEN)

    def _session(self) -> dict | None:
        raw = self.headers.get("X-Review-Session", "")
        if not raw:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except Exception:  # noqa: BLE001
                cookie = SimpleCookie()
            morsel = cookie.get("review_session")
            raw = morsel.value if morsel else ""
        if not raw:
            return None
        session = SESSIONS.get(raw)
        if not session:
            return None
        if session["expires"] < time.time():
            SESSIONS.pop(raw, None)
            return None
        session["lastSeen"] = time.time()
        return session

    def _require_session(self) -> dict | None:
        session = self._session()
        if session is None:
            self._json(401, {"error": "برای این عملیات باید وارد شوید"})
        return session

    def _require_post(self) -> bool:
        if not self._token_ok() or not self._origin_ok():
            self._json(403, {"error": "توکن یا مبدأ درخواست نامعتبر است"})
            return False
        return True

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            raise ValueError("بدنهٔ نامعتبر")
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("JSON نامعتبر") from exc
        if not isinstance(body, dict):
            raise ValueError("بدنه باید شیء JSON باشد")
        return body

    def _pdf_path(self, revision_id: str) -> tuple[Path, dict]:
        bundle = review.load_bundle(revision_id)
        document = (bundle.get("revision") or {}).get("document") or {}
        stored = document.get("storedPath")
        if not stored:
            raise FileNotFoundError("مسیر سند در پیش‌نویس ثبت نشده است")
        candidate = Path(str(stored).replace("\\", "/"))
        path = (candidate if candidate.is_absolute() else ROOT / candidate).resolve()
        allowed = [UPLOAD_DIR.resolve(), (ROOT / "PDF").resolve()]
        if not any(path.is_relative_to(root) for root in allowed):
            raise PermissionError("مسیر سند بیرون از پوشهٔ مجاز است")
        if not path.is_file():
            raise FileNotFoundError("فایل PDF سند در دسترس نیست")
        expected = document.get("sha256")
        if expected and store.sha256_file(path) != expected:
            raise ValueError("هش فایل PDF با سند ثبت‌شده نمی‌خواند")
        return path, document

    # ── GET ──────────────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            self._html()
            return
        if path == "/healthz":
            self._json(200, {"ok": True, "service": "review-panel"})
            return
        if not self._token_ok():
            self._json(403, {"error": "توکن نامعتبر"})
            return
        if path in {"/api/reviewers", "/api/session"}:
            session = self._session()
            payload = {
                "authenticated": bool(session),
                "reviewer": ({"reviewerId": session["reviewerId"],
                              "displayName": session["displayName"],
                              "keyId": session["keyId"],
                              "assurance": session["assurance"]} if session else None),
                "reviewers": review_panel.reviewers(),
                "assurance": "local-password-and-encrypted-key",
            }
            self._json(200, payload)
            return
        session = self._require_session()
        if session is None:
            return
        if path == "/api/state":
            try:
                self._json(200, review_panel.queue_state())
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"خطای خواندن صف: {exc}"})
            return
        if path == "/api/audit":
            try:
                self._json(200, review_panel.history())
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"خطای تاریخچه: {exc}"})
            return
        if path == "/api/pdf":
            qs = parse_qs(parsed.query)
            rev_id = (qs.get("revision") or [""])[0]
            try:
                pdf, document = self._pdf_path(rev_id)
                page = int((qs.get("page") or ["1"])[0])
                pages = int(document.get("pages") or 0)
                if page < 1 or (pages and page > pages):
                    raise ValueError("شمارهٔ صفحه بیرون از سند است")
            except PermissionError as exc:
                self._json(403, {"error": str(exc)})
                return
            except (ValueError, FileNotFoundError) as exc:
                self._json(404, {"error": str(exc)})
                return
            data = pdf.read_bytes()
            self._send(200, data, "application/pdf", {
                "Content-Disposition": f'inline; filename="{pdf.name}"',
                "X-Frame-Options": "SAMEORIGIN",
                "Content-Security-Policy": "default-src 'none'",
            })
            return
        self._json(404, {"error": "not found"})

    # ── POST ─────────────────────────────────────────────────────────────
    def do_POST(self) -> None:  # noqa: N802
        if not self._require_post():
            return
        path = urlparse(self.path).path
        if path == "/api/login":
            self._login()
            return
        if path == "/api/logout":
            session = self._session()
            if session:
                SESSIONS.pop(self.headers.get("X-Review-Session", ""), None)
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get("Cookie", ""))
                    raw = cookie.get("review_session")
                    if raw:
                        SESSIONS.pop(raw.value, None)
                except Exception:  # noqa: BLE001
                    pass
            self._json(200, {"ok": True}, {"Set-Cookie":
                       "review_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            return
        session = self._require_session()
        if session is None:
            return
        if path == "/api/upload":
            self._upload()
            return
        try:
            body = self._read_json()
            if path == "/api/decide":
                self._json(200, review_panel.decide(session, body))
            elif path == "/api/year-approval":
                self._json(200, review_panel.year_approval(session, body))
            elif path == "/api/reject":
                self._json(200, review_panel.reject_revision(session, body))
            elif path == "/api/revert":
                self._json(200, review_panel.revert(session, body))
            else:
                self._json(404, {"error": "not found"})
        except review_panel.PanelError as exc:
            self._json(400, {"error": str(exc)})
        except (ValueError, FileNotFoundError, KeyError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": f"خطای داخلی: {exc}"})

    def _login(self) -> None:
        client = self.client_address[0] if self.client_address else "?"
        now = time.time()
        fails = [t for t in LOGIN_FAILS.get(client, []) if now - t < 300]
        LOGIN_FAILS[client] = fails
        if len(fails) >= 8:
            self._json(429, {"error": "تلاش‌های ناموفق زیاد است؛ چند دقیقه صبر کنید"})
            return
        try:
            body = self._read_json()
            session = reviewer_auth.authenticate(
                str(body.get("reviewer") or ""), str(body.get("password") or ""))
        except (ValueError, KeyError) as exc:
            fails.append(now)
            LOGIN_FAILS[client] = fails
            self._json(401, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            fails.append(now)
            LOGIN_FAILS[client] = fails
            self._json(401, {"error": f"ورود ناموفق: {exc}"})
            return
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {
            **session,
            "expires": now + SESSION_TTL,
            "createdAt": now,
            "lastSeen": now,
        }
        self._json(200, {
            "ok": True,
            "reviewer": {"reviewerId": session["reviewerId"],
                         "displayName": session["displayName"],
                         "keyId": session["keyId"],
                         "assurance": session["assurance"]},
        }, {"Set-Cookie": (
            f"review_session={token}; HttpOnly; SameSite=Strict; Path=/; "
            f"Max-Age={SESSION_TTL}")})

    def _upload(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json(400, {"error": "بدنهٔ نامعتبر"})
            return
        raw = self.rfile.read(length)
        try:
            fields = parse_multipart(raw, self.headers.get("Content-Type", ""))
            if "file" not in fields or not fields["file"][0]:
                raise ValueError("فیلدِ file لازم است")
            filename, data = fields["file"]
            year_raw = (fields.get("year", (None, b""))[1] or b"").decode("utf-8", "replace").strip()
            year = int(year_raw) if year_raw else None
            if year is not None and not 1300 <= year <= 1420:
                raise ValueError("سال باید بین ۱۳۰۰ و ۱۴۲۰ باشد")
            ocr = (fields.get("ocr", (None, b""))[1] or b"").decode() in {"1", "true", "on"}
            stored = save_upload(filename, data)
            bundle = ingest_pdf.write_bundle(stored, year, do_ocr=ocr,
                                             original_name=filename)
            rev = bundle["revision"]
            self._json(200, {"ok": True, "revisionId": rev["id"], "year": rev["year"],
                             "rows": len(bundle["rawRows"]),
                             "method": rev["extraction"]["method"],
                             "diff": bundle["diff"]["counts"]})
        except (ValueError, FileNotFoundError, KeyError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": f"خطای داخلی: {exc}"})


def main() -> int:
    ap = argparse.ArgumentParser(description="سرورِ محلیِ پنلِ بازبینیِ انسانی")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    port = server.server_address[1]
    if not args.quiet:
        print(f"پنل بازبینی: http://127.0.0.1:{port}/  (فقط همین رایانه)")
        print("ورود با حساب محلیِ بازبین؛ بدون ورود، صف نمایش داده نمی‌شود.")
        print("ثبت حساب: py -3 scripts/reviewer_auth.py register --id reviewer-1 --name \"نام\"")
        print("پایان: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nبسته شد.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
