"""مدلِ تاریخِ رویداد — هویت، وقوعِ سالانه، نسخهٔ تقویم و تاریخچهٔ تغییرات.

سه موجودیتِ اصلی (فاز ۱ چک‌لیست):

* ``Event``            هویتِ اصلیِ رویداد و اطلاعاتِ عمومیِ آن؛
* ``EventOccurrence``  وقوعِ رویداد در یک سالِ مشخص با شاهدِ همان سال؛
* ``CalendarRevision`` نسخهٔ مستقلِ تقویمِ یک سال (هشِ PDF، روشِ استخراج، وضعیتِ تأیید).

قاعدهٔ بنیادین: وقوع فقط از ردیفِ **مشاهده‌شده** در یک نسخهٔ تأییدشده ساخته می‌شود.
هیچ وقوعی برای سالی که سند ندارد ساخته نمی‌شود؛ خروجیِ قاعده‌محورِ
``data/years`` هرگز وارد این مدل نمی‌شود.

وقوع‌ها و هویت‌ها از نسخه‌های تأییدشده **بازتولید** می‌شوند؛ بنابراین
``audit_history.py`` می‌تواند یک‌به‌یک بررسی کند که دادهٔ منتشرشده با شاهدها
یکی است و کسی دستی آن را تغییر نداده است.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# کنسولِ ویندوز گاهی cp1252 است و چاپِ فارسی را می‌شکند؛ خروجیِ ابزارها UTF-8 است.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - جریانِ غیرقابل‌تنظیم
        pass

import calendar_engine as engine  # noqa: E402
import event_normalize  # noqa: E402

DATA = ROOT / "data"
HISTORY_DIR = DATA / "history"
REVISION_DIR = HISTORY_DIR / "revisions"
EVENTS_FILE = HISTORY_DIR / "events.json"
OCCURRENCES_FILE = HISTORY_DIR / "occurrences.json"
REVISIONS_FILE = REVISION_DIR / "index.json"
CHANGELOG_FILE = HISTORY_DIR / "changelog.json"
IDENTITY_REVIEWS_FILE = HISTORY_DIR / "identity-reviews.json"
REVIEW_DIR = DATA / "review"
CHANGES_DIR = REVIEW_DIR / "changes"
INGEST_DIR = REVIEW_DIR / "ingest"

APPROVED_STATES = {"approved"}
REVIEW_DECISIONS = {"keep-merged-row", "keep-garbled-row", "map"}
EVIDENCE_KIND = "official-pdf-row"
BASELINE_ACTOR = "baseline:parse_official"
BASELINE_AT = "2026-11-24T00:00:00Z"
HEADER_ONLY = re.compile(
    r"[\d\s۰-۹]*(?:چهارشنبه|پنجشنبه|سه‌شنبه|یکشنبه|دوشنبه|شنبه)?[\d\s۰-۹]*"
)


# ───────────────────────────── ابزارِ فایل/زمان ─────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def empty_history() -> dict:
    return {"events": [], "occurrences": [], "revisions": [], "changelog": []}


def load_history() -> dict:
    return {
        "events": load_json(EVENTS_FILE, {"events": []}).get("events", []),
        "occurrences": load_json(OCCURRENCES_FILE, {"occurrences": []}).get("occurrences", []),
        "revisions": load_json(REVISIONS_FILE, {"revisions": []}).get("revisions", []),
        "changelog": load_json(CHANGELOG_FILE, {"entries": []}).get("entries", []),
    }


def load_identity_review_entries() -> list[dict]:
    """تصمیم‌های ثبت‌شدهٔ بازبینیِ هویت (فایلِ قابلِ ردیابی، مستقل از دادهٔ مشتق‌شده)."""
    data = load_json(IDENTITY_REVIEWS_FILE, {"reviews": []})
    return list(data.get("reviews", [])) if isinstance(data, dict) else []


def load_identity_reviews() -> dict[str, dict]:
    return {r["eventId"]: r for r in load_identity_review_entries()
            if r.get("eventId")}


def save_history(events: list[dict], occurrences: list[dict]) -> None:
    write_json(EVENTS_FILE, {
        "generatedAt": now_iso(),
        "counts": {
            "events": len(events),
            "occurrences": len(occurrences),
            "witnessedEvents": sum(1 for e in events if e.get("observedYears")),
        },
        "rule": "هر وقوع فقط با شاهدِ ردیفِ یک نسخهٔ تأییدشده ساخته می‌شود.",
        "events": events,
    })
    write_json(OCCURRENCES_FILE, {
        "generatedAt": now_iso(),
        "counts": {"occurrences": len(occurrences)},
        "occurrences": occurrences,
    })


def save_revisions(revisions: list[dict]) -> None:
    ordered = sorted(revisions, key=lambda r: (r["year"], r.get("approvedAt") or "", r["id"]))
    write_json(REVISIONS_FILE, {"revisions": ordered})


def save_changelog(entries: list[dict]) -> None:
    write_json(CHANGELOG_FILE, {"kind": "append-only", "entries": entries})


# ───────────────────────────── کلید/تطبیق ─────────────────────────────

@lru_cache(maxsize=50000)
def clean_observed(title: str) -> str:
    """عنوانِ چاپی، بدونِ زوائدِ ستون‌های PDF (برای نمایش)."""
    t = engine.clean_title(event_normalize.alias_title(title or ""))
    return re.sub(r"\s+", " ", t).strip()


@lru_cache(maxsize=50000)
def display_clean(title: str) -> str:
    """پاک‌سازیِ املا بدونِ اعمالِ alias؛ عنوانِ هویت را جابه‌جا نمی‌کند.

    نشانه‌های چاپی (نه معنایی) حذف می‌شوند تا مقایسهٔ دو استخراجِ متفاوت از
    یک PDF، «تغییرِ عنوان» جعلی نسازد: ``(تعطیل)``، ``ه‍.ش``، ``هو ش``، ``ه.ق``.
    """
    t = engine.clean_title(title or "")
    t = re.sub(r"[\\(\\{]\\s*تعطیل\\s*[\\)\\}]", " ", t)
    t = re.sub(r"(?<![\u0600-\u06FF])ه(?:و\s+|[\u200c\u200d.\s]+)[شق](?![\u0600-\u06FF])", " ", t)
    t = re.sub(r"(?<![\u0600-\u06FF])تعطیل(?![\u0600-\u06FF])", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -،.؛:()")
    return t


@lru_cache(maxsize=50000)
def identity_key(title: str) -> str:
    """کلیدِ کانونیِ هویت (بدونِ شماره/سال/افتخار) برای ادغامِ املاها.

    عمداً ``alias_title`` اعمال نمی‌شود: اصلاحیه‌ها عنوان‌های *چسبیده* را به رویدادِ
    درست می‌رسانند، اما اگر در ساختِ کلید هم اعمال شوند «آغاز نوروز» و «عید نوروز»
    یک هویت می‌شوند و دو رویدادِ مستقل با هم قاطی می‌شوند.
    """
    return event_normalize.canon_key(display_clean(title))


def synthetic_event_id(key: str) -> str:
    return "S" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8].upper()


def compare_text(title: str) -> str:
    """متنِ مقایسه‌ای برای شباهتِ عنوان (ارقام حفظ می‌شوند)."""
    t = display_clean(title)
    t = t.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه").replace("ة", "ه")
    t = re.sub(r"[\u200c\u200d\u200e\u200f]", "", t)
    t = re.sub(r"[«»\"'()\[\]{}،,؛;:.!?؟…\-–—]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def row_is_event(title: str) -> bool:
    t = (title or "").strip()
    if len(re.findall(r"[آ-یءأإؤئ]", t)) < 2:
        return False
    if HEADER_ONLY.fullmatch(t):
        return False
    return True


def master_catalog() -> list[dict]:
    """کاتالوگِ رسمیِ ۵۰۳ رویداد؛ تنها منبعِ عنوان/دسته/اصلِ هویت‌های کاتالوگی."""
    return engine.build_catalog()["catalog"]


class CatalogMatcher:
    """تطبیقِ ردیفِ PDF با هویتِ کاتالوگ، با کلیدهای پیش‌محاسبه‌شده.

    ترتیب: تطبیقِ کانونی → عنوانِ کاملِ موجود در ردیف (حداقل پوشش ۵۵٪) →
    تطبیقِ محافظه‌کارانهٔ موتور (فقط ردیف‌های کوتاه) → هویتِ ردیف.

    ابهامِ عنوان‌های تکراری (چهار «عید نوروز»، دو «شب قدر»، …) با تاریخِ همان
    ردیف، سالِ مشاهده و شباهتِ عنوان حل می‌شود؛ ابهامِ باقی‌مانده = هویتِ ردیف،
    نه تطبیقِ غلط. ردیفِ بلندِ چسبیده هرگز به یک رویدادِ تنها نسبت داده نمی‌شود.
    """

    MIN_CONTAINED = 7
    MIN_COVER = 0.55
    MAX_FUZZY_LEN = 60

    def __init__(self, catalog: list[dict] | None = None):
        self.catalog = catalog if catalog is not None else master_catalog()
        self.by_id = {e["id"]: e for e in self.catalog}
        self.keys: list[tuple[str, dict]] = []
        seen: set[str] = set()
        for e in self.catalog:
            if e.get("excludeFromCalendar"):
                continue
            k = identity_key(e.get("title", ""))
            if len(k) >= 4 and k not in seen:
                seen.add(k)
                self.keys.append((k, e))
        self.keys.sort(key=lambda x: -len(x[0]))
        self.exact: dict[str, list[dict]] = {}
        self.alias_exact: dict[str, list[dict]] = {}
        for e in self.catalog:
            if e.get("excludeFromCalendar"):
                continue
            self.exact.setdefault(identity_key(e.get("title", "")), []).append(e)
            ak = event_normalize.canon_key(clean_observed(e.get("title", "")))
            if ak:
                self.alias_exact.setdefault(ak, []).append(e)

    @staticmethod
    def _date_tokens(row: dict) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for name, key in (("solar", "solar"), ("lunar", "lunar"), ("gregorian", "gregorian")):
            val = row.get(key) or [None, None, None]
            if len(val) == 3 and val[1] is not None and val[2] is not None:
                out[name] = (int(val[1]), int(val[2]))
        return out

    def _pick(self, cands: list[dict], row: dict | None, title: str) -> dict:
        if len(cands) == 1:
            return cands[0]
        pool = list(cands)
        if row:
            tokens = self._date_tokens(row)
            dated = []
            for ev in pool:
                for key, (m, d) in tokens.items():
                    if [m, d] in (ev.get(f"{key}_dates") or []):
                        dated.append(ev)
                        break
            if dated:
                pool = dated
        if row:
            year = int((row.get("solar") or [None])[0] or 0)
            if year:
                in_years = [e for e in pool if year in (e.get("years") or [])]
                if in_years:
                    pool = in_years
        clean = compare_text(title)
        pool.sort(key=lambda e: (
            -difflib.SequenceMatcher(None, clean, compare_text(e.get("title", ""))).ratio(),
            e["id"]))
        return pool[0]

    def match(self, title: str, row: dict | None = None) -> list[tuple[dict, str, float]]:
        cleaned = clean_observed(title)
        key = identity_key(title)
        if not key:
            return []

        exact = self.exact.get(key) or []
        if exact:
            return [(self._pick(exact, row, title), "exact", 1.0)]

        found: list[tuple[dict, str, float]] = []
        used: list[str] = []
        chosen_keys: set[str] = set()
        groups: dict[str, list[dict]] = {}
        for ck, ev in self.keys:
            if len(ck) < self.MIN_CONTAINED or ck not in key:
                continue
            groups.setdefault(ck, []).append(ev)
        for ck in sorted(groups, key=len, reverse=True):
            if any(ck in other or other in ck for other in used):
                continue
            used.append(ck)
            chosen_keys.add(ck)
            found.append((self._pick(groups[ck], row, title), "contained", 0.8))
        if found:
            cover = sum(len(k) for k in used) / len(key)
            return found if cover >= self.MIN_COVER else []

        alias = self.alias_exact.get(event_normalize.canon_key(cleaned)) or []
        if alias:
            return [(self._pick(alias, row, title), "alias", 0.85)]

        if len(cleaned) <= self.MAX_FUZZY_LEN:
            ev = engine.match_catalog(cleaned, self.catalog)
            if ev is not None and not ev.get("excludeFromCalendar"):
                return [(ev, "fuzzy", 0.75)]

        row_ev = {
            "id": synthetic_event_id(key),
            "title": cleaned,
            "category": engine.categorize({"title": cleaned, "calendar": "unresolved"}),
            "calendar": "unresolved",
            "recurrenceType": None,
            "origin": None,
            "verificationStatus": "partially_verified",
            "_rowIdentity": True,
        }
        return [(row_ev, "row", 1.0)]


# ───────────────────────────── نسخه‌ها ─────────────────────────────

def revision_id(year: int, document_sha: str) -> str:
    return f"R-{year}-{document_sha[:8]}"


def load_revision_rows(rev: dict) -> list[dict]:
    path = REVISION_DIR / f"{rev['id']}.json"
    if not path.exists():
        return []
    return load_json(path, {}).get("rows", [])


def save_revision_rows(rev_id: str, year: int, rows: list[dict], source: dict | None = None) -> Path:
    path = REVISION_DIR / f"{rev_id}.json"
    write_json(path, {"revisionId": rev_id, "year": year, "source": source or {}, "rows": rows})
    return path


def active_revisions(revisions: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for rev in revisions:
        if rev.get("state") not in APPROVED_STATES:
            continue
        cur = out.get(rev["year"])
        if cur is None or (rev.get("approvedAt") or "", rev["id"]) > (cur.get("approvedAt") or "", cur["id"]):
            out[rev["year"]] = rev
    return out


def revision_documents(revisions: list[dict]) -> dict[int, dict]:
    """سال → سندِ نسخهٔ فعال (برای نمایش «سند بررسی شد»)."""
    return {y: r["document"] for y, r in active_revisions(revisions).items()}


# ───────────────────────────── استخراج/بازتولید ─────────────────────────────

def _date_of(row: dict) -> dict:
    solar = [int(x) if x is not None else None for x in (row.get("solar") or [None, None, None])]
    greg = [int(x) if x is not None else None for x in (row.get("gregorian") or [None, None, None])]
    lunar = [int(x) if x is not None else None for x in (row.get("lunar") or [None, None, None])]
    derived = row.get("derived") or []
    return {
        "solar": solar,
        "gregorian": greg,
        "lunar": lunar,
        "approxLunar": bool("lunar" in derived) or lunar[1] is None,
    }


def _origin(ev: dict) -> dict:
    """تاریخِ اصل/اعلام را از کاتالوگ جدا نگه می‌دارد؛ برای هویتِ ردیف سند نیست."""
    origin = ev.get("origin") or {}
    if origin:
        return {
            "kind": origin.get("kind") or "unrecorded",
            "label": origin.get("label") or "",
            "date": None,
            "note": origin.get("note") or "",
            "sourceRef": origin.get("source") or "",
            "certainty": "documented" if origin.get("source") else "unconfirmed",
        }
    return {
        "kind": "unrecorded",
        "label": "بدونِ سندِ اصل",
        "date": None,
        "note": "هویت از ردیفِ تقویم ساخته شده؛ تاریخِ ایجاد/تصویب در دست نیست.",
        "sourceRef": "",
        "certainty": "unknown",
    }


def derive(events_catalog: list[dict], revisions: list[dict],
           rows_by_revision: dict[str, list[dict]],
           identity_reviews: dict[str, dict] | None = None
           ) -> tuple[list[dict], list[dict]]:
    """وقوع‌ها و هویت‌ها را فقط از نسخه‌های فعال (تأییدشده) بازمی‌سازد.

    ``identity_reviews`` تصمیمِ انسانیِ ثبت‌شده برای هویت‌های ردیفی است:
    ``map`` فقط وقتی اعمال می‌شود که شاهد و علت در همان فایل باشد؛ ``keep``
    هویت را حفظ می‌کند و فقط وضعیتِ بازبینی را از «باز» به «مستند» می‌برد.
    هیچ ادغامِ خودکاری انجام نمی‌شود.
    """
    matcher = CatalogMatcher(events_catalog)
    by_id = {e["id"]: e for e in events_catalog}
    reviews = load_identity_reviews() if identity_reviews is None else identity_reviews
    reviews = {k: v for k, v in reviews.items() if v.get("active", True)}
    active = active_revisions(revisions)
    occurrences: list[dict] = []
    observed: dict[str, set[str]] = {}
    all_events: dict[str, dict] = {}

    for year in sorted(active):
        rev = active[year]
        rows = rows_by_revision.get(rev["id"], [])
        used_sigs: set[tuple[str, int, int, str]] = set()
        for pos, row in enumerate(sorted(rows, key=lambda r: (
                (r.get("solar") or [0, 0, 0])[1], (r.get("solar") or [0, 0, 0])[2],
                r.get("title", "")))):
            raw = row.get("title", "")
            if not row_is_event(raw):
                continue
            matches = matcher.match(raw, row)
            if not matches:
                continue
            shared = len(matches) > 1
            for ev, kind, confidence in matches:
                eid = ev["id"]
                review = reviews.get(eid)
                if review and review.get("decision") == "map":
                    target = review.get("target")
                    if not target or target not in by_id:
                        # تصمیمِ ناقص هرگز به ادغامِ خودکار تبدیل نمی‌شود.
                        review = None
                    else:
                        eid = target
                        ev = by_id[target]
                if eid in by_id and by_id[eid].get("excludeFromCalendar"):
                    continue
                date = _date_of(row)
                m, d = date["solar"][1] or 0, date["solar"][2] or 0
                sig = (eid, m, d, identity_key(raw))
                if sig in used_sigs:
                    continue
                used_sigs.add(sig)
                seq = 1 + sum(1 for o in occurrences
                              if o["eventId"] == eid and o["year"] == year
                              and o["date"]["solar"][1:] == [m, d])
                occ = {
                    "id": f"O-{year}-{eid}-{m:02d}{d:02d}-{seq}",
                    "eventId": eid,
                    "year": year,
                    "date": date,
                    "observedTitle": raw,
                    "description": row.get("description"),
                    "holiday": bool(row.get("holiday")),
                    "match": {
                        "kind": kind,
                        "confidence": confidence,
                        "sharedRow": shared,
                        "rowIndex": pos,
                    },
                    "verification": {
                        "status": (by_id.get(eid, {}).get("verificationStatus")
                                   if eid in by_id else "partially_verified"),
                        "dateCertainty": "unconfirmed",
                    },
                    "evidence": {
                        "kind": EVIDENCE_KIND,
                        "revisionId": rev["id"],
                        "documentId": rev["document"].get("file"),
                        "documentSha256": rev["document"].get("sha256"),
                        "page": row.get("page"),
                        "sourceRef": f"{rev['document'].get('file')}#page={row.get('page')}",
                        "bbox": row.get("bbox"),
                        "method": rev["extraction"].get("method"),
                        "extractedAt": rev["extraction"].get("extractedAt"),
                    },
                }
                occurrences.append(occ)
                observed.setdefault(eid, set()).add(raw)
                info = all_events.get(eid)
                if info is None:
                    info = {
                        "id": eid,
                        "canonicalTitle": ev.get("title") or clean_observed(raw),
                        "aliases": [],
                        "identityKind": "row" if ev.get("_rowIdentity") else "catalog",
                        "category": ev.get("category") or "official",
                        "calendar": ev.get("calendar") or "unresolved",
                        "recurrenceType": ev.get("recurrenceType"),
                        "established": _origin(ev),
                        "verificationStatus": ev.get("verificationStatus") or "partially_verified",
                        "notes": [],
                    }
                    all_events[eid] = info

    # هویت‌های کاتالوگ حتی بدونِ وقوع در داده می‌مانند تا «دیده نشدن» صادقانه نمایش داده شود.
    for ev in events_catalog:
        if ev["id"] not in all_events and not ev.get("excludeFromCalendar"):
            all_events[ev["id"]] = {
                "id": ev["id"],
                "canonicalTitle": ev.get("title", ""),
                "aliases": [],
                "identityKind": "catalog",
                "category": ev.get("category") or "official",
                "calendar": ev.get("calendar") or "unresolved",
                "recurrenceType": ev.get("recurrenceType"),
                "established": _origin(ev),
                "verificationStatus": ev.get("verificationStatus") or "unverified",
                "notes": [],
            }

    for eid, info in all_events.items():
        mine = sorted([o for o in occurrences if o["eventId"] == eid],
                      key=lambda o: (o["year"], o["date"]["solar"][1] or 0, o["date"]["solar"][2] or 0))
        info["observedYears"] = sorted({o["year"] for o in mine})
        info["occurrenceCount"] = len(mine)
        info["aliases"] = sorted(observed.get(eid, set()))
        if mine:
            first = mine[0]
            info["firstObservedYear"] = first["year"]
            info["firstRecordedDate"] = {
                "solar": first["date"]["solar"],
                "gregorian": first["date"]["gregorian"],
                "page": first["evidence"]["page"],
                "revisionId": first["evidence"]["revisionId"],
                "sourceRef": first["evidence"]["sourceRef"],
            }
        else:
            info["firstObservedYear"] = None
            info["firstRecordedDate"] = None
        info["needsReview"] = bool(
            info["identityKind"] == "row"
            and (len(info["canonicalTitle"]) > 90 or any(o["match"]["sharedRow"] for o in mine))
        )
        review = reviews.get(eid)
        if review and review.get("decision") in {"keep-merged-row", "keep-garbled-row"}:
            info["review"] = {
                "decision": review["decision"],
                "reason": review.get("reason", ""),
                "evidence": review.get("evidence", []),
                "constituents": review.get("constituents", []),
                "reviewedBy": review.get("reviewedBy"),
                "reviewedAt": review.get("reviewedAt"),
                "approval": review.get("approval"),
            }
            info["needsReview"] = False

    events = sorted(all_events.values(), key=lambda e: (
        0 if e["id"].startswith("E") else 1, e["id"]))
    occurrences.sort(key=lambda o: (o["year"], o["date"]["solar"][1] or 0,
                                    o["date"]["solar"][2] or 0, o["eventId"], o["id"]))
    return events, occurrences


def rebuild_from_revisions(changelog: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    history = load_history()
    revisions = history["revisions"]
    rows_by_revision = {rev["id"]: load_revision_rows(rev) for rev in revisions}
    return derive(master_catalog(), revisions, rows_by_revision)


# ───────────────────────────── اعتبارسنجی ─────────────────────────────

def _issue(code: str, severity: str, message: str, ref: str = "") -> dict:
    return {"code": code, "severity": severity, "message": message, "ref": ref}


def validate(history: dict, *, expected: tuple[list[dict], list[dict]] | None = None,
             pdf_dir: Path | None = None, check_pdf_hashes: bool = False,
             identity_reviews: list[dict] | None = None) -> list[dict]:
    """بررسیِ ساختاری و شاهد‌محور؛ خروجی فهرستِ اشکال با کدِ پایدار."""
    issues: list[dict] = []
    events, occurrences = history["events"], history["occurrences"]
    revisions, changelog = history["revisions"], history["changelog"]
    rev_by_id = {r["id"]: r for r in revisions}
    event_ids = {e["id"] for e in events}
    if len(event_ids) != len(events):
        issues.append(_issue("EVENT_DUPLICATE_ID", "error", "شناسهٔ تکراری در هویت‌ها"))

    # منشأ تأیید باید صادقانه باشد: مبنا هرگز خود را «تأیید انسانی» جا نمی‌زند.
    for rev in revisions:
        if rev.get("state") not in APPROVED_STATES:
            continue
        approval = rev.get("approval")
        if not isinstance(approval, dict):
            issues.append(_issue("REV_APPROVAL_MISSING", "error",
                                 "نسخهٔ تأییدشده منشأِ تأیید ندارد", rev["id"]))
            continue
        kind = approval.get("kind")
        if kind not in {"baseline", "human"}:
            issues.append(_issue("REV_APPROVAL_UNKNOWN", "error",
                                 f"منشأِ تأییدِ ناشناخته: {kind!r}", rev["id"]))
        if kind == "baseline":
            if rev.get("approvedBy") != BASELINE_ACTOR:
                issues.append(_issue("REV_BASELINE_ACTOR", "error",
                                     "نسخهٔ مبنا نامِ سازندهٔ مبنا را ندارد", rev["id"]))
            if (rev.get("extraction") or {}).get("sourceKind") != "baseline-official-json":
                issues.append(_issue("REV_BASELINE_SOURCE", "error",
                                     "نسخهٔ مبنا از منبعِ مبنا ساخته نشده", rev["id"]))
        elif kind == "human":
            if rev.get("approvedBy") in {None, "", BASELINE_ACTOR}:
                issues.append(_issue("REV_HUMAN_ACTOR", "error",
                                     "تأییدِ انسانی نامِ تأییدکننده ندارد", rev["id"]))
            if not approval.get("method"):
                issues.append(_issue("REV_HUMAN_METHOD", "error",
                                     "روشِ تأییدِ انسانی ثبت نشده", rev["id"]))
            if approval.get("method") == "review" and not rev.get("review"):
                issues.append(_issue("REV_HUMAN_NO_REVIEW", "error",
                                     "تأییدِ انسانی بدونِ رکوردِ تصمیم‌هاست", rev["id"]))

    for e in events:
        if not e.get("id") or not e.get("canonicalTitle"):
            issues.append(_issue("EVENT_INCOMPLETE", "error", "هویت بدونِ شناسه/عنوان", e.get("id", "")))
        years = e.get("observedYears") or []
        mine = [o for o in occurrences if o.get("eventId") == e["id"]]
        computed = sorted({o["year"] for o in mine})
        if years != computed:
            issues.append(_issue("EVENT_YEARS_MISMATCH", "error",
                                 f"{e['id']}: سال‌های مشاهده {years} ≠ وقوع‌ها {computed}", e["id"]))
        first = min(computed) if computed else None
        if e.get("firstObservedYear") != first:
            issues.append(_issue("EVENT_FIRST_OBSERVED_MISMATCH", "error",
                                 f"{e['id']}: نخستین مشاهده {e.get('firstObservedYear')} ≠ {first}", e["id"]))

    seen_occ: set[str] = set()
    for o in occurrences:
        oid = o.get("id", "")
        if oid in seen_occ:
            issues.append(_issue("OCC_DUPLICATE_ID", "error", "شناسهٔ تکراریِ وقوع", oid))
        seen_occ.add(oid)
        if o.get("eventId") not in event_ids:
            issues.append(_issue("OCC_EVENT_MISSING", "error", f"وقوع به هویتِ ناموجود: {o.get('eventId')}", oid))
        ev = o.get("evidence") or {}
        if not ev or ev.get("kind") != EVIDENCE_KIND:
            issues.append(_issue("OCC_NOT_WITNESSED", "error", "وقوع بدونِ شاهدِ ردیفِ PDF", oid))
            continue
        rev = rev_by_id.get(ev.get("revisionId"))
        if rev is None:
            issues.append(_issue("OCC_REVISION_MISSING", "error",
                                 f"نسخهٔ ناموجود: {ev.get('revisionId')}", oid))
            continue
        if rev.get("state") not in APPROVED_STATES:
            issues.append(_issue("OCC_REVISION_NOT_APPROVED", "error",
                                 f"نسخهٔ تأییدنشده: {rev['id']} ({rev.get('state')})", oid))
        if rev["year"] != o.get("year"):
            issues.append(_issue("OCC_YEAR_MISMATCH", "error",
                                 f"سالِ وقوع {o.get('year')} ≠ سالِ نسخه {rev['year']}", oid))
        if not ev.get("documentSha256") or not ev.get("page"):
            issues.append(_issue("OCC_EVIDENCE_MISSING", "warning",
                                 "شاهد صفحه/هشِ سند ندارد", oid))
        if ev.get("sourceRef", "") .startswith("events-master"):
            issues.append(_issue("OCC_PROJECTED", "error", "وقوع از کاتالوگ/قاعده آمده، نه PDF", oid))

    if check_pdf_hashes and pdf_dir is not None:
        for rev in revisions:
            document = rev["document"]
            stored = document.get("storedPath")
            path = (Path(stored) if Path(stored).is_absolute() else ROOT / stored) if stored \
                else pdf_dir / (document.get("file") or "")
            if not path.exists():
                issues.append(_issue("REV_PDF_MISSING", "warning", f"PDF نیست: {path.name}", rev["id"]))
                continue
            actual = sha256_file(path)
            if actual != document.get("sha256"):
                issues.append(_issue("REV_SHA_MISMATCH", "error",
                                     f"{rev['id']}: هشِ فایل با نسخه نمی‌خواند", rev["id"]))

    # تصمیم‌های بازبینیِ هویت: هر ورودی باید شاهد، علت و مقصدِ معتبر داشته باشد.
    entries = load_identity_review_entries() if identity_reviews is None else identity_reviews
    seen_reviews: set[str] = set()
    for entry in entries:
        eid = entry.get("eventId", "")
        if eid in seen_reviews:
            issues.append(_issue("REVIEW_DUPLICATE", "error",
                                 f"تصمیمِ تکراری برای {eid}", eid))
        seen_reviews.add(eid)
        if not eid or entry.get("decision") not in REVIEW_DECISIONS:
            issues.append(_issue("REVIEW_DECISION_UNKNOWN", "error",
                                 "تصمیمِ بازبینیِ ناشناخته/ناقص", eid))
            continue
        if not entry.get("reason") or not entry.get("reviewedBy") or not entry.get("reviewedAt"):
            issues.append(_issue("REVIEW_INCOMPLETE", "error",
                                 "تصمیم بدونِ علت/بازبین/زمان", eid))
        approval = entry.get("approval") or {}
        if approval.get("kind") != "human" or not approval.get("by") or not approval.get("at"):
            issues.append(_issue("REVIEW_APPROVAL_MISSING", "error",
                                 "تصمیمِ هویت تأییدِ صریحِ انسانی ندارد", eid))
        if entry["decision"] == "map":
            if entry.get("target") not in event_ids:
                issues.append(_issue("REVIEW_TARGET_MISSING", "error",
                                     f"مقصدِ ادغام وجود ندارد: {entry.get('target')}", eid))
            if not eid.startswith("S"):
                issues.append(_issue("REVIEW_MAP_SOURCE", "error",
                                     "فقط هویتِ ردیفی (S…) به کاتالوگ نگاشت می‌شود", eid))
        elif entry["decision"] in {"keep-merged-row", "keep-garbled-row"}:
            if eid not in event_ids:
                issues.append(_issue("REVIEW_EVENT_MISSING", "error",
                                     "هویتِ بازبینی‌شده در داده نیست", eid))
        ev = entry.get("evidence") or []
        if not ev:
            issues.append(_issue("REVIEW_EVIDENCE_MISSING", "error",
                                 "تصمیم بدونِ شاهدِ صفحه/نسخه", eid))
        for item in ev:
            rev = rev_by_id.get(item.get("revisionId"))
            if rev is None or not item.get("page"):
                issues.append(_issue("REVIEW_EVIDENCE_MISSING", "error",
                                     "شاهدِ بازبینی به نسخه/صفحهٔ معتبر اشاره نمی‌کند", eid))
            elif not 1 <= int(item["page"]) <= int(rev["document"].get("pages") or 0):
                issues.append(_issue("REVIEW_EVIDENCE_PAGE", "error",
                                     f"صفحهٔ {item['page']} بیرون از سند {rev['id']}", eid))
    open_reviews = [e["id"] for e in events if e.get("needsReview")]
    for eid in open_reviews:
        issues.append(_issue("REVIEW_OPEN", "warning",
                             "هویتِ ردیفی هنوز تصمیمِ مستند ندارد", eid))

    # تغییراتِ تأییدشده باید در تاریخچه باشند و برعکس.
    log_ids = {c.get("id") for c in changelog}
    if len(log_ids) != len(changelog):
        issues.append(_issue("CHANGELOG_DUPLICATE_ID", "error", "شناسهٔ تکراری در ChangeLog"))
    for entry in changelog:
        if not entry.get("id") or not entry.get("action") or not entry.get("actor"):
            issues.append(_issue("CHANGELOG_INCOMPLETE", "error", "ورودیِ ناقص در ChangeLog", entry.get("id", "")))
        if entry.get("action") == "REVERT" and entry.get("restoresLogId") not in log_ids:
            issues.append(_issue("CHANGELOG_BAD_REVERT", "error",
                                 "بازگردانی به ورودیِ ناموجود اشاره می‌کند", entry.get("id", "")))
        if entry.get("action") == "APPROVE" and not isinstance(entry.get("snapshotBefore"), list):
            issues.append(_issue("CHANGELOG_NO_SNAPSHOT", "warning",
                                 "تأیید بدونِ عکسِ وضعیتِ پیشین (بازگردانی سخت می‌شود)", entry.get("id", "")))

    if expected is not None:
        exp_events, exp_occ = expected
        def key(o: dict) -> tuple:
            return (o["id"], o["year"], o["eventId"], o["observedTitle"],
                    tuple(o["date"]["solar"]), o["evidence"].get("page"),
                    o.get("description"), bool(o.get("holiday")),
                    o["evidence"].get("revisionId"))
        got = {key(o) for o in occurrences}
        want = {key(o) for o in exp_occ}
        if got != want:
            missing = sorted(want - got)[:3]
            extra = sorted(got - want)[:3]
            issues.append(_issue("OCC_NOT_DERIVED", "error",
                                 f"وقوع‌ها با بازتولیدِ نسخه‌ها یکی نیستند (کم: {missing}، اضافه: {extra})"))

        def ekey(e: dict) -> tuple:
            return (e["id"], e.get("canonicalTitle"), tuple(e.get("observedYears") or []),
                    e.get("firstObservedYear"), e.get("verificationStatus"))
        got_e = {ekey(e) for e in events}
        want_e = {ekey(e) for e in exp_events}
        if got_e != want_e:
            issues.append(_issue("EVENT_NOT_DERIVED", "error",
                                 "هویت‌ها با بازتولیدِ نسخه‌ها یکی نیستند"))
        if len(events) != len(exp_events):
            issues.append(_issue("EVENT_COUNT_MISMATCH", "error",
                                 f"هویت‌ها {len(events)} ≠ بازتولید {len(exp_events)}"))
    return issues


def summarize_issues(issues: list[dict]) -> dict:
    out = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        out[i["severity"]] = out.get(i["severity"], 0) + 1
    return out
