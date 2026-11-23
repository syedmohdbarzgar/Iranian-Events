#!/usr/bin/env python3
"""استخراج ساختاریافتهٔ PDFهای مرجع (غیر از تقویم‌های سالانه) — هر فایل جداگانه.

سه گونه سند در پوشهٔ PDF هست:
  * «سال ۱۳xx هجری شمسی - ویکی‌شیعه» → مقالهٔ سال: آغاز/پایان سال و «وقایع مهم»؛
  * مصوبه/آیین‌نامه/فهرست روزها → فهرست‌های تاریخ‌دار یا بدون تاریخ؛
  * «تعطیلات و مناسبت‌های تقویم» → فهرست تعطیلات.

خروجی: extracted/ref/<slug>.json با فیلدهای:
  kind, year, first_day, last_day, dated_events[{solar,text}], key_lines[], chars
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_official import SOLAR_MONTHS, norm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEXT = ROOT / "extracted" / "text"
OUT = ROOT / "extracted" / "ref"

YEAR = re.compile(r"سال\s*(\d{4})\s*هجری")
DATED = re.compile(rf"(?P<text>.+?)\s+(?P<d>\d{{1,2}})\s+(?P<m>{'|'.join(SOLAR_MONTHS)})\s*$")
FIRST = re.compile(r"روز نخست سال.*?مصادف است با(?P<body>.{0,160})", re.S)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for path in sorted(TEXT.glob("*.txt")):
        if path.name.startswith("Calendar-") or path.name == "_index.json":
            continue
        raw = path.read_text(encoding="utf-8")
        lines = [norm(l) for l in raw.split("\n")]
        text = "\n".join(l for l in lines if l)
        m = YEAR.search(text)
        year = int(m.group(1)) if m else None
        if year is None:
            m2 = re.search(r"سال\s*(\d{4})", text)
            year = int(m2.group(1)) if m2 else None

        kind = "wiki-year" if "ویکی" in path.name else "reference"
        if "تعطیلات" in path.name:
            kind = "holidays-list"
        if "مصوبه" in path.name or "آیین" in path.name or "نامگذاری" in path.name:
            kind = "regulation"

        dated = []
        for line in lines:
            mm = DATED.match(line)
            if mm and len(mm.group("text")) > 6:
                dated.append(
                    {
                        "month": SOLAR_MONTHS.index(mm.group("m")) + 1,
                        "day": int(mm.group("d")),
                        "text": mm.group("text").strip(),
                    }
                )
        fm = FIRST.search(text)
        first_day = norm(fm.group("body"))[:160] if fm else ""
        last = re.search(r"آخرین روز سال.{0,200}", text, re.S)
        key_lines = [l for l in lines if 10 < len(l) < 160][:40]

        data = {
            "file": path.name.replace(".txt", ".pdf"),
            "slug": path.stem,
            "kind": kind,
            "year": year,
            "chars": len(raw),
            "first_day": first_day,
            "last_day": norm(last.group(0))[:200] if last else "",
            "dated_events": dated[:400],
            "key_lines": key_lines,
        }
        (OUT / f"{path.stem}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({"slug": path.stem, "kind": kind, "year": year, "dated": len(dated)})
        print(f"{kind:13s} year={str(year):5s} dated={len(dated):3d}  {path.name[:60]}")
    (OUT / "_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"reference docs: {len(index)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
