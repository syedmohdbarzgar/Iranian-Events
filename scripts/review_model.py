#!/usr/bin/env python3
"""مدلِ خالصِ پنلِ بازبینیِ انسانی.

این ماژول هیچ فایلی را تغییر نمی‌دهد؛ شناسهٔ پایدار، وضعیت، اعتبارسنجیِ تاریخ و
ساختِ صف را جدا از OCR/Build و جدا از سرور محاسبه می‌کند تا آزمون‌پذیر باشد.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import calendar_engine as engine  # noqa: E402

STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_CORRECTED = "corrected"
STATUS_REJECTED = "rejected"
STATUS_NEEDS_EVIDENCE = "needs-evidence"
STATUSES = (STATUS_DRAFT, STATUS_PENDING, STATUS_APPROVED, STATUS_CORRECTED,
            STATUS_REJECTED, STATUS_NEEDS_EVIDENCE)
STATUS_LABELS = {
    STATUS_DRAFT: "Draft",
    STATUS_PENDING: "Pending",
    STATUS_APPROVED: "Approved",
    STATUS_CORRECTED: "Corrected",
    STATUS_REJECTED: "Rejected",
    STATUS_NEEDS_EVIDENCE: "Needs Evidence",
}
ALGORITHM = "calendar_engine.jalali-arithmetic"
ALGORITHM_VERSION = "1"
CALENDARS = ("solar", "lunar", "gregorian")
# سال‌هایی که فقط بستهٔ شاهد/پیش‌نویس دارند و تا بازبینیِ ردیفیِ کامل و مجوز انتشار
# جداگانه نباید فعال/منتشر شوند؛ پنل هم نباید برای آن‌ها «تأیید سال» بدهد.
LOCKED_YEARS = (1393, 1396, 1402)


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_hex(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _triple(value) -> list[int]:
    if isinstance(value, dict):
        value = [value.get("y"), value.get("m"), value.get("d")]
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("تاریخ باید سه جزء (سال، ماه، روز) داشته باشد")
    try:
        return [int(x) for x in value]
    except (TypeError, ValueError) as exc:
        raise ValueError("اجزای تاریخ باید عدد باشند") from exc


def validate_solar(year: int, values) -> list[int]:
    y, m, d = _triple(values)
    if y != year:
        raise ValueError(f"سالِ تاریخ باید {year} باشد، نه {y}")
    if not 1 <= m <= 12:
        raise ValueError(f"ماهِ شمسی نامعتبر: {m}")
    if not 1 <= d <= engine.month_len(y, m):
        raise ValueError(f"روزِ {d} در ماهِ {m} سالِ {y} وجود ندارد")
    return [y, m, d]


def _gregorian_to_solar(year: int, values) -> list[int]:
    y, m, d = _triple(values)
    try:
        date(y, m, d)
    except ValueError as exc:
        raise ValueError(f"تاریخِ میلادیِ نامعتبر: {y}-{m}-{d}") from exc
    solar = list(engine.gregorian_to_jalali(y, m, d))
    if solar[0] != year:
        raise ValueError(f"تاریخِ میلادی به سالِ {solar[0]} شمسی می‌افتد، نه {year}")
    return solar


def lunar_to_solar(year: int, values) -> list[int]:
    y, m, d = _triple(values)
    # سالِ قمری، سالِ هجریِ قمری است و با سالِ شمسی یکی نیست؛ فقط بازهٔ معقول
    # بررسی می‌شود و نگاشتِ واقعی با lunar_occurrence انجام می‌گیرد.
    if not 1300 <= y <= 1500:
        raise ValueError("سالِ قمری در بازهٔ معقول نیست")
    if not 1 <= m <= 12 or not 1 <= d <= 30:
        raise ValueError(f"تاریخِ قمریِ نامعتبر: {y}-{m}-{d}")
    solar = engine.lunar_occurrence(year, m, d)
    if solar is None:
        raise ValueError(f"تاریخِ قمری {m}/{d} در سالِ {year} به روزِ شمسی نگاشت نشد")
    return list(solar)


def date_from_calendar(year: int, calendar: str, values) -> list[int]:
    if calendar not in CALENDARS:
        raise ValueError(f"تقویمِ ناشناخته: {calendar}")
    if calendar == "solar":
        return validate_solar(year, values)
    if calendar == "gregorian":
        return _gregorian_to_solar(year, values)
    return lunar_to_solar(year, values)


def normalize_period(payload: dict, year: int, fallback_solar) -> dict:
    """بازهٔ شروع/پایان را به تاریخِ شمسیِ معتبر و فرادادهٔ تبدیل برمی‌گرداند.

    ورودیِ هر سر: ``{"calendar": "solar"|"lunar"|"gregorian", "date": [y,m,d]}``.
    تاریخِ اصلیِ منبع جدا از تاریخِ تبدیل‌شده در ``source`` می‌ماند.
    """
    raw_start = payload.get("start") or {}
    raw_end = payload.get("end") or {}
    start_cal = raw_start.get("calendar") or payload.get("calendar") or "solar"
    end_cal = raw_end.get("calendar") or start_cal
    start_values = raw_start.get("date") if isinstance(raw_start, dict) else raw_start
    end_values = raw_end.get("date") if isinstance(raw_end, dict) else raw_end
    if not start_values:
        start_values = fallback_solar
    start_solar = date_from_calendar(year, start_cal, start_values)
    end_solar = (date_from_calendar(year, end_cal, end_values)
                 if end_values else list(start_solar))
    if tuple(end_solar) < tuple(start_solar):
        raise ValueError("پایانِ بازه نمی‌تواند پیش از شروع باشد")
    return {
        "startSolar": start_solar,
        "endSolar": end_solar,
        "multiDay": end_solar != start_solar,
        "source": {
            "calendar": start_cal,
            "start": _triple(start_values),
            "end": _triple(end_values) if end_values else _triple(start_values),
        },
        "conversion": {
            "algorithm": ALGORITHM,
            "version": ALGORITHM_VERSION,
            "from": start_cal,
            "to": "solar",
            "startSolar": start_solar,
            "endSolar": end_solar,
        },
    }


def event_review_id(bundle: dict, change: dict) -> str:
    """شناسهٔ پایدارِ ردیف بر پایهٔ سند/صفحه/سطر/متنِ منبع، نه ترتیبِ diff."""
    before = change.get("before") or {}
    after = change.get("after") or {}
    source = change.get("source") or before or after
    page = source.get("page") if isinstance(source, dict) else None
    table_row = source.get("tableRow") if isinstance(source, dict) else None
    if table_row is None and isinstance(source.get("locator"), dict):
        table_row = source["locator"].get("tableRow")
    raw_title = (source.get("titleRaw") or source.get("title") or
                 before.get("titleRaw") or after.get("titleRaw") or "")
    fields = {
        "year": bundle.get("revision", {}).get("year"),
        "sourceSha256": bundle.get("revision", {}).get("document", {}).get("sha256"),
        "page": page,
        "tableRow": table_row,
        "dateKey": change.get("dateKey"),
        "sourceTitle": raw_title,
        "kind": change.get("kind"),
    }
    return "H-" + sha256_hex(fields)[:16].upper()


def status_for(bundle: dict, change: dict) -> str:
    decision = (bundle.get("decisions") or {}).get(change.get("id")) or {}
    action = decision.get("action")
    if action == "needs-evidence":
        return STATUS_NEEDS_EVIDENCE
    if action == "reject":
        return STATUS_REJECTED
    if action == "approve":
        return STATUS_CORRECTED if decision.get("edited") or decision.get("edit") else STATUS_APPROVED
    if bundle.get("state") == "rejected":
        return STATUS_REJECTED
    return STATUS_PENDING if change.get("requiresHuman", True) else STATUS_DRAFT


def _row_page(row: dict | None) -> int | None:
    if not isinstance(row, dict):
        return None
    if row.get("page") is not None:
        return int(row["page"])
    locator = row.get("locator") or {}
    return int(locator["page"]) if locator.get("page") is not None else None


def queue_items(bundles: list[dict]) -> list[dict]:
    items: list[dict] = []
    for bundle in bundles:
        rev = bundle.get("revision") or {}
        for change in (bundle.get("diff") or {}).get("changes", []):
            if change.get("kind") == "UNCHANGED":
                continue
            before, after = change.get("before") or {}, change.get("after") or {}
            source = before or after
            status = status_for(bundle, change)
            decision = (bundle.get("decisions") or {}).get(change.get("id")) or {}
            page = _row_page(after) or _row_page(before)
            items.append({
                "itemId": event_review_id(bundle, change),
                "revisionId": rev.get("id"),
                "changeId": change.get("id"),
                "year": rev.get("year"),
                "document": rev.get("document") or {},
                "status": status,
                "statusLabel": STATUS_LABELS[status],
                "page": page,
                "tableRow": (source.get("locator") or {}).get("tableRow"),
                "sourceDate": source.get("sourceDate") or source.get("solar"),
                "sourceLunar": source.get("sourceLunar") or source.get("lunar"),
                "sourceGregorian": source.get("sourceGregorian") or source.get("gregorian"),
                "sourceTitle": source.get("titleRaw") or source.get("title") or "",
                "dateKey": change.get("dateKey"),
                "kind": change.get("kind"),
                "requiresHuman": bool(change.get("requiresHuman", True)),
                "similarity": change.get("similarity"),
                "reason": change.get("reason") or "",
                "duplicateGroup": change.get("duplicateGroup"),
                "suspectedSplit": bool(change.get("suspectedSplit")),
                "before": before or None,
                "after": after or None,
                "decision": decision or None,
                "needsEvidence": page is None or status == STATUS_NEEDS_EVIDENCE,
            })
    return items


def status_counts(items: list[dict]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


def all_requires_human_resolved(bundle: dict) -> bool:
    for change in (bundle.get("diff") or {}).get("changes", []):
        if not change.get("requiresHuman", True):
            continue
        decision = (bundle.get("decisions") or {}).get(change.get("id")) or {}
        if decision.get("action") not in {"approve", "reject"}:
            return False
    return True


def approval_bundle_hash(bundle: dict) -> str:
    """اثرِ انگشتِ تصمیم‌ها؛ تأییدِ سال باید دقیقاً به همین وضعیت گره بخورد."""
    return sha256_hex({
        "revisionId": (bundle.get("revision") or {}).get("id"),
        "state": bundle.get("state"),
        "decisions": bundle.get("decisions") or {},
    })
