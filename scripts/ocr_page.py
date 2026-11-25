#!/usr/bin/env python3
"""OCR واقعی یک صفحه + اتصالِ هر ردیف به تاریخ، صفحه و شاهدِ اصلی (P0-03/P0-04).

این ابزار دادهٔ اصلی را تغییر نمی‌دهد. خروجیِ آن یک سندِ قابلِ ممیزی در
``reports/ocr/`` است: هشِ PDF، تصویرِ رندرشده، موتور/زبان/اطمینان، متنِ خام،
ردیف‌های تاریخ‌دارِ استخراج‌شده و تطبیقِ آن‌ها با وقوع‌های منتشرشده.

    py -3 scripts/ocr_page.py --pdf PDF/Calendar-1405.pdf --page 17 --year 1405
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402
import ingest_pdf  # noqa: E402

OUT_DIR = ROOT / "reports" / "ocr"


def _norm(text: str) -> str:
    return store.compare_text(text or "")


def link_rows(rows: list[dict], occurrences: list[dict], year: int) -> list[dict]:
    """هر ردیفِ OCR را به وقوعِ همان سال/تاریخ/عنوان وصل می‌کند؛ بدونِ حدسِ تاریخ."""
    pool = [o for o in occurrences if o.get("year") == year]
    for row in rows:
        solar = row.get("solar") or [None, None, None]
        same_date = [o for o in pool if (o.get("date", {}).get("solar") or [])[1:] == solar[1:]]
        exact = [o for o in same_date if _norm(o.get("observedTitle")) == _norm(row.get("title"))]
        chosen = exact[0] if exact else (same_date[0] if len(same_date) == 1 else None)
        row["link"] = {
            "occurrenceId": chosen.get("id") if chosen else None,
            "eventId": chosen.get("eventId") if chosen else None,
            "kind": "exact" if exact else ("date-only" if chosen else "unmatched"),
            "candidates": len(same_date),
            "sourceRevisionId": chosen.get("evidence", {}).get("revisionId") if chosen else None,
            "sourcePage": chosen.get("evidence", {}).get("page") if chosen else None,
        }
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="OCR یک صفحه با شاهدِ کامل")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    pdf = (ROOT / args.pdf).resolve()
    if not pdf.exists():
        print(f"PDF نیست: {pdf}", file=sys.stderr)
        return 2
    result = ingest_pdf.ocr_page(pdf, args.page, OUT_DIR / "images")
    if result.get("status") != "ok":
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"status": result.get("status"), "reason": result.get("reason"),
                   "pdf": str(pdf.relative_to(ROOT)), "page": args.page}
        path = OUT_DIR / f"page-{args.year}-{args.page:03d}.json"
        store.write_json(path, payload)
        print(f"OCR {result.get('status')}: {result.get('reason')}")
        return 2

    rows = ingest_pdf.parse_ocr_page(
        result.get("text", ""), args.year, args.page,
        ocr_meta={k: result.get(k) for k in
                  ("engine", "lang", "confidence", "image", "imageSha256", "render")})
    occurrences = store.load_history()["occurrences"]
    rows = link_rows(rows, occurrences, args.year)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ok",
        "pdf": str(pdf.relative_to(ROOT)),
        "pdfSha256": store.sha256_file(pdf),
        "page": args.page,
        "year": args.year,
        "engine": result.get("engine"),
        "lang": result.get("lang"),
        "confidence": result.get("confidence"),
        "image": result.get("image"),
        "imageSha256": result.get("imageSha256"),
        "render": result.get("render"),
        "textChars": len(result.get("text", "")),
        "text": result.get("text", ""),
        "rows": rows,
        "linked": sum(1 for r in rows if r["link"]["occurrenceId"]),
        "unmatched": sum(1 for r in rows if not r["link"]["occurrenceId"]),
        "needsReview": all(r.get("needsReview") for r in rows),
        "rule": "ردیفِ OCR فقط با تاریخِ صریح ساخته می‌شود و هرگز خودکار تأیید نمی‌شود.",
    }
    path = OUT_DIR / f"page-{args.year}-{args.page:03d}.json"
    store.write_json(path, payload)
    print(f"OCR ok · {args.year} p{args.page} · engine={payload['engine']} "
          f"confidence={payload['confidence']} rows={len(rows)} "
          f"linked={payload['linked']} → {path.relative_to(ROOT)}")
    for row in rows:
        print(f"  {row['solar']} {row['title'][:60]} → {row['link']['kind']} "
              f"{row['link']['occurrenceId'] or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
