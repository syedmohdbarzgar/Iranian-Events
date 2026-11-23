#!/usr/bin/env python3
"""اعمالِ اصلاحیه‌های هویتی روی data/events-master.json، بدونِ بازسازیِ کاتالوگ.

چرا جدا از build_master؟ چون بازسازیِ کامل می‌تواند تعداد/عنوان‌های کاتالوگ را
تغییر دهد. این اسکریپت فقط رکوردهای مشخص‌شده را اصلاح می‌کند، مقدار قبلی را در
correctionHistory نگه می‌دارد و رکورد را حذف نمی‌کند.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MASTER = DATA / "events-master.json"
CORRECTIONS = DATA / "event-identity-corrections.json"
REPORT = ROOT / "reports" / "audit" / "identity-corrections.md"


def main() -> int:
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    corrections = json.loads(CORRECTIONS.read_text(encoding="utf-8")).get("corrections", [])
    by_id = {e["id"]: e for e in master["events"]}
    applied, errors = [], []
    for corr in corrections:
        event = by_id.get(corr.get("id"))
        if event is None:
            errors.append(f"شناسهٔ ناموجود: {corr.get('id')}")
            continue
        if corr.get("supersededBy") not in by_id:
            errors.append(f"جایگزینِ ناموجود برای {corr['id']}: {corr.get('supersededBy')}")
            continue
        event["correctionHistory"] = {
            "preserved": corr.get("preserved", {}),
            "reason": corr.get("reason", ""),
            "source": corr.get("source", ""),
            "supersededBy": corr.get("supersededBy"),
        }
        event.update(corr.get("set", {}))
        event["supersededBy"] = corr.get("supersededBy")
        applied.append(event)
        if event.get("excludeFromCalendar") and event.get("verificationStatus") == "verified":
            errors.append(f"{event['id']} کنارگذاشته اما verified")

    master["verification_counts"] = dict(Counter(e.get("verificationStatus") for e in master["events"]))
    master["identityCorrections"] = {
        "file": "data/event-identity-corrections.json",
        "applied": [e["id"] for e in applied],
        "errors": errors,
    }
    MASTER.write_text(json.dumps(master, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# اصلاحیه‌های هویتی", "",
             f"- اعمال‌شده: **{len(applied)}** · خطا: **{len(errors)}**", ""]
    for e in applied:
        h = e["correctionHistory"]
        lines += [f"## {e['id']} — {e['title']}", "",
                  f"- جایگزین: `{h['supersededBy']}`",
                  f"- وضعیت: `{e['verificationStatus']}` · قطعیت تاریخ: `{e.get('dateCertainty')}` · از تقویم کنار گذاشته: `{bool(e.get('excludeFromCalendar'))}`",
                  f"- دلیل: {h['reason']}",
                  f"- منبع: {h['source']}", ""]
    if errors:
        lines += ["## خطاها", ""] + [f"- {x}" for x in errors]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"identity corrections: applied={len(applied)} errors={len(errors)} -> {MASTER}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
