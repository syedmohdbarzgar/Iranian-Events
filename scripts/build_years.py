"""ساختِ خروجیِ هر سال از فایلِ یگانهٔ رویدادها + اعتبارسنجی.

خروجی: data/years/<year>.json برای ۱۳۰۰–۱۴۲۰ و data/years/index.json
گزارش: reports/year-build-validation.md
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402

DATA = ROOT / "data"
OUT = DATA / "years"
REPORT = ROOT / "reports" / "year-build-validation.md"
FIRST, LAST = 1300, 1420


def main() -> int:
    catalog = engine.build_catalog()
    OUT.mkdir(exist_ok=True)
    official_years = {int(p.stem.split("-")[-1]) for p in DATA.glob("official-calendar-*.json")}
    index, errors, counts = {}, [], {}
    quds_checks = []
    for y in range(FIRST, LAST + 1):
        res = engine.generate(y, catalog)
        rows = res["rows"]
        payload = {"year": y, "mode": res["mode"], "count": len(rows),
                   "droppedRows": res.get("droppedRows", 0), "addedRows": res.get("addedRows", 0),
                   "rows": rows}
        (OUT / f"{y}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        counts[y] = len(rows)
        index[y] = {"mode": res["mode"], "count": len(rows)}
        if y in official_years:
            raw = json.loads((DATA / f"official-calendar-{y}.json").read_text(encoding="utf-8"))
            if len(rows) + res.get("droppedRows", 0) < len(raw["rows"]):
                errors.append(f"{y}: تعدادِ سالِ داده {len(raw['rows'])} ≠ خروجی {len(rows)} − افزوده {res.get('addedRows', 0)} + حذف‌شده {res.get('droppedRows', 0)}")
        for r in rows:
            if not r.get("title") or not r.get("solar"):
                errors.append(f"{y}: ردیفِ ناقص")
                continue
            _, m, d = r["solar"]
            if not (1 <= m <= 12 and 1 <= d <= engine.month_len(y, m)):
                errors.append(f"{y}: تاریخ نامعتبر {m}/{d} — {r['title'][:40]}")
            try:
                g = date(*r["gregorian"])
                jy, jm, jd = engine.gregorian_to_jalali(g.year, g.month, g.day)
                if (jy, r["solar"][1], r["solar"][2]) != (jy, jm, jd):
                    errors.append(f"{y}: تبدیل میلادی/شمسی ناسازگار — {r['title'][:40]}")
            except Exception:
                errors.append(f"{y}: تاریخ میلادی نامعتبر — {r['title'][:40]}")
        q = next((r for r in rows if r["title"] == "روز جهانی قدس"), None)
        if q:
            g = date(*q["gregorian"])
            quds_checks.append((y, g.isoformat(), g.weekday() == 4))
            if g.weekday() != 4:
                errors.append(f"{y}: روز قدس جمعه نیست ({g.isoformat()})")

    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# اعتبارسنجی ساختِ سال‌ها", "",
             f"- بازه: {FIRST}–{LAST} ({len(counts)} سال)",
             f"- کمینه/بیشینهٔ رویداد در سال: **{min(counts.values())}** ({min(counts, key=counts.get)}) / "
             f"**{max(counts.values())}** ({max(counts, key=counts.get)})",
             f"- سال‌های دارای جدول: {len(official_years)}",
             f"- خطا: **{len(errors)}**",
             f"- بررسی روز قدس: {len(quds_checks)} سال", "",
             "## نمونهٔ روز قدس", "",
             "| سال | میلادی | جمعه؟ |", "|---|---|---|"]
    for y, g, ok in quds_checks[-10:]:
        lines.append(f"| {y} | {g} | {'✓' if ok else '✗'} |")
    if errors:
        lines += ["", "## خطاها", ""] + [f"- {e}" for e in errors[:200]]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"years: {len(counts)} files, errors={len(errors)}, min={min(counts.values())}, max={max(counts.values())}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
