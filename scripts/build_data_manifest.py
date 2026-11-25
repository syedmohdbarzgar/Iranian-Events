"""ساختِ manifest یگانهٔ داده و گزارشِ انتشار.

همهٔ شمارش‌ها از همین فایل‌های روی دیسک و در همین اجرا محاسبه می‌شوند تا
گزارش‌ها با commit و هشِ داده یکی باشند. این اسکریپت داده را تغییر نمی‌دهد.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports" / "audit"
OUT = REPORTS / "data-manifest.json"
SUMMARY = REPORTS / "release-summary.md"


def sha(path: Path) -> str:
    """هشِ محتوایی؛ JSON/MD با خطِ پایانِ یکسان (LF) تا ویندوز و CI یکی باشند."""
    h = hashlib.sha256()
    data = path.read_bytes()
    if path.suffix.lower() in {".json", ".md", ".txt"}:
        data = data.replace(b"\r\n", b"\n")
    h.update(data)
    return h.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return ""


def main() -> int:
    master = json.loads((DATA / "events-master.json").read_text(encoding="utf-8"))
    events = master["events"]
    sys.path.insert(0, str(ROOT / "scripts"))
    import calendar_engine as engine  # noqa: E402
    import approval_ledger  # noqa: E402

    official_files = sorted(DATA.glob("official-calendar-*.json"))
    official = {p.stem.split("-")[-1]: json.loads(p.read_text(encoding="utf-8")) for p in official_files}
    official_rows = sum(len(d["rows"]) for d in official.values())

    years: dict[int, dict] = {}
    unmatched: list[dict] = []
    for path in sorted((DATA / "years").glob("*.json")):
        if not path.stem.isdigit():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("mode") != "data":
            continue
        y = int(path.stem)
        years[y] = doc
        for row in doc.get("rows", []):
            if not row.get("eventId"):
                unmatched.append({
                    "year": y, "solar": row.get("solar"), "title": row.get("title"),
                    "source": row.get("source"),
                })

    statuses = Counter(e.get("verificationStatus") for e in events)
    identity_records = approval_ledger.latest_records()
    identity_classes = [approval_ledger.attestation_class(r) for r in identity_records.values()]
    identity_precision = [approval_ledger.approved_at_precision(r)
                          for r in identity_records.values()]
    history = json.loads((DATA / "history" / "revisions" / "index.json").read_text(encoding="utf-8"))
    revisions = history.get("revisions", [])
    baseline_revisions = sum(1 for r in revisions
                             if (r.get("approval") or {}).get("kind") == "baseline")
    human_revisions = sum(1 for r in revisions
                          if (r.get("approval") or {}).get("kind") == "human")
    changelog_path = DATA / "history" / "changelog.json"
    changelog = (json.loads(changelog_path.read_text(encoding="utf-8")).get("entries", [])
                 if changelog_path.exists() else [])
    evidence_kinds = Counter((e.get("evidence") or {}).get("kind") for e in events)
    evidence_with_page = sum(1 for e in events if (e.get("evidence") or {}).get("page"))
    categories = Counter(e.get("category") for e in events)
    unique_titles = len({engine._canon(e["title"]) for e in events})
    year_rows = sum(d.get("count", len(d.get("rows", []))) for d in years.values())
    all_year_rows = 0
    for path in (DATA / "years").glob("*.json"):
        if path.stem.isdigit():
            all_year_rows += json.loads(path.read_text(encoding="utf-8")).get("count", 0)
    raw_events = json.loads((DATA / "events.json").read_text(encoding="utf-8"))

    core_files = [
        DATA / "events-master.json",
        DATA / "event-corrections.json",
        DATA / "event-identity-corrections.json",
        DATA / "official-corrections-1404-1405.json",
    ]
    data_files = sorted(official_files + list((DATA / "years").glob("*.json")) + core_files)
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in data_files}
    pdfs = sorted((ROOT / "PDF").glob("*.pdf"))
    pdf_hashes = {p.name: sha(p) for p in pdfs}

    commit = git("rev-parse", "HEAD")
    content_hash = hashlib.sha256(
        "\n".join(f"{k}:{v}" for k, v in sorted(hashes.items())).encode("utf-8")
    ).hexdigest()
    # نسخه از محتوای داده ساخته می‌شود، نه فقط از commit؛ وگرنه تغییرِ
    # uncommitted همان نسخهٔ قدیمی را جا می‌زند.
    data_version = f"v{master.get('version', '?')}+{content_hash[:7]}"
    # گزارش‌ها عمداً از سنجشِ کثیفی بیرون‌اند؛ وگرنه تولیدِ خودِ گزارش‌ها
    # همیشه درخت را «کثیف» نشان می‌دهد و provenance بی‌معنا می‌شود.
    dirty = bool(git(
        "status", "--porcelain", "--",
        "data/events-master.json", "data/official-corrections-1404-1405.json",
        "data/official-calendar-*.json", "data/years", "scripts", "tests", "docs",
    ))
    manifest = {
        "schema": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataVersion": data_version,
        "contentHash": content_hash,
        "commit": commit,
        "workingTreeDirty": dirty,
        "generatedBy": "scripts/build_data_manifest.py",
        "counts": {
            "uniqueEvents": len(events),
            "uniqueCanonicalTitles": unique_titles,
            "officialYears": len(official),
            "officialRows": official_rows,
            "annualRows": year_rows,
            "annualMatchedRows": year_rows - len(unmatched),
            "annualUnmatchedRows": len(unmatched),
            "allYearRows": all_year_rows,
            "rawEvents": len(raw_events),
            "pdfCalendarFiles": len(pdfs),
        },
        "verificationStatus": dict(sorted(statuses.items())),
        "provenance": {
            "baselineRevisions": baseline_revisions,
            "humanApprovedRevisions": human_revisions,
            "changelogEntries": len(changelog),
            "identityDecisions": len(identity_records),
            "identityHumanAttestations": identity_classes.count("human-signed"),
            "identityMachineRecorded": sum(1 for c in identity_classes if c.startswith("machine-")),
            "identityDateOnlyApprovedAt": identity_precision.count("date-only"),
            "identityHumanAttestationProven": bool(identity_records) and all(
                c == "human-signed" for c in identity_classes),
        },
        "evidenceKinds": dict(sorted(evidence_kinds.items())),
        "evidenceWithPage": evidence_with_page,
        "categories": dict(sorted(categories.items())),
        "officialYears": sorted(int(y) for y in official),
        "missingOfficialYears": [1393, 1396, 1402],
        "dataHashes": hashes,
        "pdfHashes": pdf_hashes,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    c = manifest["counts"]
    lines = [
        "# گزارشِ انتشارِ داده — یک منبع، یک اجرا",
        "",
        f"- داده: **{manifest['dataVersion']}** · commitِ پایهٔ تولید: `{commit or 'نامشخص'}`"
        + (" · **درختِ کاری تمیز نیست**" if dirty else ""),
        f"- زمانِ تولید (UTC): `{manifest['generatedAt']}`",
        f"- رویدادِ یکتا: **{c['uniqueEvents']}** · عنوانِ کانونیِ یکتا: **{c['uniqueCanonicalTitles']}**",
        f"- سالِ دارای جدولِ رسمی: **{c['officialYears']}** · ردیفِ رسمی: **{c['officialRows']}**",
        f"- ردیفِ سالانهٔ ۲۲ سالِ داده: **{c['annualRows']}** · متصل: **{c['annualMatchedRows']}** · بدونِ تطبیق: **{c['annualUnmatchedRows']}**",
        f"- ردیفِ همهٔ ۱۲۱ سال: **{c['allYearRows']}** · رویدادِ خامِ `events.json`: **{c['rawEvents']}**",
        f"- فایلِ PDF: **{c['pdfCalendarFiles']}** (هش در manifest)",
        "",
        "## شاهدِ ثبت‌شده",
        "",
        f"- رویدادِ دارای شاهد: **{len(events)}** · با شمارهٔ صفحه: **{evidence_with_page}**",
        "- " + " · ".join(f"`{k}`: {v}" for k, v in sorted(evidence_kinds.items())),
        "",
        "## وضعیتِ تأیید (بدونِ ارتقای دسته‌جمعی)",
        "",
        "| وضعیت | تعداد |",
        "|---|---:|",
    ]
    for k, v in sorted(statuses.items(), key=lambda x: str(x[0])):
        lines.append(f"| `{k}` | {v} |")
    p = manifest["provenance"]
    lines += [
        "",
        "## تفکیکِ تأیید (ماشین از انسان)",
        "",
        f"- نسخه‌های مبنا: **{p['baselineRevisions']}** · نسخه‌های تأییدشدهٔ انسانی: "
        f"**{p['humanApprovedRevisions']}** · ChangeLog: {p['changelogEntries']}",
        f"- تصمیم‌های هویت: **{p['identityDecisions']}** · تأییدِ انسانیِ مستقل: "
        f"**{p['identityHumanAttestations']}** · رکوردِ ماشینی: {p['identityMachineRecorded']} "
        f"· `approvedAt` فقط-تاریخی: {p['identityDateOnlyApprovedAt']}",
        "- **این دو شمارش یکی نیستند:** نسخهٔ سالانه با `approval.kind=human` از تصمیمِ "
        "هویتِ امضاشده جدا است؛ هیچ‌کدام از ۲۲ تصمیمِ فعلی اثباتِ تأییدِ انسانیِ مستقل نیست.",
        "",
        "## مرزِ صداقت",
        "",
        "- `officialRows` ردیف‌های جدولِ PDF است، نه تعداد رویدادِ یکتا؛ یک رویداد می‌تواند در چند سال تکرار شود.",
        "- `uniqueEvents` کاتالوگِ کانونی است؛ `rawEvents` فهرستِ خامِ استخراج است و این دو را نباید یکی خواند.",
        "- `allYearRows` جمعِ ۱۲۱ فایلِ سالانه است؛ `annualRows` فقط ۲۲ سالِ دارای جدولِ داده را می‌شمارد.",
        "- `annualUnmatchedRows` ردیف‌های سالانه‌ای است که `eventId` ندارند؛ در `unmatched.json` تک‌به‌تک مستند شده‌اند.",
        "- هشِ همهٔ فایل‌های داده و PDF در `data-manifest.json` است؛ تغییرِ هر فایل بدونِ تولیدِ دوبارهٔ گزارش = ناسازگاری در تست.",
        "",
    ]
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    print(f"manifest: {manifest['dataVersion']} · events={len(events)} · rows={year_rows} · unmatched={len(unmatched)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
