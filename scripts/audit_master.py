#!/usr/bin/env python3
"""گزارشِ اعتبارسنجیِ کاتالوگ از روی فایلِ موجود، بدونِ بازسازی.

`build_master.py` فقط هنگامِ بازسازی گزارش می‌سازد؛ اگر کاتالوگ با
`apply_identity_corrections.py` اصلاح شود، گزارشِ قدیمی کهنه می‌ماند. این
اسکریپت تنها منبعِ شمارش را می‌خواند و گزارش را با همان اعداد بازمی‌سازد.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORT = ROOT / "reports" / "master-validation.md"


def main() -> int:
    master = json.loads((DATA / "events-master.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "reports" / "audit" / "data-manifest.json").read_text(encoding="utf-8"))
    events = master["events"]
    counts = Counter(e.get("category") for e in events)
    cals = Counter(e.get("calendar") for e in events)
    recs = Counter(e.get("recurrenceType") for e in events)
    statuses = Counter(e.get("verificationStatus") for e in events)
    merged = sum(max(0, len(e.get("mergedTitles", [])) - 1) for e in events)
    corrected = [e["id"] for e in events if e.get("correctionHistory")]
    lines = ["# اعتبارسنجی فایل یگانهٔ رویدادها (نسخهٔ ۲)", "",
             f"- داده: **{manifest['dataVersion']}** · commit: `{manifest['commit'][:7]}`",
             f"- رویدادها: **{len(events)}** · عنوان‌های ادغام‌شده: **{merged}** · اصلاحیهٔ هویتی: **{len(corrected)}**",
             "- دسته‌ها: " + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())),
             "- تقویم: " + " · ".join(f"{k}: {v}" for k, v in sorted(cals.items())),
             "- نوع تکرار: " + " · ".join(f"{k}: {v}" for k, v in sorted(recs.items())),
             "- وضعیت اعتبار: " + " · ".join(f"{k}: {v}" for k, v in sorted(statuses.items())),
             f"- خطا: **{len(master.get('errors', []))}** · هشدار: **{len(master.get('warnings', []))}**", ""]
    if corrected:
        lines += ["## اصلاحیه‌های هویتی", ""]
        for e in events:
            if e["id"] in corrected:
                lines.append(f"- `{e['id']}` → `{e.get('supersededBy')}` — {e['title']}")
        lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"master-validation: events={len(events)} status={dict(statuses)} errors={len(master.get('errors', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
