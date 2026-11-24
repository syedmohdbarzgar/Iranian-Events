"""مقایسهٔ دو نسخه از تقویمِ یک سال (فاز ۳ چک‌لیست).

تفاوت‌ها به این دسته‌ها تقسیم می‌شوند:

``ADDED`` · ``REMOVED`` · ``RENAMED`` · ``DATE_CHANGED`` · ``MODIFIED`` · ``UNCHANGED``

تفاوتِ نگارشی/OCR (همان کلیدِ کانونی با فاصله/نیم‌فاصله/ارقام متفاوت) عمداً
``UNCHANGED`` با ``variantOnly=True`` است تا «تغییرِ واقعی» از «خطای استخراج»
جدا بماند. مقایسه فقط در محدودهٔ همان سال انجام می‌شود.

این ماژول داده نمی‌نویسد؛ تابعِ خالصِ ``diff_rows`` برای تست و بازاستفاده است.
"""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402

KINDS = ("ADDED", "REMOVED", "RENAMED", "DATE_CHANGED", "MODIFIED", "UNCHANGED")
SIM_RENAME = 0.72
SIM_VARIANT = 0.92
SIM_CHANGE_PAIR = 0.8

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def compare_key(title: str) -> str:
    """کلیدِ مقایسه با حفظِ ارقام؛ برای سنجشِ شباهت و تغییرِ واقعی."""
    t = store.clean_observed(title).translate(DIGITS)
    t = t.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه").replace("ة", "ه")
    t = re.sub(r"[\u200c\u200d\u200e\u200f\u202a-\u202e]", "", t)
    t = re.sub(r"[«»\"'()\[\]{}،,؛;:.!?؟…\-–—]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def loose_key(title: str) -> str:
    return store.identity_key(title)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, compare_key(a), compare_key(b)).ratio()


def edit_distance(a: str, b: str) -> int:
    """فاصلهٔ لِوِنشتاین روی متنِ مقایسه‌ای (برای جداکردنِ تفاوتِ نگارشی)."""
    x, y = compare_key(a), compare_key(b)
    if x == y:
        return 0
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cx != cy)))
        prev = cur
    return prev[-1]


def _row(row: dict) -> dict:
    return {
        "title": row.get("title", ""),
        "description": row.get("description"),
        "solar": list(row.get("solar") or [None, None, None]),
        "gregorian": list(row.get("gregorian") or [None, None, None]),
        "lunar": list(row.get("lunar") or [None, None, None]),
        "weekday": row.get("weekday"),
        "holiday": bool(row.get("holiday")),
        "page": row.get("page"),
        "bbox": row.get("bbox"),
        "derived": list(row.get("derived") or []),
        "flags": list(row.get("flags") or []),
    }


def _md(row: dict) -> tuple[int, int]:
    solar = row.get("solar") or [0, 0, 0]
    return int(solar[1] or 0), int(solar[2] or 0)


def _fields_changed(old: dict, new: dict, title_variant: bool) -> list[str]:
    out: list[str] = []
    if not title_variant and compare_key(old.get("title", "")) != compare_key(new.get("title", "")):
        out.append("title")
    if _md(old) != _md(new):
        out.append("date")
    if bool(old.get("holiday")) != bool(new.get("holiday")):
        out.append("holiday")
    if (old.get("description") or "").strip() != (new.get("description") or "").strip():
        out.append("description")
    if [int(x) if x is not None else None for x in (old.get("lunar") or [])] != \
            [int(x) if x is not None else None for x in (new.get("lunar") or [])]:
        out.append("lunar")
    if [int(x) if x is not None else None for x in (old.get("gregorian") or [])] != \
            [int(x) if x is not None else None for x in (new.get("gregorian") or [])]:
        out.append("gregorian")
    if bool(old.get("derived")) != bool(new.get("derived")):
        out.append("derived")
    return out


def _change(kind: str, before: dict | None, after: dict | None, *,
            similarity_score: float = 0.0, variant_only: bool = False,
            reason: str = "", fields: list[str] | None = None) -> dict:
    return {
        "kind": kind,
        "dateKey": (lambda r: f"{(r.get('solar') or [0,0,0])[1]:02d}-{(r.get('solar') or [0,0,0])[2]:02d}")
                   (after or before or {}),
        "before": _row(before) if before else None,
        "after": _row(after) if after else None,
        "fields": fields or [],
        "similarity": round(similarity_score, 3),
        "variantOnly": variant_only,
        "requiresHuman": kind != "UNCHANGED",
        "autoAcceptable": kind == "UNCHANGED",
        "reason": reason,
    }


