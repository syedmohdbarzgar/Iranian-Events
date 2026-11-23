"""صحت‌سنجی تک‌به‌تکِ رویدادها فقط با ویکی‌پدیا.

برای هر رویداد یک جست‌وجوی سبک (opensearch) در ویکی‌پدیای فارسی انجام می‌شود؛
برای رویدادهای جهانی در نبودِ نتیجهٔ فارسی، ویکی‌پدیای انگلیسی.
خروجی: data/wikipedia-verification.json + reports/wikipedia-verification.md
"""
import argparse
import concurrent.futures
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_engine as engine  # noqa: E402

OUT = ROOT / "data" / "wikipedia-verification.json"
REPORT = ROOT / "reports" / "wikipedia-verification.md"
UA = "CalendarPlatform/1.0 (calendar data verification)"


def wiki_search(lang: str, text: str) -> tuple[str, str] | None:
    """جست‌وجوی صفحهٔ ویکی‌پدیا از مسیر HTML (API عمومی این شبکه ۴۲۹ می‌دهد)."""
    url = f"https://{lang}.wikipedia.org/w/index.php?" + urllib.parse.urlencode({"search": text})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 CalendarPlatformVerification"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                html = r.read().decode("utf-8", "ignore")
            m = re.search(r'<link rel="canonical" href="([^"]+)"', html)
            t = re.search(r"<title>(.*?)</title>", html, re.S)
            if m and t and "جستجو" not in t.group(1):
                title = re.sub(r"\s*-\s*ویکی‌پدیا.*$", "", t.group(1)).strip()
                return title, m.group(1)
            m = re.search(r'mw-search-result-heading[^>]*>\s*<a href="([^"]+)"[^>]*title="([^"]+)"', html, re.S)
            if m:
                return m.group(2), "https://" + lang + ".wikipedia.org" + m.group(1)
            return None
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(10 + 5 * attempt)
                continue
            time.sleep(3)
        except Exception:
            time.sleep(3)
    return None


PREFIX = ("شهادت", "ولادت", "رحلت", "وفات", "میلاد", "عید", "آغاز", "سالروز", "بزرگداشت",
          "روز", "شب", "درگذشت", "ارتحال", "بازگشت", "تشکیل", "تأسیس", "فتح", "عملیات",
          "انفجار", "حمله", "قیام", "پیروزی")
NOISE = ("حضرت", "امام", "آیت‌الله", "آیتاالله", "سید", "سلام‌الله", "علیها", "علیه", "السلام")


def clean_term(title: str) -> str:
    t = engine._norm(title)
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\b(?:ه\.?ق|ه\.?ش|هجری|قمری|شمسی)\b", " ", t)
    words = [w for w in t.split() if len(w) > 1]
    while words and words[0] in PREFIX:
        words.pop(0)
    core = [w for w in words if w not in NOISE and "سلام" not in w and not w.startswith("علیه")
            and "الله" not in w]
    return " ".join((core or words)[:4]) or t


def sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, engine._norm(a), engine._norm(b)).ratio()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    cat = engine.build_catalog()
    done = {}
    if OUT.exists():
        try:
            done = {r["title"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))}
        except Exception:
            done = {}
    entries = cat["catalog"]

    def work(e):
        title = e["title"]
        if title in done and done[title].get("status"):
            return done[title]
        term = clean_term(title)
        hit = wiki_search("fa", term)
        lang = "fa"
        if not hit and e["category"] == "international":
            hit = wiki_search("en", term)
            lang = "en"
        if not hit:
            return {"title": title, "category": e["category"],
                    "origin": (e.get("origin") or {}).get("label", ""), "page": "", "url": "",
                    "ratio": 0.0, "status": "not_found"}
        page, url = hit
        ratio = max(sim(title, page), sim(term, page))
        core = engine._norm(page) in engine._norm(title) or engine._norm(term) in engine._norm(page)
        status = "page_match" if ratio >= 0.5 or core else "weak_match"
        return {"title": title, "category": e["category"], "origin": (e.get("origin") or {}).get("label", ""),
                "page": page, "url": url, "ratio": round(ratio, 2), "status": status}

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for i, row in enumerate(pool.map(work, entries), 1):
            rows.append(row)
            done[row["title"]] = row
            if i % 15 == 0:
                OUT.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"[{i}/{len(entries)}] {row['title'][:40]} -> {row['status']}", flush=True)
            time.sleep(0.35)

    allrows = list(done.values())
    counts = {}
    for r in allrows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = ["# صحت‌سنجی ویکی‌پدیا — تک‌به‌تک", "",
             "هر رویداد کاتالوگ با یک جست‌وجوی ویکی‌پدیا (فارسی؛ برای رویدادهای جهانی در نبودِ صفحهٔ فارسی، انگلیسی) سنجیده شده است.",
             "معیار: صفحهٔ یافت‌شده و نسبتِ شباهتِ عنوان؛ «weak_match» یعنی صفحه‌ای هست ولی عنوان دور است.",
             "این گذار صفحه‌محور است؛ تأییدِ تاریخِ دقیق فقط برای لنگرهای مستند (پایین) انجام شده است.", "",
             "## خلاصه", ""]
    for k in ("page_match", "weak_match", "not_found"):
        lines.append(f"- {k}: **{counts.get(k, 0)}**")
    lines += ["", f"جمع: {len(allrows)} رویداد", "", "## جدول تک‌به‌تک", "",
              "| # | رویداد | دسته | اصل | صفحهٔ ویکی‌پدیا | شباهت | وضعیت |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(allrows, 1):
        page = f"[{r['page']}]({r['url']})" if r.get("url") else "—"
        lines.append(f"| {i} | {r['title'][:65]} | {r['category']} | {r['origin']} | {page} | "
                     f"{r['ratio']} | {r['status']} |")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT.write_text(json.dumps(allrows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("summary:", counts, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
