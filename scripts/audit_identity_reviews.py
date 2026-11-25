#!/usr/bin/env python3
"""P1-03: بازبینیِ مستقلِ ۲۲ تصمیم هویت در برابر ردیف‌های واقعیِ PDF.

هر تصمیم باید: امضای معتبر، شاهدِ صفحه/نسخهٔ موجود، ردیفِ قابلِ ردیابی، و برای
``map`` مقصدِ کاتالوگیِ موجود داشته باشد. تطبیقِ متنی ضعیف هشدار است، نه ادغام.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import approval_ledger  # noqa: E402
import history_store as store  # noqa: E402

OUT_MD = ROOT / "reports" / "identity-review-audit.md"
OUT_JSON = ROOT / "reports" / "identity-review-audit.json"
STOP = {"روز", "و", "به", "از", "در", "با", "برای", "های", "ها", "ش", "ه", "ق"}


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[آ-یءأإؤئ]{3,}", text or "") if w not in STOP}


def overlap(a: str, b: str) -> int:
    return len(words(a) & words(b))


def main() -> int:
    history = store.load_history()
    by_id = {e["id"]: e for e in history["events"]}
    catalog = {e["id"]: e for e in store.master_catalog()}
    revisions = {r["id"]: r for r in history["revisions"]}
    reviews = store.load_identity_review_entries()
    ledger = approval_ledger.latest_records()
    issues: list[dict] = []
    rows_out: list[dict] = []

    for entry in reviews:
        eid = entry.get("eventId", "")
        evidence_ok = 0
        for ev in entry.get("evidence") or []:
            rev = revisions.get(ev.get("revisionId"))
            if not rev:
                issues.append({"code": "EVIDENCE_REVISION", "ref": eid,
                               "message": f"نسخهٔ {ev.get('revisionId')} نیست"})
                continue
            rows = store.load_revision_rows(rev)
            same_page = [r for r in rows if r.get("page") == ev.get("page")]
            title = ev.get("observedTitle", "")
            hit = [r for r in same_page if store.identity_key(r.get("title", "")) == store.identity_key(title)]
            if not hit:
                hit = [r for r in same_page if overlap(r.get("title", ""), title) >= 2]
            if hit:
                evidence_ok += 1
            else:
                issues.append({"code": "EVIDENCE_ROW", "ref": eid,
                               "message": f"ردیفِ شاهد در {rev['id']} صفحهٔ {ev.get('page')} پیدا نشد"})
        if not evidence_ok:
            issues.append({"code": "EVIDENCE_NONE", "ref": eid,
                           "message": "هیچ شاهدِ ردیفیِ قابلِ ردیابی ندارد"})
        if approval_ledger.verify_entry(entry):
            issues.extend(approval_ledger.verify_entry(entry))

        # مستقل از فیلدهای متصل، خودِ رکورد دفتر را تطبیق بده؛ وگرنه یک
        # approval کپی‌شده با فیلدهای هم‌شکل می‌تواند بی‌سروصدا از زنجیره جدا شود.
        approval = entry.get("approval") or {}
        record = ledger.get(eid)
        if record is None:
            issues.append({"code": "APPROVAL_LEDGER_MISSING", "ref": eid,
                           "message": "رکورد فعالی در دفتر تأیید برای این تصمیم نیست"})
        else:
            links = {
                "ledgerSeq": (approval.get("ledgerSeq"), record.get("seq")),
                "recordHash": (approval.get("recordHash"), record.get("recordHash")),
                "by": (approval.get("by"), record.get("approver")),
                "at": (approval.get("at"), record.get("approvedAt")),
                "statementSha256": (approval.get("statementSha256"), record.get("statementSha256")),
                "recordedBy": (approval.get("recordedBy"), record.get("recordedBy")),
                "attestation": (approval.get("attestation"), record.get("attestation")),
            }
            for field, (attached, ledger_value) in links.items():
                if attached != ledger_value:
                    issues.append({"code": "APPROVAL_LEDGER_LINK", "ref": eid,
                                   "message": f"فیلد {field} با رکورد دفتر نمی‌خواند"})
            if record.get("action") != "approve":
                issues.append({"code": "APPROVAL_LEDGER_ACTION", "ref": eid,
                               "message": "آخرین رکورد دفتر approve نیست"})
            if not record.get("recordedBy"):
                issues.append({"code": "APPROVAL_RECORDER_UNDECLARED", "ref": eid,
                               "message": "ثبت‌کنندهٔ رکورد اعلام نشده است"})
            if not record.get("attestation"):
                issues.append({"code": "APPROVAL_ATTESTATION_MISSING", "ref": eid,
                               "message": "نوع شاهدِ تأیید (attestation) اعلام نشده است"})
        if not str(entry.get("reviewedBy", "")).startswith("proposal:"):
            issues.append({"code": "REVIEW_PROPOSAL_ORIGIN", "ref": eid,
                           "message": "منشأ reviewedBy باید proposal باشد، نه ادعای انسان"})

        if entry.get("decision") == "map":
            target = catalog.get(entry.get("target"))
            if not target:
                issues.append({"code": "TARGET_MISSING", "ref": eid,
                               "message": f"مقصد {entry.get('target')} در کاتالوگ نیست"})
            else:
                score = max((overlap(ev.get("observedTitle", ""), target["title"])
                             for ev in entry.get("evidence") or []), default=0)
                if score < 2:
                    issues.append({"code": "TARGET_WEAK_MATCH", "ref": eid,
                                   "message": f"هم‌پوشانیِ متنی با {target['id']} کم است ({score})"})
                if eid in by_id:
                    issues.append({"code": "MAPPED_SOURCE_STILL_PRESENT", "ref": eid,
                                   "message": "هویتِ مپ‌شده هنوز در داده هست"})
        else:
            if eid not in by_id:
                issues.append({"code": "KEEP_EVENT_MISSING", "ref": eid,
                               "message": "هویتِ حفظ‌شده در داده نیست"})
            for c in entry.get("constituents") or []:
                if c.get("id") not in catalog:
                    issues.append({"code": "CONSTITUENT_MISSING", "ref": eid,
                                   "message": f"جزء {c.get('id')} در کاتالوگ نیست"})
        rows_out.append({"eventId": eid, "decision": entry.get("decision"),
                         "target": entry.get("target"),
                         "evidenceRows": evidence_ok,
                         "constituents": len(entry.get("constituents") or []),
                         "approved": approval_ledger.is_approved(entry),
                         "ledgerSeq": approval.get("ledgerSeq"),
                         "approvedAt": approval.get("at"),
                         "recordedBy": approval.get("recordedBy"),
                         "attestation": approval.get("attestation")})

    errors = [i for i in issues if i["code"] in {
        "EVIDENCE_REVISION", "EVIDENCE_ROW", "EVIDENCE_NONE", "TARGET_MISSING",
        "MAPPED_SOURCE_STILL_PRESENT", "KEEP_EVENT_MISSING", "CONSTITUENT_MISSING",
        "REVIEW_APPROVAL_MISSING", "REVIEW_APPROVAL_UNSIGNED", "APPROVAL_SIGNATURE",
        "APPROVAL_STATEMENT_MISMATCH", "APPROVAL_KEY_UNTRUSTED", "APPROVAL_LEDGER_MISSING",
        "APPROVAL_LEDGER_LINK", "APPROVAL_LEDGER_ACTION", "APPROVAL_RECORDER_UNDECLARED",
        "APPROVAL_ATTESTATION_MISSING", "REVIEW_PROPOSAL_ORIGIN"}]
    payload = {"generatedAt": store.now_iso(), "reviews": rows_out, "issues": issues,
               "errors": len(errors), "gate": "pass" if not errors else "fail"}
    store.write_json(OUT_JSON, payload)
    lines = ["# ممیزیِ مستقلِ تصمیم‌های هویت", "",
             f"**نتیجه: {'سبز' if not errors else 'قرمز'}** · {len(rows_out)} تصمیم · "
             f"{sum(1 for r in rows_out if r['approved'])} رکوردِ امضاشده", "",
             "**مرزِ ادعا:** این رکوردها تأیید صریح کاربر در چت را ثبت می‌کنند؛ "
             "`recordedBy` عاملِ ثبت‌کننده را نشان می‌دهد و امضای Ed25519 فقط یکپارچگی "
             "است، نه امضای شخصیِ انسان. زمان دقیق چت ثبت نشده و `approvedAt` فقط تاریخ است.",
             "",
             "| هویت | تصمیم | مقصد | شاهدِ ردیفی | اجزا | تأیید |",
             "|---|---|---|---|---|---|"]
    for r in rows_out:
        lines.append(f"| `{r['eventId']}` | {r['decision']} | {r['target'] or '—'} | "
                     f"{r['evidenceRows']} | {r['constituents']} | {'✓' if r['approved'] else '—'} |")
    lines += ["", "## منشأ تأیید (از دفتر)", "",
              "| هویت | seq | ثبت‌کننده | attestation | approvedAt |",
              "|---|---|---|---|---|"]
    for r in rows_out:
        lines.append(f"| `{r['eventId']}` | {r['ledgerSeq'] or '—'} | "
                     f"{r['recordedBy'] or '—'} | {r['attestation'] or '—'} | "
                     f"{r['approvedAt'] or '—'} |")
    lines += ["", "## دامنهٔ بررسی", "",
              "- بررسی‌شده: وجود ردیف شاهد، صفحه/نسخه، مقصد کاتالوگی، امضا، "
              "اتصال فیلدهای approval به آخرین رکورد دفتر، ثبت‌کننده و attestation.",
              "- بررسی‌نشده: درستی تاریخی/معنایی ادعای انسان و هویت شخصیِ امضاکننده؛ "
              "این دو به شاهد بیرونی و امضای شخصیِ انسان نیاز دارند."]
    if issues:
        lines += ["", "## اشکال/هشدار", ""] + [f"- `{i['code']}` ({i['ref']}): {i['message']}" for i in issues]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"identity audit gate={'PASS' if not errors else 'FAIL'} reviews={len(rows_out)} "
          f"errors={len(errors)} warnings={len(issues) - len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
