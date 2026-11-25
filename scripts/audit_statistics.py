#!/usr/bin/env python3
"""P1-05: تطبیقِ آمارِ گزارش‌ها با دادهٔ واقعی و نسخه‌های منتشرشده."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402

OUT_MD = ROOT / "reports" / "statistics-audit.md"
OUT_JSON = ROOT / "reports" / "statistics-audit.json"


def main() -> int:
    history = store.load_history()
    active = store.active_revisions(history["revisions"])
    reviews = store.load_identity_review_entries()
    approved = sum(1 for r in reviews if store.approval_ledger.is_approved(r))
    actual = {
        "events": len(history["events"]),
        "occurrences": len(history["occurrences"]),
        "witnessedEvents": sum(1 for e in history["events"] if e.get("observedYears")),
        "needsReview": sum(1 for e in history["events"] if e.get("needsReview")),
        "reviewedIdentities": sum(1 for e in history["events"] if e.get("review")),
        "revisions": len(history["revisions"]),
        "activeRevisions": len(active),
        "documentYears": sorted(active),
        "changelog": len(history["changelog"]),
        "identityReviews": len(reviews),
        "approvedIdentityReviews": approved,
    }
    issues: list[dict] = []
    audit_path = ROOT / "reports" / "history-audit.json"
    if not audit_path.exists():
        issues.append({"code": "STATS_AUDIT_MISSING", "message": "history-audit.json نیست"})
    else:
        coverage = json.loads(audit_path.read_text(encoding="utf-8")).get("coverage", {})
        for key in ("events", "occurrences", "witnessedEvents", "needsReview",
                    "reviewedIdentities", "revisions", "activeRevisions",
                    "documentYears", "changelog"):
            if coverage.get(key) != actual[key]:
                issues.append({"code": "STATS_AUDIT_MISMATCH",
                               "message": f"history-audit.{key}={coverage.get(key)} ≠ {actual[key]}"})

    history_md = ROOT / "reports" / "history.md"
    text = history_md.read_text(encoding="utf-8") if history_md.exists() else ""
    m = re.search(r"هویت‌ها: \*\*(\d+)\*\* · دارای وقوعِ مستند: \*\*(\d+)\*\* · بدونِ هیچ سند: (\d+)", text)
    if not m:
        issues.append({"code": "STATS_HISTORY_MD_MISSING", "message": "اعدادِ سرصفحهٔ history.md خوانده نشد"})
    else:
        got = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        want = (actual["events"], actual["witnessedEvents"],
                actual["events"] - actual["witnessedEvents"])
        if got != want:
            issues.append({"code": "STATS_HISTORY_MD_MISMATCH",
                           "message": f"history.md {got} ≠ {want}"})
    m = re.search(r"وقوع‌های سالانه: \*\*(\d+)\*\* در (\d+) سند", text)
    if not m:
        issues.append({"code": "STATS_HISTORY_MD_OCCURRENCES", "message": "شمارِ وقوع در history.md نیست"})
    elif (int(m.group(1)), int(m.group(2))) != (actual["occurrences"], len(actual["documentYears"])):
        issues.append({"code": "STATS_HISTORY_MD_OCCURRENCES",
                       "message": f"history.md وقوع/سند ≠ {actual['occurrences']}/{len(actual['documentYears'])}"})

    # دفترِ تأیید: تعداد تصمیم‌های معتبر باید با فایلِ مشتق‌شده یکی باشد.
    if actual["approvedIdentityReviews"] != sum(1 for r in reviews if r.get("active")):
        issues.append({"code": "STATS_APPROVAL_COUNT",
                       "message": "تعداد تأییدهای معتبر با active در identity-reviews یکی نیست"})

    payload = {"generatedAt": store.now_iso(), "actual": actual,
               "issues": issues,
               "gate": "pass" if not issues else "fail"}
    store.write_json(OUT_JSON, payload)
    lines = ["# تطبیقِ آمارِ گزارش‌ها", "",
             f"**نتیجه: {'سبز' if not issues else 'قرمز'}**", "",
             "| سنجه | مقدار داده |", "|---|---|"]
    for key, value in actual.items():
        lines.append(f"| {key} | {value} |")
    if issues:
        lines += ["", "## مغایرت‌ها", ""] + [f"- `{i['code']}`: {i['message']}" for i in issues]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"statistics gate={'PASS' if not issues else 'FAIL'} issues={len(issues)} "
          f"events={actual['events']} occurrences={actual['occurrences']}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
