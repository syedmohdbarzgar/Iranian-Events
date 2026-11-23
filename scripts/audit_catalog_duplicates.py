"""ممیزیِ عنوان‌های تکراریِ کاتالوگ — بدونِ حذفِ خودکار.

تکرارها سه گونه‌اند: چندروزهٔ عمدی، یک رویداد با دو تقویم، و روایت‌های
متعددِ یک مناسبت. فقط گزارش می‌شوند تا حذف/ادغام با شاهدِ انسانی انجام شود.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402

OUT = ROOT / "reports" / "audit" / "catalog-duplicates.json"
MD = ROOT / "reports" / "audit" / "catalog-duplicates.md"


def classify(group: list[dict]) -> str:
    titles = " ".join(e["title"] for e in group)
    cals = {e.get("calendar") for e in group}
    if any(k in titles for k in ("نوروز", "شب قدر", "فاطمه زهرا", "عرفه")):
        return "intentional_multi_day_or_narration"
    if len(cals) > 1:
        return "same_event_multiple_calendars"
    return "same_calendar_multiple_dates_needs_review"


def main() -> int:
    events = json.loads((ROOT / "data" / "events-master.json").read_text(encoding="utf-8"))["events"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        groups[engine._canon(e["title"])].append(e)
    items = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        kind = classify(group)
        items.append({
            "canonical": key,
            "kind": kind,
            "ids": [e["id"] for e in group],
            "events": [{
                "id": e["id"], "title": e["title"], "calendar": e.get("calendar"),
                "month": e.get("month"), "day": e.get("day"),
                "status": e.get("verificationStatus"), "source": e.get("source"),
            } for e in group],
            "action": "keep" if kind.startswith("intentional") else "needs_manual_review",
        })
    items.sort(key=lambda x: (-len(x["events"]), x["canonical"]))
    doc = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "groups": len(items),
        "events": sum(len(x["events"]) for x in items),
        "byKind": {},
        "items": items,
    }
    for it in items:
        doc["byKind"][it["kind"]] = doc["byKind"].get(it["kind"], 0) + 1
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    lines = [
        "# تکرارهای عنوان در کاتالوگ",
        "",
        f"- گروه: **{doc['groups']}** · رویداد: **{doc['events']}**",
        "- هیچ رویدادی در این اجرا حذف یا ادغام نشد.",
        "",
        "| گروه | نوع | شناسه‌ها | اقدام |",
        "|---|---|---|---|",
    ]
    for it in items:
        lines.append(f"| {it['canonical'][:45]} | `{it['kind']}` | {', '.join(it['ids'])} | `{it['action']}` |")
    lines += [
        "",
        "## تفسیر",
        "",
        "- `intentional_multi_day_or_narration`: نوروز/شب قدر/عرفه/فاطمه — چند روز یا چند روایت، نه خطای داده.",
        "- `same_event_multiple_calendars`: یک رویداد با دو تقویم؛ نامزدِ ادغام با شاهدِ انسانی (چکیده در گزارش).",
        "- `same_calendar_multiple_dates_needs_review`: تاریخ‌های متفاوت در یک تقویم؛ بدونِ سند ادغام نشود.",
        "",
    ]
    MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"duplicates: {doc['groups']} groups · {doc['events']} events · {doc['byKind']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
