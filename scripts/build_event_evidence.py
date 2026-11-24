#!/usr/bin/env python3
"""ثبتِ شاهدِ قابلِ ردیابی برای هر رویداد در `events-master.json`.

این اسکریپت تاریخ یا عنوان را عوض نمی‌کند؛ فقط شاهدِ همان داده را از ردیف‌های
سالانه/کاتالوگ به رکورد می‌چسباند. «بررسی» این‌جا یعنی ثبتِ خودکارِ منبع، نه
تأییدِ مستقلِ تاریخی؛ برای همین `reviewKind` صریح است.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402
MASTER = DATA / "events-master.json"
REVIEWED_AT = date.today().isoformat()


def main() -> int:
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    rows_by_event: dict[str, list[dict]] = {}
    for path in sorted((DATA / "years").glob("*.json")):
        if not path.stem.isdigit():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("mode") != "data":
            continue
        for row in doc.get("rows", []):
            eid = row.get("eventId")
            if eid:
                rows_by_event.setdefault(eid, []).append(row)

    official_docs = {}
    for path in DATA.glob("official-calendar-*.json"):
        year = int(path.stem.split("-")[-1])
        official_docs[year] = json.loads(path.read_text(encoding="utf-8"))["rows"]

    def title_key(text: str) -> str:
        text = re.sub(r"\([^)]*\)", "", text or "")
        text = re.sub(r"[\d۰-۹]+", "", text)
        return re.sub(r"[،؛:().«»\-\s]+", "", text)[:35]

    missing = []
    for event in master["events"]:
        rows = rows_by_event.get(event["id"], [])
        official = [r for r in rows if r.get("page") and str(r.get("source", "")).startswith("official")]
        row = official[0] if official else (rows[0] if rows else None)
        if not official and event.get("verifiedYears"):
            # ردیفِ سالانه ممکن است به هویتِ هم‌عنوانِ دیگری وصل شده باشد؛ خودِ
            # جدولِ رسمیِ همان سال را با کلیدِ عنوان می‌گردیم و صفحه را نگه می‌داریم.
            key = title_key(event["title"])
            for y in sorted(event["verifiedYears"]):
                for candidate in official_docs.get(y, []):
                    if key and key in title_key(candidate.get("title", "")):
                        row = candidate
                        official = [candidate]
                        rows_by_event.setdefault(event["id"], []).append(candidate)
                        break
                if official:
                    break
        correction = event.get("correctionHistory") or {}
        if row is not None:
            witness = {
                "kind": "official-pdf-row" if official else "calendar-row",
                "documentId": (f"official-calendar-{row['solar'][0]}.json" if official
                               else f"data/years/{row['solar'][0]}.json"),
                "sourceRef": (row.get("sourceRef") or row.get("source") or
                              f"official-calendar-{row['solar'][0]}.json#page={row.get('page')}"),
                "page": row.get("page"),
                "witnessText": row.get("title"),
                "witnessDate": row.get("solar"),
                "year": row["solar"][0],
            }
            source_name = event.get("sourceName") or "تقویم رسمی ایران"
            source_url = event.get("sourceUrl") or ""
        elif correction:
            witness = {
                "kind": "identity-correction",
                "documentId": "data/event-identity-corrections.json",
                "sourceRef": f"event-identity-corrections.json#{event['id']}",
                "page": None,
                "witnessText": correction.get("source", ""),
                "witnessDate": None,
                "year": None,
            }
            source_name = "اصلاحیهٔ هویتیِ مستند"
            source_url = ""
        else:
            witness = {
                "kind": "catalog-only",
                "documentId": "data/events-master.json",
                "sourceRef": f"events-master.json#{event['id']}",
                "page": None,
                "witnessText": event["title"],
                "witnessDate": [event.get("month"), event.get("day")]
                if event.get("month") and event.get("day") else None,
                "year": event.get("first_year"),
            }
            source_name = event.get("sourceName") or "کاتالوگ"
            source_url = event.get("sourceUrl") or ""

        event["evidence"] = {
            **witness,
            "sourceName": source_name,
            "sourceUrl": source_url,
            "reviewedAt": REVIEWED_AT,
            "reviewKind": "automated-source-capture",
            "verificationStatus": event.get("verificationStatus"),
            "dateCertainty": ((row or {}).get("dateCertainty") if row else None) or (
                "confirmed" if event.get("verificationStatus") == "verified" else "unconfirmed"),
        }
        if not witness["sourceRef"] or not witness["witnessText"]:
            missing.append(event["id"])

    MASTER.write_text(json.dumps(master, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"evidence: events={len(master['events'])} missing={len(missing)} reviewedAt={REVIEWED_AT}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
