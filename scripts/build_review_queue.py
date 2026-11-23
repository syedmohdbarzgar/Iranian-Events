"""ساختِ صفِ بازبینیِ انسانی برای رویدادهای غیرِ verified.

وضعیتِ `events-master.json` را تغییر نمی‌دهد؛ فقط تعیین تکلیف و شاهدِ لازم را
ثبت می‌کند تا هیچ رویدادی بی‌دلیل به verified ارتقا نیابد.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "data" / "review" / "verification-queue.json"
MD = ROOT / "reports" / "audit" / "verification-queue.md"


def main() -> int:
    master = json.loads((DATA / "events-master.json").read_text(encoding="utf-8"))
    queue = []
    for e in master["events"]:
        status = e.get("verificationStatus")
        if status == "verified":
            continue
        if status == "unverified":
            action = "needs_manual_review"
            reason = "هیچ سندِ مستقلِ تأییدکننده در کاتالوگ ثبت نشده است."
            required = "صفحهٔ PDF همان سال + منبعِ مستقلِ تاریخ (یا حذفِ ادعای رسمی)"
        elif status == "partially_verified":
            action = "needs_independent_source"
            reason = "فقط با پک/جدول هم‌تراز شده؛ سندِ مستقلِ خط‌به‌خط ثبت نشده است."
            required = "نشانیِ صفحهٔ منبعِ اولیه و تاریخِ دسترسی، مستقل از پک"
        elif status == "traditional":
            action = "keep_traditional_no_historical_claim"
            reason = "آیینِ سنتی است و ادعای تاریخِ رسمی/تاریخی ندارد؛ برچسب باید سنتی بماند."
            required = "نیازی به ارتقا نیست؛ فقط منبعِ فرهنگِ عامه در صورت ادعای تاریخی"
        else:
            action = "needs_manual_review"
            reason = "وضعیتِ ناشناخته"
            required = "بازبینیِ دستی"
        queue.append({
            "id": e["id"], "title": e["title"], "status": status,
            "category": e.get("category"), "calendar": e.get("calendar"),
            "month": e.get("month"), "day": e.get("day"),
            "source": e.get("source"), "sourceUrl": e.get("sourceUrl"),
            "origin": e.get("origin"), "action": action,
            "reason": reason, "requiredEvidence": required,
            "lastVerifiedAt": e.get("lastVerifiedAt"),
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": dict(Counter(e["status"] for e in queue)),
        "queue": queue,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    lines = [
        "# صفِ بازبینیِ تأیید — ۱۴۰۵/۰۹/۰۲",
        "",
        f"- کلِ صف: **{len(queue)}**",
        f"- بدونِ تأیید: **{sum(1 for e in queue if e['status'] == 'unverified')}**",
        f"- تأییدِ جزئی: **{sum(1 for e in queue if e['status'] == 'partially_verified')}**",
        f"- سنتی: **{sum(1 for e in queue if e['status'] == 'traditional')}**",
        "",
        "هیچ وضعیتی در این اجرا به `verified` ارتقا داده نشد.",
        "",
        "| شناسه | عنوان | وضعیت | اقدام | شاهدِ لازم |",
        "|---|---|---|---|---|",
    ]
    for e in queue:
        lines.append(
            f"| {e['id']} | {e['title'][:60]} | `{e['status']}` | `{e['action']}` | {e['requiredEvidence'][:80]} |"
        )
    lines += ["", "فایلِ ماشین‌خوان: `data/review/verification-queue.json`", ""]
    MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"review queue: {len(queue)} · {dict(Counter(e['status'] for e in queue))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
