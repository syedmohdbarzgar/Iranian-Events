#!/usr/bin/env python3
"""متادیتای اعتبار را از master به پک‌های همراهِ برنامه می‌برد.

هر ردیفِ پکِ فارسی با تاریخ/تقویم و عنوان به یک رویدادِ master وصل می‌شود؛ سپس
همان متادیتا با `id` به نسخه‌های انگلیسی/کردی همان ردیف می‌رسد. ردیفی که شاهدِ
master ندارد `unverified` می‌ماند و حذف نمی‌شود. این اسکریپت فقط سه فیلدِ شاهد را
اضافه/به‌روز می‌کند و عنوان یا تاریخِ پک را تغییر نمی‌دهد.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import event_normalize as norm  # noqa: E402

PACK_DIR = ROOT.parent / "app" / "src" / "main" / "assets" / "events" / "iran"
MASTER = ROOT / "data" / "events-master.json"
BASE_PACKS = ("solar", "lunar", "gregorian", "misc", "kurdish")
SYSTEM_CALENDAR = {"PERSIAN": "solar", "ISLAMIC": "lunar", "GREGORIAN": "gregorian"}
DATE_FIELD = {"solar": "solar_dates", "lunar": "lunar_dates", "gregorian": "gregorian_dates"}


def key(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", text or "")
    return norm.canon_key(text)


def tokens(text: str) -> set[str]:
    return norm.title_tokens(text)


def match_event(row: dict, events: list[dict]) -> dict | None:
    calendar = SYSTEM_CALENDAR.get(row.get("system"))
    if not calendar:
        return None
    month, day = row.get("month"), row.get("day")
    candidates = [
        e for e in events
        if e.get("calendar") == calendar and not e.get("excludeFromCalendar")
        and (not month or [month, day] in (e.get(DATE_FIELD[calendar]) or []))
    ]
    if not candidates:
        return None
    exact = [e for e in candidates if key(e["title"]) == key(row.get("event", ""))]
    pool = exact or candidates
    own = tokens(row.get("event", ""))
    scored = []
    for event in pool:
        other = tokens(event["title"])
        score = len(own & other) / min(len(own), len(other)) if own and other else 0
        scored.append((score, event))
    scored.sort(key=lambda pair: -pair[0])
    if not scored:
        return None
    best_score, best = scored[0]
    if exact or best_score >= 0.6:
        return best
    return None


def evidence_for(event: dict, row: dict, pack: str) -> dict:
    status = event.get("verificationStatus") or "unverified"
    if status == "verified":
        certainty = "confirmed"
    elif status == "partially_verified":
        certainty = "single_source"
    elif status == "traditional":
        certainty = "traditional"
    else:
        certainty = "unconfirmed"
    evidence = event.get("evidence") or {}
    return {
        "verificationStatus": status,
        "dateCertainty": certainty,
        "sourceRef": evidence.get("sourceRef") or f"events-master.json#{event['id']}",
        "sourceName": evidence.get("sourceName") or event.get("sourceName") or "کاتالوگ رویدادها",
    }


def fallback_meta(row: dict, pack: str) -> dict:
    traditional = row.get("category") == "KURDISH"
    return {
        "verificationStatus": "traditional" if traditional else "unverified",
        "dateCertainty": "traditional" if traditional else "unconfirmed",
        "sourceRef": f"app-pack:{pack}_events.json#{row.get('id')}",
        "sourceName": "پک فرهنگی کردی (بدون کاتالوگ)" if traditional else "پک همراه برنامه (بدون شاهد کاتالوگ)",
    }


def main() -> int:
    events = json.loads(MASTER.read_text(encoding="utf-8"))["events"]
    base_meta: dict[str, dict] = {}
    matched = 0
    for pack in BASE_PACKS:
        path = PACK_DIR / f"{pack}_events.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            event = match_event(row, events)
            meta = evidence_for(event, row, pack) if event else fallback_meta(row, pack)
            if event:
                matched += 1
            base_meta[f"{pack}:{row.get('id')}"] = meta

    base_rows: dict[str, dict[str, dict]] = {}
    for pack in BASE_PACKS:
        rows = json.loads((PACK_DIR / f"{pack}_events.json").read_text(encoding="utf-8"))
        base_rows[pack] = {row["id"]: row for row in rows}

    changed = 0
    for path in sorted(PACK_DIR.glob("*_events*.json")):
        pack = path.name.split("_events")[0]
        rows = json.loads(path.read_text(encoding="utf-8"))
        is_base = path.name == f"{pack}_events.json"
        out = []
        for row in rows:
            if not is_base and row.get("id") in base_rows.get(pack, {}):
                # ترجمه فقط `event` را عوض می‌کند؛ تاریخ/سال/تعطیلات/شاهد باید
                # بیت‌به‌بیت با پایه یکی بماند (گاردِ OfficialEventsAssetsTest).
                new = {**base_rows[pack][row["id"]], "event": row.get("event")}
            else:
                meta = base_meta.get(f"{pack}:{row.get('id')}")
                if not meta:
                    meta = fallback_meta(row, pack)
                new = {**row, **meta}
            if new != row:
                changed += 1
            out.append(new)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    statuses = {}
    for path in PACK_DIR.glob("*_events.json"):
        for row in json.loads(path.read_text(encoding="utf-8")):
            statuses[row.get("verificationStatus")] = statuses.get(row.get("verificationStatus"), 0) + 1
    print(f"app-assets: rows={sum(statuses.values())} matched={matched} changed={changed} statuses={statuses}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
