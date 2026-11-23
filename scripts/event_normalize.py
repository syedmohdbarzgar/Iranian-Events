"""یکسان‌سازیِ عنوان/تاریخِ رویدادها با پک‌های همراهِ برنامه.

پک‌های `app/src/main/assets/events/iran/*_events.json` دادهٔ **منتشرشدهٔ** برنامه‌اند و
تاریخ‌های قمری/شمسیِ آن‌ها با جدول‌های رسمی هم‌خوان است؛ در حالی که عنوان‌های استخراج‌شده
از PDF در `calendars-final` گاهی چند رویداد را چسبانده یا تاریخِ قمریِ ردیفِ همسایه را
برداشته‌اند. این ماژول یک کلیدِ معنایی می‌سازد تا هر رویداد به پکِ خودش برسد؛ خودِ پک
هیچ‌جا تغییر نمی‌کند و فقط مرجعِ تطبیق است.

هیچ‌کدام از این توابع در زمانِ اجرای برنامه صدا زده نمی‌شوند؛ ابزارِ ساخت/ممیزی‌اند.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import calendar_engine as engine

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT.parent
PACK_DIR = APP_ROOT / "app" / "src" / "main" / "assets" / "events" / "iran"
CORRECTIONS = ROOT / "data" / "event-corrections.json"

SYSTEM_CALENDAR = {"PERSIAN": "solar", "ISLAMIC": "lunar", "GREGORIAN": "gregorian"}

# واژه‌های افتخاری که هویتِ رویداد را عوض نمی‌کنند
_HONOR = tuple(sorted(engine.HONOR, key=len, reverse=True))
_DROP_WORDS = re.compile(
    r"\b(?:ه[‌.\s]*[شق]|هجری(?:\s*(?:شمسی|قمری))?|میلادی|ه\.?ق|ه\.?ش)\b")


def load_corrections() -> dict:
    if CORRECTIONS.exists():
        return json.loads(CORRECTIONS.read_text(encoding="utf-8"))
    return {"aliases": [], "date_overrides": [], "suppress": []}


def alias_title(title: str) -> str:
    """عنوان‌های چسبیده/به‌هم‌ریخته را به عنوانِ کانونیِ همان رویداد برمی‌گرداند."""
    ct = canon_key(title)
    for a in load_corrections().get("aliases", []):
        # مقایسهٔ خام کافی نیست: PDF پرانتز/نیم‌فاصله را جابه‌جا می‌کند
        # («روز جهانی قدس)آخرین جمعه...»). با کلیدِ کانونی هم بسنج.
        if a["match"] in title or canon_key(a["match"]) in ct:
            return a["title"]
    return title


def canon_key(title: str) -> str:
    """کلیدِ مقایسه: بدونِ افتخار، پرانتز، عدد، فاصله و نویسه‌های نگارشی.

    عمداً از `engine.clean_title` استفاده نمی‌شود: آن تابع «ه.ق) به روایتی» را از انتهای
    عنوان حذف می‌کند و دو روایتِ شهادت حضرت فاطمه (۱۳ جمادی‌الاول و ۳ جمادی‌الثانی) را
    یکی می‌کند. این‌جا فقط نویسه‌ها یکسان می‌شوند، نه معنای عنوان.
    """
    t = (title or "").replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه").replace("ة", "ه")
    for h in _HONOR:
        t = t.replace(h, " ")
    # گونه‌های بدونِ نیم‌فاصله/با فاصلهٔ متفاوتِ همان عبارت‌های افتخاری
    gap = r"[\s\u200c\u200d]*"
    t = re.sub(rf"سلام{gap}الله{gap}علیها", " ", t)
    t = re.sub(rf"سلام{gap}الله{gap}علیه(?!{gap}ها)", " ", t)
    t = re.sub(rf"صلی{gap}الله{gap}علیه{gap}و{gap}آله", " ", t)
    t = re.sub(rf"علیه{gap}السلام", " ", t)
    t = re.sub(rf"رحم[ةه]{gap}الله{gap}علیه", " ", t)
    t = re.sub(rf"قدس{gap}الله{gap}نفسه{gap}الزکیه", " ", t)
    # پرانتز حفظ می‌شود (متنش می‌ماند) چون «(به روایتی)» و «(روز دوم)» دو رویدادِ متفاوت‌اند؛
    # فقط نویسه‌های پرانتز/گیومه حذف می‌شوند، نه محتوای معنادارشان.
    t = t.replace("(", " ").replace(")", " ").replace("«", " ").replace("»", " ")
    # «امام علی» و «علی» یک شخص‌اند؛ وگرنه عنوانِ پک و کاتالوگ دوتا می‌شود.
    t = re.sub(rf"امام{gap}(?=علی)", " ", t)
    t = _DROP_WORDS.sub(" ", t)
    t = t.replace("منافقین", "منافقان").replace("منافقون", "منافقان")
    t = t.replace("شهیدان", "شهید").replace("شهدای", "شهید")
    t = t.replace("افتخار آفرین", "افتخارآفرین").replace("غرور آفرین", "افتخارآفرین")
    t = re.sub(r"[\d۰-۹]+", " ", t)
    t = re.sub(r"[^\w\u0600-\u06FF]+", "", t, flags=re.UNICODE)
    return t.replace("\u200c", "").replace("\u200d", "")


def entry_year(title: str) -> int | None:
    """سالِ وقوعِ صریح در عنوانِ پک (مثل «(1360 ه.ش)»)."""
    m = re.search(r"\(?\s*(1[23]\d{2})\s*(?:ه[‌.\s]*[شق])", title or "")
    return int(m.group(1)) if m else None


def load_packs() -> dict:
    """پک‌های پایهٔ ایران + فهرستِ شناسه‌ها (بدونِ نسخه‌های زبانی)."""
    packs = {}
    for name in ("solar", "lunar", "gregorian", "misc", "kurdish"):
        p = PACK_DIR / f"{name}_events.json"
        if p.exists():
            packs[name] = json.loads(p.read_text(encoding="utf-8"))
    return packs


def pack_index() -> dict[str, dict]:
    """کلیدِ کانونی → نخستین ردیفِ پک (پک‌ها مرجعِ تاریخ‌اند)."""
    index: dict[str, dict] = {}
    for name, rows in load_packs().items():
        for row in rows:
            key = canon_key(row.get("event", ""))
            if key and key not in index:
                index[key] = {**row, "_pack": name}
    return index


def pack_for(title: str, index: dict[str, dict] | None = None) -> dict | None:
    idx = index if index is not None else pack_index()
    return idx.get(canon_key(alias_title(title)))


def title_tokens(title: str) -> set[str]:
    return {w for w in engine._norm(title).split() if len(w) >= 3}


def same_event(a: str, b: str) -> bool:
    """اشتراکِ واژه‌های معنادار؛ برای تطبیقِ عنوانِ ردیفِ PDF با عنوانِ رویداد."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.6
