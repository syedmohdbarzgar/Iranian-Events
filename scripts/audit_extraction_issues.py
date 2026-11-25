"""بررسیِ استخراجِ سه سالِ خراب: ۱۳۹۳، ۱۳۹۶، ۱۴۰۲.

هیچ فایلِ `official-calendar-*.json` برای این سال‌ها ساخته نمی‌شود؛ خروجی این
اسکریپت فقط شاهدِ خرابی و تعداد ردیف‌های قابل‌اعتماد/غیرقابل‌اعتماد است.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import parse_official as parser  # noqa: E402

OUT = ROOT / "reports" / "audit" / "extraction-issues.json"
MD = ROOT / "reports" / "audit" / "extraction-issues.md"
REVIEW = ROOT / "data" / "review"
YEARS = (1393, 1396, 1402)


def main() -> int:
    results = []
    REVIEW.mkdir(parents=True, exist_ok=True)
    for year in YEARS:
        pdf = ROOT / "PDF" / f"Calendar-{year}.pdf"
        item = {"year": year, "pdf": str(pdf.relative_to(ROOT)).replace("\\", "/")}
        data = None
        try:
            data = parser.build(year, pdf)
            rows = data["rows"]
            nonempty = [r for r in rows if (r.get("title") or "").strip()]
            qc = data.get("qc", {})
            item.update({
                "rows": len(rows),
                "nonemptyTitles": len(nonempty),
                "weekdayProblems": len(qc.get("problems", [])),
                "gregorianAnomalies": len(qc.get("gregorian_anomalies", [])),
                "sample": [
                    {"solar": r.get("solar"), "title": (r.get("title") or "")[:80]}
                    for r in (nonempty[:3] if nonempty else rows[:3])
                ],
            })
            if year == 1393:
                draft_path = ROOT / "reports" / "ocr" / "1393-rows-draft.json"
                draft = json.loads(draft_path.read_text(encoding="utf-8")) if draft_path.exists() else {}
                item["ocrDraftRows"] = draft.get("rows", 0)
                item["ocrDraftTitles"] = sum(1 for r in draft.get("data", []) if r.get("title"))
                item["nonemptyTitles"] = item["ocrDraftTitles"]
                item["nonemptyTitlesSource"] = "ocr-draft"
                item["verdict"] = "blocked_ocr_table_needs_human_review"
                item["why"] = ("لایهٔ متنی نگاشتِ ناقص دارد؛ draft بازسازیِ جدول با OCR "
                                f"{draft.get('rows', 0)} ردیف ساخت، اما عنوان‌ها/تاریخ قمری "
                                "غلط‌خوانی دارند و همه needsReview هستند.")
            elif year == 1396:
                item["verdict"] = "blocked_layout_lunar_review_required"
                item["why"] = (f"جدول {len(rows)} ردیف و {len(nonempty)} عنوان داد؛ سالِ قمریِ "
                                "لایهٔ متنی خراب است (۱۴۱۸ به‌جای ۱۴۳۸) و عنوان‌ها نیازمند بازبینی‌اند.")
            else:
                item["verdict"] = "blocked_layout_title_review_required"
                item["why"] = (f"جدول {len(rows)} ردیف و {len(nonempty)} عنوان داد؛ ستون‌های میلادی/قمری "
                                "فقط جزئی خوانده شدند و عنوان‌ها نیازمند بازبینی‌اند.")
        except Exception as exc:  # noqa: BLE001
            item.update({"verdict": "extraction_failed", "why": f"{type(exc).__name__}: {exc}"})
        item["publishable"] = False
        item["rawFile"] = f"data/review/official-{year}.extracted.json"
        if data is not None:
            (REVIEW / f"official-{year}.extracted.json").write_text(json.dumps({
                "year": year, "publishable": False,
                "reviewStatus": "needs_manual_review",
                "verdict": item["verdict"],
                "note": "خروجیِ خامِ استخراج؛ برای انتشار/موتور تقویم استفاده نشود.",
                **data,
            }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        results.append(item)

    OUT.write_text(json.dumps({
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "years": results,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    lines = [
        "# استخراجِ ۱۳۹۳، ۱۳۹۶ و ۱۴۰۲ — مسدود",
        "",
        "این سه سال در `data/official-calendar-*.json` **منتشر نشده‌اند**؛ استخراجِ خودکارشان قابل‌اعتماد نیست.",
        "",
        "| سال | ردیف | عنوانِ غیرخالی | خطای هفته | خطای میلادی | حکم |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['year']} | {r.get('rows', '—')} | {r.get('nonemptyTitles', '—')} | "
            f"{r.get('weekdayProblems', '—')} | {r.get('gregorianAnomalies', '—')} | `{r['verdict']}` |"
        )
    lines += [
        "",
        "## دلیلِ توقف",
        "",
        "- **۱۳۹۳:** نگاشتِ فونتِ PDF ناقص است؛ draft جدول با OCR سلول‌ها ساخته شد اما بازبینی انسانی لازم دارد.",
        "- **۱۳۹۶:** جدول ۳۶۵ ردیف و ۱۷۵ عنوان داد؛ سالِ قمری در لایهٔ متنی خراب است.",
        "- **۱۴۰۲:** جدول ۳۶۵ ردیف و ۱۸۴ عنوان داد؛ ستون‌های تاریخ کامل نیستند.",
        "",
        "## اقدامِ لازم",
        "",
        "۱) نصبِ OCR فارسی (Tesseract `fas`) و استخراجِ صفحه‌به‌صفحه با حفظِ مختصات.",
        "۲) بازبینیِ انسانیِ هر ردیف در برابر تصویرِ همان صفحه.",
        "۳) فقط پس از تأیید، فایلِ رسمیِ سال ساخته شود؛ خروجیِ خام در `reports/audit/extraction-issues.json` می‌ماند.",
        "",
    ]
    MD.write_text("\n".join(lines), encoding="utf-8")
    print("extraction:", {" ".join([str(r["year"]) + "=" + r["verdict"] for r in results])})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
