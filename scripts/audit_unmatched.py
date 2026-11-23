"""مستندسازیِ تک‌به‌تکِ ردیف‌های بدونِ تطبیق.

هیچ ردیفی حذف یا با حدس به رویداد وصل نمی‌شود. خروجی برای هر ردیف:
سال، تاریخ، منبع، صفحهٔ PDF (اگر ردیف رسمی باشد)، عنوان، دستهٔ مشکل و
اقدامِ لازم. وضعیت همه `needs_manual_review` است مگر اینکه عنوان دقیقاً
تکرارِ یک ردیفِ دیگر باشد.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "reports" / "audit" / "unmatched.json"
MD = ROOT / "reports" / "audit" / "unmatched.md"


def classify(title: str) -> str:
    t = title.strip()
    if len(t) < 15:
        return "fragment_or_truncated_title"
    if re.search(r"[()]", t) and t.count("(") != t.count(")"):
        return "unbalanced_parentheses"
    if len(re.findall(r"\s+و\s+", t)) >= 2 or "روز" in t[20:]:
        return "multi_event_or_concatenated"
    if re.search(r"(ش و|ه‍\.ش|ه‍\.ق|روز روز|روز ملی روز)", t):
        return "extraction_artifact"
    return "no_safe_catalog_match"


def main() -> int:
    pages: dict[tuple[int, tuple[int, int, int]], int] = {}
    for path in DATA.glob("official-calendar-*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        y = int(doc["year"])
        for row in doc["rows"]:
            pages[(y, tuple(row["solar"]))] = row.get("page")

    rows = []
    for path in sorted((DATA / "years").glob("*.json")):
        if not path.stem.isdigit():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("mode") != "data":
            continue
        y = int(path.stem)
        for row in doc.get("rows", []):
            if row.get("eventId"):
                continue
            title = (row.get("title") or "").strip()
            rows.append({
                "year": y,
                "solar": row["solar"],
                "title": title,
                "source": row.get("source"),
                "page": pages.get((y, tuple(row["solar"]))) if row.get("source") == "official-pdf" else None,
                "category": classify(title),
                "disposition": "needs_manual_review",
                "action": "افزودنِ رویدادِ کاتالوگ با منبع مستقل یا ثبت به‌عنوان ردیفِ چندرویدادی/آسیبِ استخراج",
            })

    groups = Counter(r["title"] for r in rows)
    doc = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(rows),
        "uniqueTitles": len(groups),
        "byCategory": dict(Counter(r["category"] for r in rows)),
        "byYear": dict(sorted(Counter(str(r["year"]) for r in rows).items())),
        "topRepeated": [{"title": t, "rows": n} for t, n in groups.most_common(20)],
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    lines = [
        "# ردیف‌های بدونِ تطبیق — مستندشده",
        "",
        f"- تولید: `{doc['generatedAt']}`",
        f"- کل: **{doc['total']}** ردیف · عنوانِ یکتا: **{doc['uniqueTitles']}**",
        "- وضعیت همه: `needs_manual_review` — هیچ‌کدام حذف یا با حدس وصل نشده‌اند.",
        "",
        "## دسته‌بندی",
        "",
        "| دسته | ردیف |",
        "|---|---:|",
    ]
    for k, v in sorted(doc["byCategory"].items(), key=lambda x: -x[1]):
        lines.append(f"| `{k}` | {v} |")
    lines += ["", "## پرتکرارترین عنوان‌ها", "", "| عنوان | ردیف |", "|---|---:|"]
    for item in doc["topRepeated"]:
        lines.append(f"| {item['title'][:100]} | {item['rows']} |")
    lines += [
        "",
        "## فهرستِ کامل",
        "",
        f"همهٔ {doc['total']} ردیف با سال/تاریخ/صفحه/دسته در `unmatched.json` هستند؛ این فهرست فقط خلاصهٔ قابل‌خواندن است.",
        "",
    ]
    MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"unmatched: {doc['total']} rows · {doc['uniqueTitles']} titles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
