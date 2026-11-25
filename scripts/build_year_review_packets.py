#!/usr/bin/env python3
"""بستهٔ بازبینیِ ردیف‌به‌ردیف برای سال‌های مسدود (۱۳۹۳/۱۳۹۶/۱۴۰۲).

هیچ ردیفی را تأیید یا فعال نمی‌کند. برای هر ردیف، صفحه، موقعیتِ جدول، متنِ خام و
وضعیتِ قمری را نگه می‌دارد و جای تصمیمِ بازبین را خالی می‌گذارد. خروجی برای
بازبینیِ انسانی است؛ ``publishable`` همیشه ``false`` است.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACTED = ROOT / "extracted" / "json"
DRAFT_1393 = ROOT / "reports" / "ocr" / "1393-rows-draft.json"
OUT = ROOT / "data" / "review" / "year-review-packets"
YEARS = (1393, 1396, 1402)


def _rows_1393() -> tuple[dict, list[dict]]:
    draft = json.loads(DRAFT_1393.read_text(encoding="utf-8"))
    rows = []
    for raw in draft.get("data", []):
        locator = raw.get("locator") or {}
        rows.append({
            "solar": raw.get("solar"),
            "page": locator.get("page") or raw.get("page"),
            "table": None,
            "tableRow": locator.get("tableRow"),
            "titleRaw": raw.get("title", ""),
            "lunarRaw": raw.get("lunar"),
            "lunarValidated": bool(raw.get("lunar") and None not in raw.get("lunar")),
            "holiday": bool(raw.get("holiday")),
            "source": raw.get("source") or draft.get("method"),
            "needsReview": True,
            "review": {"decision": None, "title": None, "solar": None,
                       "lunar": None, "reviewer": None, "reviewedAt": None,
                       "note": None},
        })
    return draft, rows


def _rows_layout(year: int) -> tuple[dict, list[dict]]:
    doc = json.loads((EXTRACTED / f"{year}.json").read_text(encoding="utf-8"))
    rows = []
    for raw in doc.get("rows", []):
        layout = raw.get("layout") or {}
        rows.append({
            "solar": raw.get("solar"),
            "page": raw.get("page"),
            "table": layout.get("table"),
            "tableRow": layout.get("tableRow"),
            "titleRaw": raw.get("title", ""),
            "lunarRaw": raw.get("lunar"),
            "lunarValidated": bool(raw.get("lunar") and None not in raw.get("lunar")),
            "holiday": bool(raw.get("holiday")),
            "source": layout.get("method") or doc.get("source"),
            "needsReview": True,
            "review": {"decision": None, "title": None, "solar": None,
                       "lunar": None, "reviewer": None, "reviewedAt": None,
                       "note": None},
        })
    return doc, rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for year in YEARS:
        if year == 1393:
            source, rows = _rows_1393()
        else:
            source, rows = _rows_layout(year)
        payload = {
            "schema": 1,
            "year": year,
            "status": "awaiting-human-review",
            "publishable": False,
            "source": source.get("source"),
            "rule": "هیچ ردیفی بدونِ تصمیمِ ثبت‌شدهٔ بازبین فعال نمی‌شود.",
            "counts": {"rows": len(rows), "decided": 0},
            "rows": rows,
        }
        if any(row["review"]["decision"] is not None for row in rows):
            raise SystemExit(f"{year}: تصمیمِ خودکار در بستهٔ بازبینی مجاز نیست")
        (OUT / f"{year}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"review packet {year}: {len(rows)} rows, publishable=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
