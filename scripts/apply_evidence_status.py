#!/usr/bin/env python3
"""وضعیتِ اعتبار را از شاهدِ ثبت‌شده می‌سازد، نه از حضور در یک جدول.

قاعده:
  • فقط شاهدی که مستقل از PDF/کاتالوگ تأیید شده باشد `verified` می‌شود.
  • ردیفِ PDF یا شاهدِ کاتالوگِ تنها ⇒ `partially_verified` (تک‌منبع).
  • رویدادِ آیینی/سنتی با برچسبِ قبلی ⇒ `traditional`.
  • بدونِ شاهدِ اولیه یا با تاریخِ مورد اختلاف ⇒ `unverified`.

هیچ رویدادی حذف نمی‌شود؛ تغییرِ وضعیت با تاریخچه در خودِ رکورد می‌ماند.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "events-master.json"
TODAY = date.today().isoformat()


def main() -> int:
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    changed = 0
    for event in master["events"]:
        evidence = event.get("evidence") or {}
        old = event.get("verificationStatus")
        if event.get("excludeFromCalendar") or event.get("dateCertainty") == "disputed":
            new = "unverified"
            reason = "هویت/تاریخ مورد اختلاف است و از تقویم کنار گذاشته شده"
        elif old == "traditional":
            new = "traditional"
            reason = "رویدادِ آیینی/سنتی؛ سندِ ثبتِ رسمی ندارد"
        elif evidence.get("kind") == "official-pdf-row":
            new = "partially_verified"
            reason = "فقط ردیفِ جدولِ رسمیِ PDF؛ تأییدِ مستقل انجام نشده"
        else:
            new = "unverified"
            reason = "شاهدِ اولیه/صفحهٔ سند برای این رویداد ثبت نشده"
        event.setdefault("previousVerificationStatus", old)
        event["verificationStatus"] = new
        event["evidenceLevel"] = (
            "official-primary-only" if evidence.get("kind") == "official-pdf-row"
            else "disputed" if new == "unverified" and event.get("excludeFromCalendar")
            else "rule-or-catalog-only"
        )
        if new != old:
            event.setdefault("verificationHistory", []).append({
                "date": TODAY, "from": old, "to": new, "reason": reason,
                "source": evidence.get("sourceRef"),
                "reviewKind": "automated-source-capture",
            })
            changed += 1
    master["verification_counts"] = dict(sorted(Counter(e["verificationStatus"] for e in master["events"]).items()))
    MASTER.write_text(json.dumps(master, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"evidence-status: changed={changed} counts={master['verification_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
