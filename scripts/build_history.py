"""ساختِ مبنای تاریخِ رویداد از PDFهای رسمی (فاز ۱ و ۲ چک‌لیست).

برای هر ``data/official-calendar-<سال>.json`` یک ``CalendarRevision`` می‌سازد که
هش/صفحه/روشِ استخراجِ PDF خودش را دارد، سپس هویت‌ها و وقوع‌ها را از همان
نسخه‌های تأییدشده بازتولید می‌کند. هیچ ردیفی از ``data/years`` (خروجیِ
قاعده‌محور) وارد نمی‌شود.

اجرا:
    py -3 scripts/build_history.py              # ساختِ مبنا اگر خالی باشد
    py -3 scripts/build_history.py --force      # بازسازیِ مبنا فقط بدونِ تأییدِ انسانی
    py -3 scripts/build_history.py --force-all  # بازنویسیِ کامل (ChangeLog حفظ می‌شود)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402

DATA = ROOT / "data"
PDF_DIR = ROOT / "PDF"
TEXT_INDEX = ROOT / "extracted" / "text" / "_index.json"
REPORT = ROOT / "reports" / "history-build.md"


def pdf_pages(pdf: Path) -> int:
    index = store.load_json(TEXT_INDEX, [])
    for row in index if isinstance(index, list) else []:
        if row.get("file") == pdf.name and row.get("pages"):
            return int(row["pages"])
    import subprocess
    proc = subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), "-"], capture_output=True)
    if proc.returncode != 0:
        return 0
    return proc.stdout.count(b"\f")


def baseline_revision(year: int, official: dict, pdf: Path) -> tuple[dict, list[dict]]:
    sha = store.sha256_file(pdf)
    rid = store.revision_id(year, sha)
    rows = []
    for row in official.get("rows", []):
        if not store.row_is_event(row.get("title", "")):
            continue
        rows.append({
            "solar": row.get("solar"),
            "gregorian": row.get("gregorian"),
            "lunar": row.get("lunar"),
            "weekday": row.get("weekday"),
            "title": row.get("title", ""),
            "holiday": bool(row.get("holiday")),
            "page": row.get("page"),
            "derived": row.get("derived", []),
            "corrections": row.get("corrections", []),
        })
    rev = {
        "id": rid,
        "year": year,
        "document": {
            "file": pdf.name,
            "originalName": pdf.name,
            "storedPath": f"PDF/{pdf.name}",
            "sha256": sha,
            "bytes": pdf.stat().st_size,
            "pages": pdf_pages(pdf),
        },
        "extraction": {
            "method": "text-layer",
            "tool": "pdftotext -table",
            "extractedAt": store.BASELINE_AT,
            "rowCount": len(rows),
            "sourceKind": "baseline-official-json",
            "ocrPages": [],
            "qcProblems": len((official.get("qc") or {}).get("problems", [])),
        },
        "state": "approved",
        "approvedBy": store.BASELINE_ACTOR,
        "approvedAt": store.BASELINE_AT,
        "approval": {
            "kind": "baseline",
            "method": "baseline-import",
            "by": store.BASELINE_ACTOR,
            "at": store.BASELINE_AT,
            "note": "واردکردنِ خودکارِ مبنای parse_official؛ تأییدِ انسانی نیست.",
        },
        "note": "مبنای بازسازی‌شده از data/official-calendar-*.json (خروجیِ parse_official).",
        "supersedes": None,
        "supersededBy": None,
    }
    return rev, rows


def main() -> int:
    ap = argparse.ArgumentParser(description="ساختِ مبنای تاریخِ رویداد")
    ap.add_argument("--force", action="store_true", help="بازسازیِ مبنا (فقط وقتی تأییدِ انسانی نداریم)")
    ap.add_argument("--force-all", action="store_true",
                    help="بازنویسیِ کامل حتی با تأییدهای انسانی (خطرناک؛ ChangeLog پاک نمی‌شود)")
    args = ap.parse_args()

    existing = store.load_history()
    human = [r for r in existing["revisions"]
             if (r.get("approval") or {}).get("kind") == "human"
             or r.get("approvedBy") != store.BASELINE_ACTOR]
    if args.force and not args.force_all and (human or existing["changelog"]):
        print("این تاریخ تأییدِ انسانی/ChangeLog دارد؛ بازسازیِ مبنا آن را بی‌اعتبار می‌کند. "
              "اگر واقعاً می‌خواهید، --force-all بدهید.", file=sys.stderr)
        return 2
    if existing["revisions"] and not (args.force or args.force_all):
        print("تاریخ از پیش ساخته شده است؛ برای بازسازی --force بدهید.")
        print(f"نسخه‌ها: {len(existing['revisions'])} · وقوع‌ها: {len(existing['occurrences'])}")
        return 0

    catalog = store.master_catalog()
    revisions, rows_by_revision = [], {}
    skipped: list[str] = []
    for official_path in sorted(DATA.glob("official-calendar-*.json")):
        m = re.search(r"official-calendar-(\d{4})\.json$", official_path.name)
        if not m:
            continue
        year = int(m.group(1))
        pdf = PDF_DIR / f"Calendar-{year}.pdf"
        if not pdf.exists():
            skipped.append(f"{year}: PDF نیست")
            continue
        official = store.load_json(official_path, {})
        rev, rows = baseline_revision(year, official, pdf)
        revisions.append(rev)
        rows_by_revision[rev["id"]] = rows

    if not revisions:
        print("هیچ نسخه‌ای ساخته نشد.", file=sys.stderr)
        return 1

    keep = {rev["id"] for rev in revisions}
    for old in store.REVISION_DIR.glob("R-*.json"):
        if old.stem not in keep:
            old.unlink()
    store.save_revisions(revisions)
    for rev in revisions:
        store.save_revision_rows(rev["id"], rev["year"], rows_by_revision[rev["id"]],
                                 source=rev["document"])
    events, occurrences = store.derive(catalog, revisions, rows_by_revision)
    store.save_history(events, occurrences)

    issues = store.validate(store.load_history())
    errors = [i for i in issues if i["severity"] == "error"]
    witnessed = [e for e in events if e["observedYears"]]
    lines = [
        "# ساختِ مبنای تاریخِ رویداد",
        "",
        f"- نسخه‌های تقویم: **{len(revisions)}** سال ({min(r['year'] for r in revisions)}–"
        f"{max(r['year'] for r in revisions)})",
        f"- ردیف‌های شاهد: **{sum(len(r) for r in rows_by_revision.values())}**",
        f"- هویت‌ها: **{len(events)}** (با وقوع: {len(witnessed)} · بدونِ وقوع: {len(events) - len(witnessed)})",
        f"- وقوع‌های سالانه: **{len(occurrences)}**",
        f"- خطا: **{len(errors)}**",
        "",
        "## پوششِ سالانه",
        "",
        "| سال | هشِ PDF | صفحه | ردیف | وقوع |",
        "|---|---|---|---|---|",
    ]
    occ_by_year: dict[int, int] = {}
    for o in occurrences:
        occ_by_year[o["year"]] = occ_by_year.get(o["year"], 0) + 1
    for rev in sorted(revisions, key=lambda r: r["year"]):
        lines.append(f"| {rev['year']} | `{rev['document']['sha256'][:12]}` | "
                     f"{rev['document']['pages']} | {len(rows_by_revision[rev['id']])} | "
                     f"{occ_by_year.get(rev['year'], 0)} |")
    if skipped:
        lines += ["", "## سال‌های بدونِ نسخه", ""] + [f"- {s}" for s in skipped]
    if errors:
        lines += ["", "## خطاها", ""] + [f"- `{i['code']}` {i['message']}" for i in errors[:50]]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"revisions={len(revisions)} events={len(events)} witnessed={len(witnessed)} "
          f"occurrences={len(occurrences)} errors={len(errors)}")
    for issue in errors[:10]:
        print("  !", issue["code"], issue["message"])
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
