"""گیتِ تاریخِ رویداد (فاز ۶ و ۷ چک‌لیست).

سه سنجهٔ مستقل:

1. **اعتبارسنجیِ ساختاری** — هر وقوع شاهد، نسخه، صفحه و سالِ درست دارد.
2. **بازتولید** — وقوع‌ها/هویت‌ها از نسخه‌های تأییدشده دوباره ساخته و با فایل
   مقایسه می‌شوند؛ هر دست‌کاریِ دستی یا دادهٔ تأییدنشده آشکار می‌شود.
3. **هشِ سند** — هشِ SHA-256 هر نسخه با PDF موجود در ``PDF/`` می‌خواند.

خروجِ غیرصفر = توقفِ انتشار. گزارش: ``reports/history-audit.{md,json}``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import approval_ledger  # noqa: E402
import history_store as store  # noqa: E402
import calendar_engine as engine  # noqa: E402

PDF_DIR = ROOT / "PDF"
REPORT_MD = ROOT / "reports" / "history-audit.md"
REPORT_JSON = ROOT / "reports" / "history-audit.json"
IDENTITY_REPORT = ROOT / "reports" / "history-identity-review.md"


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def date_issues(occurrences: list[dict]) -> list[dict]:
    out = []
    for occ in occurrences:
        solar = occ["date"]["solar"]
        greg = occ["date"]["gregorian"]
        if not solar or len(solar) != 3 or None in solar:
            out.append(store._issue("OCC_DATE_INVALID", "error", "تاریخِ شمسیِ ناقص", occ["id"]))
            continue
        y, m, d = solar
        if not (1 <= m <= 12 and 1 <= d <= engine.month_len(y, m)):
            out.append(store._issue("OCC_DATE_INVALID", "error", f"تاریخِ نامعتبر {y}-{m}-{d}", occ["id"]))
        if greg and len(greg) == 3 and None not in greg:
            try:
                py = date(*greg)
            except ValueError:
                out.append(store._issue("OCC_GREGORIAN_INVALID", "error", f"میلادیِ نامعتبر {greg}", occ["id"]))
                continue
            if engine.gregorian_to_jalali(py.year, py.month, py.day) != (y, m, d):
                out.append(store._issue("OCC_DATE_CONVERSION", "error",
                                        f"شمسی {solar} با میلادی {greg} نمی‌خواند", occ["id"]))
    return out


def coverage(history: dict) -> dict:
    active = store.active_revisions(history["revisions"])
    years = sorted(active)
    events = history["events"]
    witnessed = [e for e in events if e.get("observedYears")]
    by_year = {}
    for y in years:
        by_year[y] = sum(1 for o in history["occurrences"] if o["year"] == y)
    identity_records = approval_ledger.latest_records()
    identity_classes = [approval_ledger.attestation_class(r) for r in identity_records.values()]
    identity_precision = [approval_ledger.approved_at_precision(r)
                          for r in identity_records.values()]
    return {
        "documentYears": years,
        "events": len(events),
        "witnessedEvents": len(witnessed),
        "unwitnessedEvents": len(events) - len(witnessed),
        "occurrences": len(history["occurrences"]),
        "byYear": by_year,
        "needsReview": sum(1 for e in events if e.get("needsReview")),
        "reviewedIdentities": sum(1 for e in events if e.get("review")),
        "revisions": len(history["revisions"]),
        "activeRevisions": len(active),
        "baselineRevisions": sum(1 for r in active.values()
                                 if (r.get("approval") or {}).get("kind") == "baseline"),
        "humanRevisions": sum(1 for r in active.values()
                              if (r.get("approval") or {}).get("kind") == "human"),
        "changelog": len(history["changelog"]),
        "identityDecisions": len(identity_records),
        "identityHumanAttestations": identity_classes.count("human-signed"),
        "identityMachineAttestations": sum(1 for c in identity_classes
                                           if c.startswith("machine-")),
        "identityDateOnlyApprovedAt": identity_precision.count("date-only"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="گیتِ تاریخِ رویداد")
    ap.add_argument("--no-pdf-hash", action="store_true", help="صرف‌نظر از بررسیِ هشِ PDFها")
    args = ap.parse_args()

    history = store.load_history()
    if not history["events"] or not history["revisions"]:
        print("تاریخ ساخته نشده است؛ ابتدا build_history.py را اجرا کنید.", file=sys.stderr)
        return 1
    expected = store.rebuild_from_revisions()
    issues = store.validate(
        history, expected=expected, pdf_dir=PDF_DIR,
        check_pdf_hashes=not args.no_pdf_hash,
        identity_reviews=store.load_identity_review_entries())
    issues += date_issues(history["occurrences"])
    # زنجیرهٔ دفترِ تأیید هم بخشی از شاهدِ انتشار است، نه فقط امضای تک‌تک ردیف‌ها.
    ledger_entries = approval_ledger.ledger_document()["entries"]
    issues += approval_ledger.verify_ledger(ledger_entries)
    for entry in store.load_identity_review_entries():
        approval = entry.get("approval") or {}
        if approval.get("method") != "ed25519":
            continue
        record = next((r for r in ledger_entries
                       if r.get("seq") == approval.get("ledgerSeq")), None)
        if record is None or record.get("recordHash") != approval.get("recordHash"):
            issues.append(store._issue("REVIEW_LEDGER_MISSING", "error",
                                       "تأیید به رکوردِ معتبرِ دفتر وصل نیست",
                                       entry.get("eventId", "")))
        elif record.get("statementSha256") != approval.get("statementSha256"):
            issues.append(store._issue("REVIEW_LEDGER_STATEMENT", "error",
                                       "هشِ بیانیه با دفتر نمی‌خواند",
                                       entry.get("eventId", "")))

    active = store.active_revisions(history["revisions"])
    for rev in history["revisions"]:
        if rev.get("state") not in {"approved", "superseded", "draft", "reviewed", "rejected"}:
            issues.append(store._issue("REV_STATE_UNKNOWN", "error",
                                       f"وضعیتِ ناشناختهٔ {rev.get('state')}", rev["id"]))
        if rev["id"] not in active and rev.get("state") == "approved":
            # چند نسخهٔ approved برای یک سال: قدیمی‌تر باید superseded شده باشد
            newer = [r for r in history["revisions"] if r["year"] == rev["year"]
                     and r.get("state") == "approved" and r["id"] != rev["id"]]
            if newer:
                issues.append(store._issue("REV_MULTIPLE_ACTIVE", "error",
                                           f"بیش از یک نسخهٔ فعال برای {rev['year']}", rev["id"]))
    for o in history["occurrences"]:
        if not 1300 <= o["year"] <= 1420:
            issues.append(store._issue("OCC_YEAR_RANGE", "error", f"سالِ خارج از بازه: {o['year']}", o["id"]))
        if o.get("match", {}).get("confidence", 1) < 0.5:
            issues.append(store._issue("OCC_LOW_CONFIDENCE", "warning",
                                       "تطبیقِ هویت با اطمینانِ پایین", o["id"]))
    drafts = [r for r in history["revisions"] if r.get("state") == "draft"]
    for rev in drafts:
        if any(o.get("evidence", {}).get("revisionId") == rev["id"] for o in history["occurrences"]):
            issues.append(store._issue("DRAFT_IN_CANONICAL", "error",
                                       "دادهٔ پیش‌نویس در تاریخچه راه یافته", rev["id"]))

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    cov = coverage(history)
    report = {
        "generatedAt": store.now_iso(),
        "gate": "pass" if not errors else "fail",
        "coverage": cov,
        "issues": issues,
        "summary": store.summarize_issues(issues),
        "rule": "هیچ وقوعی بدونِ شاهدِ نسخهٔ تأییدشده در تاریخچه نیست.",
    }
    store.write_json(REPORT_JSON, report)

    lines = [
        "# گیتِ تاریخِ رویداد",
        "",
        f"**نتیجه: {'سبز' if not errors else 'قرمز'}** · {report['generatedAt']}",
        "",
        f"- سال‌های دارای نسخهٔ فعال: **{len(cov['documentYears'])}** "
        f"({cov['documentYears'][0]}–{cov['documentYears'][-1]})" if cov["documentYears"] else "- سالی ندارد",
        f"- هویت‌ها: **{cov['events']}** · با وقوع: {cov['witnessedEvents']} · بدونِ وقوع: {cov['unwitnessedEvents']}",
        f"- وقوع‌ها: **{cov['occurrences']}**",
        f"- هویت‌های نیازمندِ بازبینی: {cov['needsReview']} · بازبینیِ مستندشده: {cov['reviewedIdentities']}",
        f"- نسخه‌ها: {cov['revisions']} ({cov['activeRevisions']} فعال؛ "
        f"مبنای خودکار: {cov['baselineRevisions']}، تأییدِ انسانی: {cov['humanRevisions']}) · ChangeLog: {cov['changelog']}",
        f"- تصمیم‌های هویت: **{cov['identityDecisions']}** · تأییدِ انسانیِ مستقل: "
        f"**{cov['identityHumanAttestations']}** · رکوردِ ماشینی: {cov['identityMachineAttestations']} "
        f"· زمانِ فقط-تاریخی: {cov['identityDateOnlyApprovedAt']}",
        f"- خطا: **{len(errors)}** · هشدار: {len(warnings)}",
        "",
        "## پوششِ سالانه",
        "",
        "| سال | سند | وقوع |",
        "|---|---|---|",
    ]
    for y in cov["documentYears"]:
        rev = active[y]
        lines.append(f"| {y} | {rev['document']['file']} | {cov['byYear'].get(y, 0)} |")
    if issues:
        lines += ["", "## اشکال‌ها", ""]
        for issue in issues[:300]:
            lines.append(f"- `{issue['code']}` ({issue['severity']}): {issue['message']}"
                         + (f" — `{issue['ref']}`" if issue.get("ref") else ""))
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    reviews = store.load_identity_review_entries()
    review_lines = [
        "# بازبینیِ هویت‌های ردیفی — شاهد و علت",
        "",
        f"**{len(reviews)} تصمیمِ ثبت‌شده · {sum(1 for r in reviews if r.get('active'))} فعال** "
        "· منبع تصمیم: `data/history/identity-reviews.json` "
        "· دفتر تأیید: `data/history/approvals/identity-approvals.json`",
        f"**کلاسِ شاهد:** {cov['identityHumanAttestations']} تأییدِ انسانیِ مستقل · "
        f"{cov['identityMachineAttestations']} رکوردِ ماشینی · "
        f"{cov['identityDateOnlyApprovedAt']} زمانِ فقط-تاریخی. «فعال» یعنی امضای معتبر دارد، "
        "نه اینکه انسان شخصاً امضا کرده باشد.",
        "",
        "| هویت | تصمیم | مقصد | شاهدِ صفحه | اجزای کاتالوگی | علت | تأیید/بازبین | امضا | ثبت‌کننده |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in reviews:
        evidence = ", ".join(
            f"{ev.get('revisionId')}#p{ev.get('page')} ({ev.get('year')})"
            for ev in entry.get("evidence", []))
        parts = ", ".join(f"{c.get('id')} {c.get('title', '')[:60]}"
                         for c in entry.get("constituents", [])) or "—"
        review_lines.append(
            f"| `{entry.get('eventId')}` | {entry.get('decision')} | "
            f"{entry.get('target') or '—'} | {_cell(evidence) or '—'} | "
            f"{_cell(parts)} | {_cell(entry.get('reason', ''))} | "
            f"{_cell((entry.get('approval') or {}).get('kind', ''))}: "
            f"{_cell((entry.get('approval') or {}).get('by', ''))} | "
            f"`{(entry.get('approval') or {}).get('keyId', '—')}` "
            f"#{entry.get('approval', {}).get('ledgerSeq', '—')} | "
            f"{_cell((entry.get('approval') or {}).get('recordedBy', '—'))} |")
    IDENTITY_REPORT.write_text("\n".join(review_lines) + "\n", encoding="utf-8")

    print(f"gate={'PASS' if not errors else 'FAIL'} errors={len(errors)} warnings={len(warnings)} "
          f"events={cov['events']} occurrences={cov['occurrences']} years={len(cov['documentYears'])}")
    for issue in errors[:12]:
        print("  !", issue["code"], issue["message"])
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
