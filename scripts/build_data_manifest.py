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
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
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
    categories = Counter(e.get("category") for e in events)
    unique_titles = len({engine._canon(e["title"]) for e in events})
    year_rows = sum(d.get("count", len(d.get("rows", []))) for d in years.values())

    core_files = [
        DATA / "events-master.json",
        DATA / "official-corrections-1404-1405.json",
    ]
    data_files = sorted(official_files + list((DATA / "years").glob("*.json")) + core_files)
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in data_files}
    pdfs = sorted((ROOT / "PDF").glob("*.pdf"))
    pdf_hashes = {p.name: sha(p) for p in pdfs}

    commit = git("rev-parse", "HEAD")
    # گزارش‌ها عمداً از سنجشِ کثیفی بیرون‌اند؛ وگرنه تولیدِ خودِ گزارش‌ها
    # همیشه درخت را «کثیف» نشان می‌دهد و provenance بی‌معنا می‌شود.
    dirty = bool(git("status", "--porcelain", "--", "data", "scripts", "tests", "docs"))
    manifest = {
        "schema": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataVersion": f"v{master.get('version', '?')}+{commit[:7] if commit else 'unknown'}",
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
            "pdfCalendarFiles": len(pdfs),
        },
        "verificationStatus": dict(sorted(statuses.items())),
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
        f"- داده: **{manifest['dataVersion']}** · commit: `{commit or 'نامشخص'}`"
        + (" · **درختِ کاری تمیز نیست**" if dirty else ""),
        f"- زمانِ تولید (UTC): `{manifest['generatedAt']}`",
        f"- رویدادِ یکتا: **{c['uniqueEvents']}** · عنوانِ کانونیِ یکتا: **{c['uniqueCanonicalTitles']}**",
        f"- سالِ دارای جدولِ رسمی: **{c['officialYears']}** · ردیفِ رسمی: **{c['officialRows']}**",
        f"- ردیفِ سالانه: **{c['annualRows']}** · متصل: **{c['annualMatchedRows']}** · بدونِ تطبیق: **{c['annualUnmatchedRows']}**",
        f"- فایلِ PDF: **{c['pdfCalendarFiles']}** (هش در manifest)",
        "",
        "## وضعیتِ تأیید (بدونِ ارتقای دسته‌جمعی)",
        "",
        "| وضعیت | تعداد |",
        "|---|---:|",
    ]
    for k, v in sorted(statuses.items(), key=lambda x: str(x[0])):
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "## مرزِ صداقت",
        "",
        "- `officialRows` ردیف‌های جدولِ PDF است، نه تعداد رویدادِ یکتا؛ یک رویداد می‌تواند در چند سال تکرار شود.",
        "- `annualUnmatchedRows` ردیف‌های سالانه‌ای است که `eventId` ندارند؛ در `unmatched.json` تک‌به‌تک مستند شده‌اند.",
        "- هشِ همهٔ فایل‌های داده و PDF در `data-manifest.json` است؛ تغییرِ هر فایل بدونِ تولیدِ دوبارهٔ گزارش = ناسازگاری در تست.",
        "",
    ]
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    print(f"manifest: {manifest['dataVersion']} · events={len(events)} · rows={year_rows} · unmatched={len(unmatched)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
