#!/usr/bin/env python3
"""بازسازیِ draft جدولِ ۱۳۹۳ از تصویرِ واقعیِ PDF.

شبکهٔ جدول با PyMuPDF روی PDF اسکن‌شده تشخیص داده می‌شود؛ سپس فقط سلول‌های
غیرسفید (عنوان و تاریخ قمری) با یک worker tesseract.js به‌صورت دسته‌ای OCR
می‌شوند. خروجی فقط در ``reports/ocr/`` است؛ هیچ ردیفی وارد داده اصلی یا فایل
رسمی نمی‌شود و همهٔ ردیف‌ها ``needsReview`` دارند. روز شمسی از شمارهٔ سطر جدول
بازسازی می‌شود؛ چون رقم چاپیِ هر سطر جداگانه OCR نشده، ``dayFromSequence``
همیشه true است و ادعای تأیید رقم چاپی نمی‌کنیم.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import parse_official as official  # noqa: E402
import history_store as store  # noqa: E402

PDF = ROOT / "PDF" / "Calendar-1393.pdf"
ROW_DIR = ROOT / "reports" / "ocr" / "rows"
JOB_PATH = ROW_DIR / "jobs.json"
OUT_JSON = ROOT / "reports" / "ocr" / "1393-rows-draft.json"
OUT_MD = ROOT / "reports" / "ocr" / "1393-rows-draft.md"
BATCH_TOOL = ROOT / "tools" / "ocr" / "ocr_batch.cjs"


def has_ink(page: pymupdf.Page, rect: pymupdf.Rect, threshold: int = 180) -> bool:
    pix = page.get_pixmap(clip=rect, dpi=180, colorspace=pymupdf.csGRAY)
    return bool(pix.samples) and min(pix.samples) < threshold


def lunar_of(text: str, solar_year: int, solar_month: int, solar_day: int) -> list[int | None]:
    text = text.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    compact = text.replace(" ", "")
    month = next((name for name in official.LUNAR_MONTHS
                  if name.replace(" ", "") in compact), None)
    years = [int(x) for x in re.findall(r"\b\d{3,4}\b", text)]
    days = [int(x) for x in re.findall(r"\b\d{1,2}\b", text)]
    if month is None or not years or not days:
        return [None, None, None]
    year = years[0] + (1000 if years[0] < 1000 else 0)
    day = next((d for d in days if 1 <= d <= 30), None)
    # سال قمری باید حدود ۴۲ سال جلوتر از سال شمسی باشد؛ در غیر این صورت
    # OCR سال را خراب خوانده و مقدار ساختگی ثبت نمی‌کنیم.
    if day is None or not (solar_year + 40 <= year <= solar_year + 43):
        return [None, None, None]
    import calendar_engine as engine
    expected = engine.islamic_from_jdn(engine.jdn_jalali(solar_year, solar_month, solar_day))
    got = (year, official.LUNAR_MONTHS.index(month) + 1, day)
    if abs(engine.jdn_islamic(*got) - engine.jdn_islamic(*expected)) > 1:
        return [None, None, None]
    return list(got)


def clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" |-\u200c")


def main() -> int:
    if not PDF.exists():
        print(f"PDF نیست: {PDF}", file=sys.stderr)
        return 2
    doc = pymupdf.open(PDF)
    ROW_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    jobs: list[dict] = []
    pages: list[dict] = []
    for page_number in range(3, 15):
        month = page_number - 2  # صفحه ۳ = فروردین، ...، صفحه ۱۴ = اسفند
        page = doc[page_number - 1]
        tables = page.find_tables().tables
        if not tables:
            pages.append({"page": page_number, "month": month, "error": "no-table"})
            continue
        table = tables[0]
        month_len = 31 if month <= 6 else (30 if month <= 11 else 29)
        data_rows = table.rows[1:]
        for index in range(1, month_len + 1):
            if index > len(data_rows):
                break
            cells = data_rows[index - 1].cells
            rec = {"page": page_number, "month": month, "index": index,
                   "titleTag": f"1393-p{page_number}-r{index:02d}-title",
                   "lunarTag": f"1393-p{page_number}-r{index:02d}-lunar"}
            for kind, cell_index in (("title", 0), ("lunar", 2)):
                cell = cells[cell_index] if cell_index < len(cells) else None
                rect = pymupdf.Rect(cell) if cell else None
                if rect is None or rect.is_empty or not has_ink(page, rect):
                    continue
                pix = page.get_pixmap(clip=rect, dpi=300)
                image = ROW_DIR / f"{rec[kind + 'Tag']}.png"
                pix.save(image)
                jobs.append({"tag": rec[kind + "Tag"], "path": str(image.relative_to(ROOT))})
            records.append(rec)
        pages.append({"page": page_number, "month": month, "monthLength": month_len,
                      "tableRows": len(data_rows), "usedRows": min(len(data_rows), month_len)})
    JOB_PATH.write_text(json.dumps({"psm": 7, "images": jobs}, ensure_ascii=False),
                        encoding="utf-8")
    proc = subprocess.run(["node", str(BATCH_TOOL), str(JOB_PATH)],
                          capture_output=True, cwd=ROOT, env=os.environ)
    if proc.returncode != 0:
        print(proc.stderr.decode("utf-8", "replace")[:1500], file=sys.stderr)
        return 3
    batch = json.loads(proc.stdout.decode("utf-8"))
    texts = {r["tag"]: r for r in batch.get("results", [])}

    rows: list[dict] = []
    for rec in records:
        title_ocr = texts.get(rec["titleTag"], {})
        lunar_ocr = texts.get(rec["lunarTag"], {})
        title = clean_title(title_ocr.get("text", ""))
        g = official.jalali_to_gregorian(1393, rec["month"], rec["index"])
        rows.append({
            "solar": [1393, rec["month"], rec["index"]],
            "gregorian": list(g),
            "lunar": lunar_of(lunar_ocr.get("text", ""), 1393, rec["month"], rec["index"]),
            "weekday": date(*g).weekday(),
            "title": title,
            "holiday": "تعطیل" in title,
            "page": rec["page"],
            "source": "ocr-table-cells",
            "needsReview": True,
            "dayFromSequence": True,
            "printedDay": None,
            "locator": {"kind": "ocr-table-row", "page": rec["page"],
                        "tableRow": rec["index"]},
            "ocr": {"engine": batch.get("engine"), "lang": batch.get("lang"),
                    "title": {"confidence": title_ocr.get("confidence")},
                    "lunar": {"confidence": lunar_ocr.get("confidence")}},
        })
    for p in pages:
        subset = [r for r in rows if r["page"] == p["page"]]
        p["withTitle"] = sum(1 for r in subset if r["title"])
        p["withLunar"] = sum(1 for r in subset if r["lunar"][1])
    payload = {"status": "draft", "year": 1393, "source": "Calendar-1393.pdf",
               "method": "PyMuPDF table grid + tesseract.js fas PSM7 batch cells",
               "rows": len(rows), "needsReview": True, "pages": pages,
               "jobCount": len(jobs),
               "rule": "روز از شمارهٔ سطر جدول بازسازی شده؛ هیچ ردیفی وارد داده اصلی نشده است.",
               "data": rows}
    store.write_json(OUT_JSON, payload)
    lines = ["# بازسازیِ draft جدول ۱۳۹۳ با OCR سلول‌های جدول", "",
             f"**{len(rows)} ردیف draft · همه needsReview · منبع: `{PDF.name}` · "
             f"{len(jobs)} سلول OCR‌شده**", "",
             "| صفحه | ماه | طول ماه | سطر جدول | استفاده | عنوان | قمری |",
             "|---|---|---|---|---|---|---|"]
    for p in pages:
        lines.append(f"| {p['page']} | {p['month']} | {p.get('monthLength', '')} | "
                     f"{p.get('tableRows', p.get('error', ''))} | {p.get('usedRows', '')} | "
                     f"{p.get('withTitle', '')} | {p.get('withLunar', '')} |")
    lines += ["", "روز شمسی از شمارهٔ سطر جدول بازسازی شده و رقم چاپی جداگانه OCR نشده "
              "است؛ بنابراین `dayFromSequence` برای همه true است. عنوان‌ها خام‌اند و "
              "غلط‌خوانی OCR دارند؛ ورود به `data/history/` نیازمند بازبینی انسانی است."]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"draft rows={len(rows)} pages={len(pages)} jobs={len(jobs)} → {OUT_JSON.relative_to(ROOT)}")
    for p in pages:
        print(f"  p{p['page']} month={p['month']} table={p.get('tableRows')} "
              f"used={p.get('usedRows')} titles={p.get('withTitle')} lunar={p.get('withLunar')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
