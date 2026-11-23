"""اعمالِ اصلاحیه‌های مستند روی جدول‌های رسمی ۱۴۰۴ و ۱۴۰۵.

قواعد:
  • فقط ردیفی تغییر می‌کند که عنوان/تعطیلیِ فعلی‌اش دقیقاً با «before» بخواند؛
    اگر نه، اسکریپت متوقف می‌شود تا اصلاحِ ناخواسته رخ ندهد.
  • اجرای دوباره idempotent است: ردیفی که هم‌اکنون با «after» می‌خواند رد می‌شود.
  • after.title == null یعنی ردیفِ بدونِ مناسبت حذف شود (رویدادها جابه‌جا شده‌اند).
  • شناسهٔ اصلاح در ردیف (`corrections`) می‌ماند تا تغییر قابل ردیابی باشد.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CORR = DATA / "official-corrections-1404-1405.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    corrections = load(CORR)["corrections"]
    by_year: dict[int, list[dict]] = {}
    for c in corrections:
        by_year.setdefault(c["year"], []).append(c)

    changed = 0
    for year, items in sorted(by_year.items()):
        path = DATA / f"official-calendar-{year}.json"
        doc = load(path)
        rows = doc["rows"]
        for c in items:
            idx = [i for i, r in enumerate(rows) if r["solar"] == c["date"]]
            if len(idx) != 1:
                print(f"خطا: {c['id']} — {len(idx)} ردیف با تاریخ {c['date']}", file=sys.stderr)
                return 2
            i = idx[0]
            row = rows[i]
            before, after = c["before"], c["after"]
            already = (
                (after["title"] is None and False)
                or (row.get("title") == after["title"] and row.get("holiday") == after["holiday"])
            )
            if already:
                continue
            if row.get("title") != before["title"] or row.get("holiday") != before["holiday"]:
                print(
                    f"خطا: {c['id']} با before نمی‌خواند.\n"
                    f"  فعلی: {row.get('title')!r} / {row.get('holiday')}\n"
                    f"  before: {before['title']!r} / {before['holiday']}",
                    file=sys.stderr,
                )
                return 3
            if after["title"] is None:
                rows.pop(i)
            else:
                row["title"] = after["title"]
                row["holiday"] = after["holiday"]
                ids = list(row.get("corrections", []))
                if c["id"] not in ids:
                    ids.append(c["id"])
                row["corrections"] = ids
            changed += 1
            print(f"{c['id']}: اعمال شد")
        dump(path, doc)
    print(f"اصلاحات اعمال‌شده: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
