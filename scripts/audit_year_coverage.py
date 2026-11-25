#!/usr/bin/env python3
"""P1-01: تعیینِ تکلیفِ سال‌های بدونِ نسخهٔ منتشرشده (۱۳۹۳/۱۳۹۶/۱۴۰۲).

هیچ سالی با حدس پر نمی‌شود. برای هر سال، وجودِ PDF، وضعیتِ استخراج، دلیلِ
مسدودبودن و اقدامِ لازم ثبت می‌شود؛ خروجی برای سالِ مسدود عمداً
``publishable: false`` است.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402

TARGETS = (1393, 1396, 1402)
OUT_MD = ROOT / "reports" / "year-coverage.md"
OUT_JSON = ROOT / "reports" / "year-coverage.json"


def main() -> int:
    history = store.load_history()
    active = store.active_revisions(history["revisions"])
    issues_path = ROOT / "reports" / "audit" / "extraction-issues.json"
    extraction = {}
    if issues_path.exists():
        data = json.loads(issues_path.read_text(encoding="utf-8"))
        extraction = {item.get("year"): item for item in data.get("years", [])}
    probe_path = ROOT / "reports" / "ocr" / "page-1393-004.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8")) if probe_path.exists() else None

    rows = []
    for year in TARGETS:
        item = extraction.get(year, {})
        pdf = ROOT / "PDF" / f"Calendar-{year}.pdf"
        status = "published" if year in active else "blocked"
        packet_path = ROOT / "data" / "review" / "year-review-packets" / f"{year}.json"
        packet = (json.loads(packet_path.read_text(encoding="utf-8"))
                  if packet_path.exists() else {})
        action = ""
        draft_path = ROOT / "reports" / "ocr" / "1393-rows-draft.json"
        draft = json.loads(draft_path.read_text(encoding="utf-8")) if draft_path.exists() else {}
        if year == 1393:
            action = (f"draft جدول با OCR سلول‌ها {draft.get('rows', 0)} ردیف و "
                      f"{item.get('ocrDraftTitles', 0)} عنوان ساخت (PSM 7، اطمینانِ نمونهٔ "
                      f"{probe.get('confidence') if probe else 'نامعلوم'})؛ عنوان‌ها/تاریخ قمری "
                      "نیازمند بازبینی انسانی‌اند و انتشار مسدود است.")
        elif year == 1396:
            action = (f"جدول {item.get('rows', 0)} ردیف و {item.get('nonemptyTitles', 0)} عنوان داد؛ "
                      "سالِ قمری در لایهٔ متنی خراب است؛ بازبینی انسانی لازم است.")
        elif year == 1402:
            action = (f"جدول {item.get('rows', 0)} ردیف و {item.get('nonemptyTitles', 0)} عنوان داد؛ "
                      "ستون‌های تاریخ کامل نیستند؛ بازبینی انسانی لازم است.")
        rows.append({
            "year": year,
            "pdf": str(pdf.relative_to(ROOT)),
            "pdfExists": pdf.exists(),
            "activeRevision": active.get(year, {}).get("id"),
            "status": status,
            "verdict": item.get("verdict", "not_reported"),
            "why": item.get("why", ""),
            "rowsInTextLayer": item.get("rows"),
            "nonemptyTitles": item.get("nonemptyTitles"),
            "publishable": status == "published",
            "reviewPacket": (str(packet_path.relative_to(ROOT)) if packet else None),
            "reviewRows": (packet.get("counts") or {}).get("rows"),
            "reviewDecided": (packet.get("counts") or {}).get("decided"),
            "action": action,
        })
    payload = {"generatedAt": store.now_iso(), "years": rows,
               "rule": "سالِ بدونِ شاهدِ کامل منتشر نمی‌شود و با حدس پر نمی‌شود."}
    store.write_json(OUT_JSON, payload)
    lines = ["# تکلیفِ سال‌های بدونِ نسخه", "",
             "| سال | PDF | نسخهٔ فعال | وضعیت | حکم استخراج | عنوان‌های غیرخالی | اقدام |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['year']} | {'دارد' if r['pdfExists'] else 'ندارد'} | "
                     f"{r['activeRevision'] or '—'} | {r['status']} | {r['verdict']} | "
                     f"{r['nonemptyTitles']} | {r['action']} |")
    lines += ["", "این سه سال **منتشر نشده‌اند** و نسخهٔ رسمی/قابل انتشاری برایشان ساخته نشده است؛ "
              "draftها در `data/review/` و `reports/ocr/` و بسته‌های ردیف‌به‌ردیف در "
              "`data/review/year-review-packets/` جدا نگه داشته می‌شوند. هر بسته صفحه، "
              "موقعیتِ جدول، متنِ خام و جای خالیِ تصمیمِ بازبین را دارد و `publishable=false` است."]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"year coverage: published={sum(1 for r in rows if r['status']=='published')} "
          f"blocked={sum(1 for r in rows if r['status']=='blocked')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
