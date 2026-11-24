#!/usr/bin/env python3
"""ثبتِ تصمیمِ بازبینیِ ۲۲ هویتِ ردیفیِ مشکوک (فاز ۳ چک‌لیست).

این ابزار **تصمیم را نمی‌سازد**؛ تصمیم‌های انسانی/دستورِ کاربر در ``DECISIONS``
ثابت شده‌اند و ابزار فقط شاهدِ صفحه/نسخه و اجزای کاتالوگی را از خودِ داده
می‌خواند و در ``data/history/identity-reviews.json`` می‌نویسد.

قاعده‌ها:
* ``map`` فقط برای ردیف‌هایی است که عنوان و تاریخشان با یک رویدادِ کاتالوگی
  یکی است؛ پنج ردیفِ پراکندهٔ «زائران خانه خدا» به ``E0460`` نگاشت می‌شوند.
* ``keep-merged-row`` برای ردیف‌هایی است که چند رویدادِ متفاوت را در یک سطر
  چاپ کرده‌اند؛ هیچ ادغامِ خودکاری انجام نمی‌شود و فقط بازبینی مستند می‌شود.
* هر ورودی شاهدِ نسخه/صفحه، علت، زمان و بازبین دارد؛ دادهٔ مشتق‌شده از همین
  فایل ساخته می‌شود و با گیت قابلِ ردیابی/بازگردانی است.

    py -3 scripts/build_identity_reviews.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402

REVIEWED_AT = "2026-11-24T00:00:00Z"
REVIEWED_BY = "agent:checklist-2026-11-24 (user instruction)"
OUT = store.IDENTITY_REVIEWS_FILE

# eventId → (decision, target, constituent catalog ids, match basis)
DECISIONS: dict[str, tuple[str, str | None, list[str], str]] = {
    # یک رویدادِ واحد با عنوانِ مخدوش/پراکنده: نگاشت به هویتِ کاتالوگیِ همان رویداد.
    "S1273FA50": ("map", "E0460", ["E0460"], "عنوان و تاریخِ ۶ ذی‌الحجه با E0460 یکی است"),
    "S2864F821": ("map", "E0460", ["E0460"], "عنوان و تاریخِ ۶ ذی‌الحجه با E0460 یکی است"),
    "SB5330A72": ("map", "E0460", ["E0460"], "عنوان و تاریخِ ۶ ذی‌الحجه با E0460 یکی است"),
    "SB8C7DC86": ("map", "E0460", ["E0460"], "عنوان و تاریخِ ۶ ذی‌الحجه با E0460 یکی است"),
    "SE2CF8360": ("map", "E0460", ["E0460"], "عنوان و تاریخِ ۶ ذی‌الحجه با E0460 یکی است"),
    # ردیف‌های چسبیده: چند رویداد در یک سطر؛ بدونِ ادغام.
    "S194E7B48": ("keep-merged-row", None, ["E0037", "E0414"],
                  "شهادتِ آیت‌الله مدنی + روز تجلیل از امام‌زادگان"),
    "S23C94E95": ("keep-merged-row", None, ["E0126", "E0110"],
                  "رحلتِ امام خمینی + انتخابِ آیت‌الله خامنه‌ای"),
    "S252E2C30": ("keep-merged-row", None, ["E0500", "E0422"],
                  "ولادتِ حضرت فاطمه زهرا + روز زن"),
    "S278D8684": ("keep-merged-row", None, ["E0033", "E0483", "E0407"],
                  "شهادتِ آیت‌الله صدوقی + ولادتِ امام حسن مجتبی + روز اکرام"),
    "S2C075D77": ("keep-merged-row", None, ["E0126", "E0110"],
                  "رحلتِ امام خمینی + انتخابِ آیت‌الله خامنه‌ای"),
    "S4B6485C1": ("keep-merged-row", None, ["E0118", "E0303", "E0242"],
                  "تسخیرِ لانهٔ جاسوسی + روز مبارزه با استکبار + روز دانش‌آموز"),
    "S6ABF99E3": ("keep-merged-row", None, ["E0047", "E0085"],
                  "شهادتِ آیت‌الله اشرفی اصفهانی + روز جهانی نابینایان"),
    "S7AEF8101": ("keep-merged-row", None, ["E0213", "E0411", "E0483"],
                  "روز تشکل‌ها + روز سلمان فارسی + ولادتِ امام حسن مجتبی"),
    "SA25E4435": ("keep-merged-row", None, ["E0126", "E0029"],
                  "رحلتِ امام خمینی + شهادتِ آیت‌الله دستغیب"),
    "SAE70E9EC": ("keep-merged-row", None, ["E0047", "E0085"],
                  "شهادتِ آیت‌الله اشرفی اصفهانی + روز جهانی نابینایان"),
    "SB0CAD007": ("keep-merged-row", None, ["E0047", "E0085"],
                  "شهادتِ آیت‌الله اشرفی اصفهانی + روز جهانی نابینایان"),
    "SB889A638": ("keep-merged-row", None, ["E0383", "E0007", "E0100"],
                  "هجوم به فیضیه + عید نوروز + آغاز عملیات فتح‌المبین"),
    "SC44FB5BA": ("keep-merged-row", None, ["E0383", "E0007", "E0100"],
                  "هجوم به فیضیه + عید نوروز + آغاز عملیات فتح‌المبین"),
    "SD5409974": ("keep-merged-row", None, ["E0379", "E0455"],
                  "لغوِ امتیاز تنباکو + شهادتِ امام موسی کاظم"),
    "SE36B292D": ("keep-merged-row", None, ["E0383", "E0007", "E0100"],
                  "هجوم به فیضیه + عید نوروز + آغاز عملیات فتح‌المبین"),
    "SEF782279": ("keep-merged-row", None, ["E0126", "E0110"],
                  "رحلتِ امام خمینی + انتخابِ آیت‌الله خامنه‌ای"),
    "SF918DD6B": ("keep-merged-row", None, ["E0030", "E0326", "E0223"],
                  "شهادتِ آیت‌الله مفتح + روز وحدتِ حوزه و دانشگاه + روز جهان عاری از خشونت"),
}


def toggle(event_id: str, active: bool) -> int:
    """خاموش/روشن‌کردنِ یک تصمیم و بازتولیدِ فوریِ داده (بازگردانیِ قابلِ ردیابی)."""
    data = store.load_json(store.IDENTITY_REVIEWS_FILE, {"reviews": []})
    entry = next((r for r in data.get("reviews", []) if r.get("eventId") == event_id), None)
    if entry is None:
        print(f"تصمیمِ {event_id} در فایل نیست", file=sys.stderr)
        return 2
    entry["active"] = active
    store.write_json(store.IDENTITY_REVIEWS_FILE, data)
    events, occurrences = store.rebuild_from_revisions()
    store.save_history(events, occurrences)
    print(f"{event_id}: active={active} · events={len(events)} occurrences={len(occurrences)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="ثبت/بازتولیدِ تصمیم‌های هویتِ ردیفی")
    ap.add_argument("--disable", metavar="EVENT_ID", help="خاموش‌کردنِ یک تصمیم و بازگردانیِ داده")
    ap.add_argument("--enable", metavar="EVENT_ID", help="روشن‌کردنِ دوبارهٔ یک تصمیم")
    args = ap.parse_args()
    if args.disable:
        return toggle(args.disable, False)
    if args.enable:
        return toggle(args.enable, True)

    events = json.loads(store.EVENTS_FILE.read_text(encoding="utf-8"))["events"]
    occurrences = json.loads(store.OCCURRENCES_FILE.read_text(encoding="utf-8"))["occurrences"]
    catalog = {e["id"]: e for e in store.master_catalog()}
    by_event: dict[str, list[dict]] = {}
    for occ in occurrences:
        by_event.setdefault(occ["eventId"], []).append(occ)

    event_ids = {e["id"] for e in events}
    suspicious = {e["id"]: e for e in events if e.get("needsReview")}
    existing = {r["eventId"]: r for r in store.load_identity_review_entries()
                if r.get("eventId")}
    # اجرای دوباره پس از اعمالِ نگاشت هم باید پایدار باشد: هویتِ مپ‌شده دیگر
    # در داده نیست، اما شاهدِ تاریخی‌اش در فایلِ تصمیم باقی مانده است.
    missing = sorted(set(DECISIONS) - (set(suspicious) | set(existing)))
    extra = sorted(set(suspicious) - set(DECISIONS))
    if missing or extra:
        print(f"تصمیم‌ها با هویت‌های بازِ فعلی نمی‌خوانند؛ کم: {missing} اضافه: {extra}",
              file=sys.stderr)
        return 2

    reviews = []
    for eid in sorted(DECISIONS):
        decision, target, constituent_ids, basis = DECISIONS[eid]
        if eid not in event_ids and decision != "map":
            print(f"هویتِ حفظ‌شده در داده نیست: {eid}", file=sys.stderr)
            return 2
        occs = sorted(by_event.get(eid, []), key=lambda o: (o["year"], o["evidence"]["page"]))
        evidence = []
        seen = set()
        for occ in occs:
            key = (occ["evidence"]["revisionId"], occ["evidence"]["page"])
            if key in seen:
                continue
            seen.add(key)
            evidence.append({
                "revisionId": occ["evidence"]["revisionId"],
                "page": occ["evidence"]["page"],
                "year": occ["year"],
                "observedTitle": occ["observedTitle"],
            })
        if not evidence and existing.get(eid):
            evidence = existing[eid].get("evidence", [])
        constituents = []
        for cid in constituent_ids:
            if cid not in catalog:
                print(f"هویتِ کاتالوگیِ ناموجود: {cid}", file=sys.stderr)
                return 2
            constituents.append({"id": cid, "title": catalog[cid]["title"]})
        if decision == "map":
            if target != "E0460":
                print("نگاشتِ تازه باید با شاهدِ مستقل تأیید شود", file=sys.stderr)
                return 2
            reason = (f"{basis}. پنج ردیفِ پراکندهٔ همین رویداد در سال‌های مختلف به یک "
                      "هویتِ کاتالوگی نگاشت شدند؛ عنوانِ اصلیِ هر ردیف به‌عنوان شاهد حفظ می‌شود.")
        else:
            names = "؛ ".join(f"{c['id']} {c['title']}" for c in constituents)
            reason = (f"{basis}. PDF چند رویدادِ متفاوت را در یک سطر چاپ کرده و ترتیبِ "
                      f"واژه‌ها جابه‌جا شده است. اجزای قابلِ تشخیص: {names}. "
                      "ادغامِ خودکار انجام نشد؛ ردیف به‌عنوان شاهدِ چنده‌رویدادی حفظ می‌شود.")
        reviews.append({
            "eventId": eid,
            "active": True,
            "decision": decision,
            "target": target,
            "reason": reason,
            "constituents": constituents,
            "evidence": evidence,
            "reviewedBy": REVIEWED_BY,
            "reviewedAt": REVIEWED_AT,
        })

    store.write_json(OUT, {
        "generatedAt": REVIEWED_AT,
        "rule": "هیچ ادغامِ خودکاری؛ map فقط با شاهدِ عنوان/تاریخ؛ ردیفِ چسبیده حفظ می‌شود.",
        "reviews": reviews,
    })
    print(f"identity reviews: {len(reviews)} → {OUT.relative_to(ROOT)}")
    print("map:", sum(1 for r in reviews if r["decision"] == "map"),
          "· keep-merged-row:", sum(1 for r in reviews if r["decision"] == "keep-merged-row"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
