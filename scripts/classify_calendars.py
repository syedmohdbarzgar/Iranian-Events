"""دسته‌بندیِ تقویمیِ هر رویداد با مقایسهٔ سال‌ها (شمسی/قمری/میلادی).

منطق:
 ۱) نشانهٔ صریح در عنوان: «ه.ق» → قمری، «ه.ش» → شمسی، «میلادی» → میلادی.
 ۲) مقایسهٔ تاریخِ همان رویداد در سال‌های دارای PDF:
    ثابت‌ماندنِ (ماه، روز) شمسی و جابه‌جاییِ قمری → شمسی
    ثابت‌ماندنِ (ماه، روز) قمری و جابه‌جاییِ شمسی → قمری
    ثابت‌ماندنِ (ماه، روز) میلادی → میلادی
 ۳) در نبودِ دادهٔ کافی: پیش‌فرضِ دسته (مذهبی→قمری، جهانی→میلادی، بقیه→شمسی).
خروجی: data/calendar-classification.json + reports/calendar-comparison.md
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402

DATA = ROOT / "data"
TYPES = ("solar", "lunar", "gregorian")
PRIOR = {"religious": "lunar", "international": "gregorian", "cultural": "solar",
         "historical": "solar", "official": "solar"}


def marker(title: str) -> tuple[str, str] | None:
    t = engine._norm(title)
    if re.search(r"ه\s*[.٫]?\s*ق|هجری قمری", t):
        return "lunar", "نشانهٔ ه.ق در عنوان"
    if re.search(r"ه\s*[.٫]?\s*ش|هجری شمسی", t):
        return "solar", "نشانهٔ ه.ش در عنوان"
    if "میلادی" in t:
        return "gregorian", "نشانهٔ میلادی در عنوان"
    return None


def main() -> int:
    cat = engine.build_catalog()
    files = sorted(DATA.glob("official-calendar-*.json"))
    obs: dict[str, list[dict]] = defaultdict(list)
    for p in files:
        y = int(p.stem.split("-")[-1])
        for r in json.loads(p.read_text(encoding="utf-8"))["rows"]:
            if not r.get("title"):
                continue
            obs[engine.signature(r["title"])].append({
                "year": y, "title": r["title"],
                "solar": (r["solar"][1], r["solar"][2]),
                "lunar": tuple((r.get("lunar") or [0, 0, 0])[1:]),
                "greg": tuple((r.get("gregorian") or [0, 0, 0])[1:]),
            })

    result = {}
    rows = []
    for e in cat["catalog"]:
        sig = engine.signature(e["title"])
        o = obs.get(sig, [])
        m = marker(e["title"])
        solar_n = len({x["solar"] for x in o})
        lunar_n = len({x["lunar"] for x in o})
        greg_n = len({x["greg"] for x in o})

        def share(values):
            if not values:
                return 0.0
            return Counter(values).most_common(1)[0][1] / len(values)

        solar_share = share([x["solar"] for x in o])
        lunar_share = share([x["lunar"] for x in o])
        greg_share = share([x["greg"] for x in o])
        basis = ""
        if m:
            kind, basis = m
        elif len(o) >= 3 and solar_share >= 0.7 and lunar_share < 0.7:
            kind, basis = "solar", "تاریخ شمسی در بیشترِ سال‌ها ثابت، قمری متغیر"
        elif len(o) >= 3 and lunar_share >= 0.7 and solar_share < 0.7:
            kind, basis = "lunar", "تاریخ قمری در بیشترِ سال‌ها ثابت، شمسی متغیر"
        elif len(o) >= 3 and greg_share >= 0.7 and solar_share < 0.7:
            kind, basis = "gregorian", "تاریخ میلادی در بیشترِ سال‌ها ثابت"
        else:
            kind = e.get("calendar") if e.get("calendar") in TYPES else PRIOR.get(e["category"], "solar")
            basis = "پیش‌فرضِ تقویمِ کاتالوگ (دادهٔ کافی برای مقایسهٔ قاطع نبود)"
        conf = "بالا" if basis.startswith("نشانه") or (len(o) >= 3 and basis != "پیش‌فرضِ دسته (دادهٔ کافی برای مقایسه نبود)") else ("متوسط" if len(o) >= 2 else "پایین")
        result[e["title"]] = {"calendar": kind, "basis": basis, "confidence": conf,
                              "observations": len(o), "solar_variants": solar_n,
                              "lunar_variants": lunar_n, "greg_variants": greg_n}
        rows.append({"title": e["title"], "category": e["category"], **result[e["title"]],
                     "latest": {x["year"]: x for x in o[-2:]}})

    (DATA / "calendar-classification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    counts = Counter(v["calendar"] for v in result.values())
    lines = ["# مقایسهٔ سال‌ها و تعیین تقویمِ هر رویداد", "",
             "روش: نشانهٔ صریحِ «ه.ق»/«ه.ش» در عنوان + مقایسهٔ تاریخِ همان رویداد در سال‌های ۱۳۸۲–۱۴۰۶.",
             "اگر تاریخِ شمسی ثابت بماند و قمری جابه‌جا شود → شمسی؛ اگر قمری ثابت بماند و شمسی جابه‌جا شود → قمری؛",
             "اگر میلادی ثابت بماند → میلادی. در نبودِ دادهٔ کافی، پیش‌فرضِ دسته اعمال می‌شود.", "",
             "## خلاصه", ""]
    for t in TYPES:
        lines.append(f"- {t}: **{counts.get(t, 0)}**")
    lines += ["", "## نمونهٔ ۱۴۰۵ و ۱۴۰۶", "",
              "| رویداد | ۱۴۰۵ (شمسی / قمری) | ۱۴۰۶ (شمسی / قمری) | نوع | دلیل |",
              "|---|---|---|---|---|"]
    for r in rows:
        a = r["latest"].get(1405); b = r["latest"].get(1406)
        if not (a and b):
            continue
        lines.append(f"| {r['title'][:55]} | {a['solar'][0]}/{a['solar'][1]} · {a['lunar'][0]}/{a['lunar'][1]} | "
                     f"{b['solar'][0]}/{b['solar'][1]} · {b['lunar'][0]}/{b['lunar'][1]} | "
                     f"{r['calendar']} | {r['basis']} |")
    lines += ["", "## رویدادهای با نشانهٔ صریح در عنوان", ""]
    for r in rows:
        if r["basis"].startswith("نشانه"):
            lines.append(f"- {r['title'][:80]} → **{r['calendar']}** ({r['basis']})")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/calendar-comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("counts", dict(counts), "rows", len(rows), "report", ROOT / "reports/calendar-comparison.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