def diff_rows(old_rows: list[dict], new_rows: list[dict], *, year: int | None = None,
              new_year: int | None = None) -> dict:
    """تفاوتِ دو فهرستِ ردیف؛ هر دو باید متعلق به یک سال باشند."""
    if year is not None and new_year is not None and year != new_year:
        raise ValueError(f"مقایسهٔ دوساله مجاز نیست: {year} ≠ {new_year}")
    effective_year = year if year is not None else new_year
    old = [r for r in old_rows if store.row_is_event(r.get("title", ""))]
    new = [r for r in new_rows if store.row_is_event(r.get("title", ""))]
    for label, rows in (("old", old), ("new", new)):
        for r in rows:
            row_year = (r.get("solar") or [None])[0]
            if effective_year is not None and row_year is not None and int(row_year) != effective_year:
                raise ValueError(f"ردیفِ سالِ {row_year} در مقایسهٔ سالِ {effective_year} ({label})")

    matched_old: set[int] = set()
    matched_new: set[int] = set()
    changes: list[dict] = []
    pairs: list[tuple[int, int, str, float, bool]] = []

    # ۱) کلیدِ کانونیِ یکسان: همان رویداد در همان تاریخ یا تاریخِ دیگر
    by_loose_old: dict[str, list[int]] = {}
    for i, r in enumerate(old):
        by_loose_old.setdefault(loose_key(r.get("title", "")), []).append(i)
    for j, nr in enumerate(new):
        key = loose_key(nr.get("title", ""))
        for i in by_loose_old.get(key, []):
            if i in matched_old:
                continue
            pairs.append((i, j, "key", 1.0, False))
            matched_old.add(i)
            matched_new.add(j)
            break

    # ۲) همان تاریخ با عنوانِ شبیه: تغییرِ عنوان در برابر تفاوتِ نگارشی
    remaining_old = [i for i in range(len(old)) if i not in matched_old]
    remaining_new = [j for j in range(len(new)) if j not in matched_new]
    old_by_date: dict[tuple[int, int], list[int]] = {}
    for i in remaining_old:
        old_by_date.setdefault(_md(old[i]), []).append(i)
    for j in list(remaining_new):
        nr = new[j]
        best = None
        for i in old_by_date.get(_md(nr), []):
            if i in matched_old:
                continue
            score = similarity(old[i].get("title", ""), nr.get("title", ""))
            if best is None or score > best[0]:
                best = (score, i)
        if best and best[0] >= SIM_RENAME:
            score, i = best
            variant = (score >= SIM_VARIANT
                       or (score >= 0.85 and edit_distance(old[i].get("title", ""), nr.get("title", "")) <= 2))
            pairs.append((i, j, "date+sim", score, variant))
            matched_old.add(i)
            matched_new.add(j)

    # ۳) تغییرِ هم‌زمانِ عنوان و تاریخ: جفتِ باقی‌مانده با شباهتِ بالا
    remaining_old = [i for i in range(len(old)) if i not in matched_old]
    remaining_new = [j for j in range(len(new)) if j not in matched_new]
    scored: list[tuple[float, int, int]] = []
    for j in remaining_new:
        for i in remaining_old:
            score = similarity(old[i].get("title", ""), new[j].get("title", ""))
            if score >= SIM_CHANGE_PAIR:
                scored.append((score, i, j))
    for score, i, j in sorted(scored, reverse=True):
        if i in matched_old or j in matched_new:
            continue
        pairs.append((i, j, "moved", score, False))
        matched_old.add(i)
        matched_new.add(j)

    for i, j, why, score, variant in pairs:
        old_row, new_row = old[i], new[j]
        date_changed = _md(old_row) != _md(new_row)
        variant = variant or loose_key(old_row.get("title", "")) == loose_key(new_row.get("title", ""))
        fields = _fields_changed(old_row, new_row, variant)
        title_changed = "title" in fields
        raw_title_diff = compare_key(old_row.get("title", "")) != compare_key(new_row.get("title", ""))
        if variant and not date_changed and set(fields) <= {"title", "derived"}:
            changes.append(_change(
                "UNCHANGED", old_row, new_row, similarity_score=score, variant_only=raw_title_diff,
                reason=("تفاوتِ نگارشی/OCR؛ همان رویداد و همان تاریخ"
                        if raw_title_diff else "بدونِ تغییر"),
                fields=[]))
        elif date_changed and not title_changed and set(fields) <= {"date", "gregorian", "lunar", "derived"}:
            changes.append(_change(
                "DATE_CHANGED", old_row, new_row, similarity_score=score,
                reason="تاریخِ ردیف در همان سند تغییر کرده است", fields=fields))
        elif title_changed and not date_changed:
            changes.append(_change(
                "RENAMED", old_row, new_row, similarity_score=score,
                reason="عنوان در همان تاریخ تغییر کرده است", fields=fields))
        elif title_changed and date_changed:
            changes.append(_change(
                "MODIFIED", old_row, new_row, similarity_score=score,
                reason="عنوان و تاریخ هر دو تغییر کرده‌اند", fields=sorted(set(fields) | {"title", "date"})))
        else:
            changes.append(_change(
                "MODIFIED", old_row, new_row, similarity_score=score,
                reason="تعطیلی/توضیح/تاریخِ قمری تغییر کرده است", fields=fields))

    for i in range(len(old)):
        if i not in matched_old:
            changes.append(_change("REMOVED", old[i], None, reason="در نسخهٔ جدید دیده نشد"))
    for j in range(len(new)):
        if j not in matched_new:
            changes.append(_change("ADDED", None, new[j], reason="در نسخهٔ جدید افزوده شده است"))

    # تکراری‌ها: دو ردیفِ هم‌زمانِ یکسان در نسخهٔ جدید (نه before/after یک تغییر)
    dup_groups: dict[tuple[str, tuple[int, int]], list[dict]] = {}
    for row in new:
        dup_groups.setdefault((loose_key(row.get("title", "")), _md(row)), []).append(row)
    duplicates = []
    for (_, date), group in dup_groups.items():
        if len(group) < 2:
            continue
        date_key = f"{date[0]:02d}-{date[1]:02d}"
        keys = {(r.get("title"), tuple(r.get("solar") or [])) for r in group}
        for c in changes:
            if c["after"] and (c["after"]["title"], tuple(c["after"]["solar"] or [])) in keys:
                c["duplicateGroup"] = date_key
        duplicates.append({"date": date_key, "count": len(group),
                           "titles": sorted({r.get("title", "") for r in group})})

    order = {k: n for n, k in enumerate(KINDS)}
    changes.sort(key=lambda c: (order.get(c["kind"], 9), c["dateKey"],
                                (c["after"] or c["before"] or {}).get("title", "")))
    for n, c in enumerate(changes, 1):
        c["id"] = f"C-{effective_year or '0000'}-{n:04d}"

    # نشانهٔ شکستنِ ردیف: ردیفِ افزوده که قطعه‌ای از یک ردیفِ حذف‌شده است.
    removed = [c for c in changes if c["kind"] == "REMOVED"]
    for c in changes:
        if c["kind"] != "ADDED" or not c["after"]:
            continue
        if "fragment" in (c["after"].get("flags") or []):
            c["suspectedFragment"] = True
            c["reason"] += " (قطعهٔ متنِ شکسته؛ احتمالاً ادامهٔ ردیفِ پیشین)"
        added_key = compare_key(c["after"]["title"])
        if len(added_key) < 6:
            continue
        for r in removed:
            if not r.get("before"):
                continue
            old_key = compare_key(r["before"]["title"])
            shorter, longer = sorted((added_key, old_key), key=len)
            if shorter in longer and len(shorter) / max(1, len(longer)) >= 0.2:
                c["suspectedSplit"] = r["id"]
                c["reason"] += f" (احتمالاً قطعهٔ شکسته از ردیفِ {r['id']})"
                break

    counts = {k: 0 for k in KINDS}
    for c in changes:
        counts[c["kind"]] += 1
    return {
        "year": effective_year,
        "counts": counts,
        "changes": changes,
        "duplicates": duplicates,
        "oldRows": len(old),
        "newRows": len(new),
        "requiresReview": any(c["requiresHuman"] for c in changes),
    }
