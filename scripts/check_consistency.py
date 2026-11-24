"""گزارشِ یکپارچگیِ دادهٔ تقویم — تکرارها، عنوان‌های چسبیده، پوششِ هر سال."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402

YEARS = range(1300, 1421)


def main() -> int:
    cat = engine.build_catalog()
    entries = cat["catalog"]
    counts = Counter(e["category"] for e in entries)
    per_year = {y: len(engine.generate(y, cat)["rows"]) for y in YEARS}

    # تکرار: یک دسته + تقویم + امضا + تاریخِ همان تقویم
    seen: dict[tuple, list[str]] = {}
    for e in entries:
        d = (e["lunar_dates"] if e["calendar"] == "lunar" else
             e["gregorian_dates"] if e["calendar"] == "gregorian" else e["solar_dates"])
        if not d:
            continue
        key = (e["category"], e["calendar"], engine.signature(e["title"]), d[0][0], d[0][1])
        seen.setdefault(key, []).append(e["title"])
    dupes = {k: v for k, v in seen.items() if len(v) > 1}

    merged_like = [e["title"] for e in entries
                   if " روز " in e["title"][6:] or " - " in e["title"] or e["title"].count(" و ") > 1]
    bad_dates = []
    for e in entries:
        for m, d in (e["solar_dates"] or []):
            if not (1 <= m <= 12 and 1 <= d <= engine.month_len(1400, m)):
                bad_dates.append((e["title"], m, d))
    inferred = sum(1 for y in YEARS if y not in {int(p.stem.split("-")[-1]) for p in (ROOT / "data").glob("official-calendar-*.json")})

    manifest_path = ROOT / "reports" / "audit" / "data-manifest.json"
    version = (json.loads(manifest_path.read_text(encoding="utf-8"))["dataVersion"]
               if manifest_path.exists() else "نامشخص")
    lines = [
        "# گزارشِ یکپارچگیِ دادهٔ تقویم",
        "",
        f"- داده: **{version}** (همان manifest انتشار)",
        f"- سال‌های بررسی‌شده: {min(YEARS)}–{max(YEARS)} ({len(list(YEARS))} سال)",
        f"- سال‌های دارای جدولِ رسمی: {min(int(p.stem.split('-')[-1]) for p in (ROOT / 'data').glob('official-calendar-*.json'))}–"
        f"{max(int(p.stem.split('-')[-1]) for p in (ROOT / 'data').glob('official-calendar-*.json'))}",
        f"- سال‌های استنباطی: {inferred}",
        f"- رویدادهای کاتالوگ: {len(entries)} — " + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())),
        "",
        "## پوششِ هر سال",
        "",
        "| سال | رویداد | وضعیت |",
        "|---|---|---|",
    ]
    official_years = {int(p.stem.split("-")[-1]) for p in (ROOT / "data").glob("official-calendar-*.json")}
    for y in YEARS:
        lines.append(f"| {y} | {per_year[y]} | {'جدول رسمی' if y in official_years else 'استنباط قاعده‌محور'} |")
    lines += [
        "",
        "## یافته‌ها",
        "",
        f"- تکرارِ باقی‌مانده (هم‌دسته/هم‌تقویم/هم‌امضا/هم‌تاریخ): **{len(dupes)}**",
        f"- عنوان‌های مشکوک به چندرویدادی: **{len(merged_like)}**",
        f"- تاریخ‌های نامعتبر: **{len(bad_dates)}**",
        f"- کمترین پوششِ سالانه: **{min(per_year.values())}** رویداد ({min(per_year, key=per_year.get)})",
        f"- بیشترین پوششِ سالانه: **{max(per_year.values())}** رویداد ({max(per_year, key=per_year.get)})",
        "",
        "## نمونهٔ تکرارهای باقی‌مانده",
        "",
    ]
    for k, titles in list(dupes.items())[:15]:
        lines.append(f"- `{k[0]}/{k[1]}/{k[2]}`: " + " · ".join(titles[:3]))
    lines += ["", "## نمونهٔ عنوان‌های مشکوک", ""]
    for t in merged_like[:15]:
        lines.append(f"- {t}")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "consistency.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"consistency.md: years={len(list(YEARS))} events={len(entries)} dupes={len(dupes)} "
          f"merged_like={len(merged_like)} min={min(per_year.values())} (year {min(per_year, key=per_year.get)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
