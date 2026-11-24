"""دریافت و استخراجِ یک PDF تقویم به‌صورت **پیش‌نویس** (فاز ۲ چک‌لیست).

هیچ‌چیز در دادهٔ اصلی نوشته نمی‌شود. خروجی این ابزار در
``data/review/changes/<revisionId>.json`` می‌نشیند و تنها پس از تأییدِ انسانی
(``scripts/review_changes.py``) به تاریخچه راه می‌یابد.

قابلیت‌ها:
* هشِ SHA-256، حجم و شمارِ صفحهٔ سند؛
* تشخیصِ سال از نامِ فایل و متنِ صفحه‌ها (با هشدارِ تناقض)؛
* استخراجِ متنِ لایه‌متنی با همان تجزیه‌گرِ رسمی (``parse_official``)؛
* تشخیصِ صفحه‌های اسکن‌شده/کم‌متن و صفِ OCR (در نبودِ tesseract مسدود می‌ماند)؛
* مکان‌یابِ هر ردیف: صفحه + شمارهٔ خط + بازهٔ نویسه؛ در صورت وجودِ
  ``pdftotext -bbox`` (poppler) کادرِ نقطه‌ای هم ثبت می‌شود؛
* نگه‌داشتنِ تصویرِ صفحه برای ردیف‌های مشکوک، اگر رندرکننده موجود باشد؛
* سطحِ اطمینان و پرچم‌های بازبینی برای هر ردیف؛
* مقایسهٔ خودکار با نسخهٔ فعالِ همان سال و ساختِ پیش‌نویسِ تغییرات.

اجرا:
    py -3 scripts/ingest_pdf.py --pdf PDF/Calendar-1407.pdf
    py -3 scripts/ingest_pdf.py --pdf new.pdf --year 1407 --ocr
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import calendar_engine as engine  # noqa: E402
import history_store as store  # noqa: E402
import parse_official  # noqa: E402
import revision_diff  # noqa: E402

PDF_DIR = ROOT / "PDF"
YEAR_MIN, YEAR_MAX = 1300, 1420
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
BIDI = {ord(c): None for c in "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200b\u200c\u200d\ufeff"}


def _norm(text: str) -> str:
    text = text.translate(BIDI).translate(PERSIAN_DIGITS)
    return re.sub(r"\s+", " ", text).strip()


def detect_year(text: str, filename: str) -> dict:
    """سال را از نام و متن تشخیص می‌دهد و تناقض را گزارش می‌کند."""
    candidates: dict[int, int] = {}
    for m in re.finditer(r"(?<!\d)(1[34]\d{2})(?!\d)", text.translate(PERSIAN_DIGITS)):
        year = int(m.group(1))
        if YEAR_MIN <= year <= YEAR_MAX:
            candidates[year] = candidates.get(year, 0) + 1
    by_text = max(candidates, key=candidates.get) if candidates else None
    m = re.search(r"(?<!\d)(1[34]\d{2})(?!\d)", filename)
    by_name = int(m.group(1)) if m and YEAR_MIN <= int(m.group(1)) <= YEAR_MAX else None
    conflict = bool(by_name and by_text and by_name != by_text
                    and candidates.get(by_name, 0) < 3)
    return {
        "filename": by_name,
        "text": by_text,
        "textCandidates": dict(sorted(candidates.items(), key=lambda x: -x[1])[:5]),
        "conflict": conflict,
    }


def tool(name: str) -> str | None:
    return shutil.which(name)


def page_locator(page_text: str, title: str) -> dict | None:
    """صفحه/خط/بازهٔ نویسهٔ ردیف در متنِ همان صفحه (مکان‌یابِ قطعی و ارزان)."""
    target = _norm(title)[:24]
    if not target:
        return None
    offset = 0
    for lineno, line in enumerate(page_text.split("\n"), 1):
        norm_line = _norm(line)
        if target[:12] and target[:12] in norm_line:
            start = norm_line.find(target[:12])
            return {"kind": "page-line", "page": None, "line": lineno,
                    "charStart": offset + start, "charEnd": offset + start + len(target),
                    "lineText": norm_line[:200]}
        offset += len(line) + 1
    return None


_BBOX_SUPPORTED: bool | None = None


def _bbox_words(pdf: Path, page: int) -> list[tuple[str, float, float, float, float]] | None:
    """کادرِ واژه‌ها با ``pdftotext -bbox``؛ در نبودِ پشتیبانی None."""
    global _BBOX_SUPPORTED
    if _BBOX_SUPPORTED is False:
        return None
    proc = subprocess.run(
        ["pdftotext", "-bbox", "-f", str(page), "-l", str(page), "-enc", "UTF-8", str(pdf), "-"],
        capture_output=True)
    if proc.returncode != 0 or b"<word" not in proc.stdout:
        _BBOX_SUPPORTED = False
        return None
    _BBOX_SUPPORTED = True
    words = []
    for m in re.finditer(
            rb'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
            proc.stdout):
        try:
            text = m.group(5).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            text = ""
        words.append((_norm(text), float(m.group(1)), float(m.group(2)),
                      float(m.group(3)), float(m.group(4))))
    return words


def bbox_for_title(pdf: Path, page: int, title: str) -> dict | None:
    """کادرِ سطرِ عنوان: لنگرِ نخستین واژهٔ معنادار + هم‌باندهای افقی."""
    words = _bbox_words(pdf, page)
    if not words:
        return None
    tokens = [w for w in _norm(title).split() if len(w) >= 3]
    if not tokens:
        return None
    anchor = None
    for token in tokens[:3]:
        for word in words:
            if word[0] == token:
                anchor = word
                break
        if anchor:
            break
    if anchor is None:
        return None
    cy = (anchor[2] + anchor[4]) / 2
    band = [w for w in words if abs((w[2] + w[4]) / 2 - cy) <= 9]
    wanted = set(tokens)
    picked = [w for w in band if w[0] in wanted] or [anchor]
    return {
        "xMin": round(min(w[1] for w in picked), 2),
        "yMin": round(min(w[2] for w in picked), 2),
        "xMax": round(max(w[3] for w in picked), 2),
        "yMax": round(max(w[4] for w in picked), 2),
        "unit": "pt",
    }


def render_page(pdf: Path, page: int, out_dir: Path) -> dict:
    """تصویرِ صفحه برای بازبینیِ انسانی، اگر رندرکننده‌ای نصب باشد."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"page-{page:03d}.png"
    if target.exists():
        return {"available": True, "path": str(target.relative_to(ROOT))}
    if tool("pdftoppm"):
        cmd = ["pdftoppm", "-f", str(page), "-l", str(page), "-r", "150", "-png",
               "-singlefile", str(pdf), str(target.with_suffix(""))]
    elif tool("mutool"):
        cmd = ["mutool", "draw", "-o", str(target), "-r", "150", str(pdf), str(page)]
    elif tool("gs"):
        cmd = ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", "-r150",
               f"-dFirstPage={page}", f"-dLastPage={page}", f"-sOutputFile={target}", str(pdf)]
    else:
        return {"available": False, "reason": "هیچ رندرکننده‌ای (pdftoppm/mutool/gs) نصب نیست"}
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not target.exists():
        return {"available": False, "reason": proc.stderr.decode("utf-8", "replace")[:200]}
    return {"available": True, "path": str(target.relative_to(ROOT))}


def ocr_page(pdf: Path, page: int, out_dir: Path, lang: str = "fas+eng") -> dict:
    """OCR یک صفحه؛ در نبودِ ابزار، وضعیتِ «مسدود» با دلیلِ عملی برمی‌گردد."""
    if not tool("tesseract"):
        return {"status": "blocked", "reason": "tesseract نصب نیست (apt/choco install tesseract)"}
    rendered = render_page(pdf, page, out_dir)
    if not rendered.get("available"):
        return {"status": "blocked", "reason": f"رندرِ صفحه ممکن نشد: {rendered.get('reason')}"}
    proc = subprocess.run(["tesseract", str(ROOT / rendered["path"]), "stdout", "-l", lang],
                          capture_output=True)
    if proc.returncode != 0:
        return {"status": "error", "reason": proc.stderr.decode("utf-8", "replace")[:300]}
    text = proc.stdout.decode("utf-8", "replace")
    return {"status": "ok", "text": text, "chars": len(text.strip()), "lang": lang}


def page_texts(pdf: Path) -> list[str]:
    return parse_official.pdf_pages(pdf)


def scan_pages(pages: list[str]) -> list[int]:
    """صفحه‌های بی‌متن/کم‌متن که برای OCR نامزدند."""
    out = []
    for i, text in enumerate(pages, 1):
        letters = len(re.findall(r"[آ-یءأإؤئ]", text))
        if letters < 25:
            out.append(i)
    return out


def confidence(row: dict, flags: list[str]) -> float:
    score = 1.0
    if not row.get("solar") or None in (row["solar"][1], row["solar"][2]):
        score -= 0.45
    if not row.get("gregorian") or None in (row["gregorian"] or [None, None, None]):
        score -= 0.15
    if len(row.get("title", "")) < 5:
        score -= 0.2
    for flag in flags:
        score -= {"no-locator": 0.08, "no-bbox": 0.03, "missing-lunar": 0.05,
                  "ocr-page": 0.25, "ocr-row": 0.30, "ocr-multiple-dates": 0.2,
                  "duplicate": 0.2, "short-title": 0.1,
                  "fragment": 0.35}.get(flag, 0.05)
    return round(max(0.05, min(1.0, score)), 2)


def _ocr_flags(row: dict, *, multiple_dates: bool) -> list[str]:
    flags = ["ocr-page", "ocr-row"]
    if multiple_dates:
        flags.append("ocr-multiple-dates")
    if not row.get("lunar") or None in (row.get("lunar") or [None, None, None]):
        flags.append("missing-lunar")
    if len(row.get("title", "")) < 8:
        flags.append("short-title")
    if is_fragment(row.get("title", "")):
        flags.append("fragment")
    return sorted(set(flags))


def _ocr_title(line: str, spans: list[tuple[int, int]]) -> str:
    """عنوانِ سطرِ OCR بدونِ بازه‌های تاریخ/روزِ هفته/«تعطیل»؛ هیچ متنی ساخته نمی‌شود."""
    chars = list(line)
    for start, end in spans:
        for i in range(max(0, start), min(len(chars), end)):
            chars[i] = " "
    title = "".join(chars)
    title = re.sub(r"(?:شنبه|یکشنبه|يكشنبه|دوشنبه|سهشنبه|سه\s*شنبه|چهارشنبه|پنجشنبه|پنج\s*شنبه|جمعه|آدینه)", " ", title)
    title = title.replace("تعطیل", " ")
    title = re.sub(r"[()\[\]{}«»\"'،,؛;:.!?؟]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -–—")
    return title


def _explicit_dates(line: str, year: int) -> tuple[list[dict], list[tuple[int, int]]]:
    """تاریخ‌هایی که در متنِ OCR **صریح** آمده‌اند؛ بدونِ تاریخ = بدونِ ردیف."""
    t = _norm(line)
    found: list[dict] = []
    spans: list[tuple[int, int]] = []

    def with_year(span: tuple[int, int]) -> tuple[int, int]:
        """سالِ چسبیده به تاریخ هم بخشی از همان تاریخ است و از عنوان حذف می‌شود."""
        start, end = span
        before = re.search(r"(?<!\d)(1[34]\d{2})\s*$", t[:start])
        if before:
            start = before.start(1)
        after = re.match(r"\s*(1[34]\d{2})(?!\d)", t[end:])
        if after:
            end += after.end(1)
        return start, end

    def add(y: int, m: int, d: int, span: tuple[int, int]) -> None:
        if y != year or not (1 <= m <= 12 and 1 <= d <= engine.month_len(year, m)):
            return
        if any(x["solar"][1:] == [m, d] for x in found):
            return
        span = with_year(span)
        found.append({"solar": [year, m, d], "span": span})
        spans.append(span)

    for m in re.finditer(r"(?<!\d)(1[34]\d{2})\s*[/\-]\s*(\d{1,2})\s*[/\-]\s*(\d{1,2})(?!\d)", t):
        add(int(m.group(1)), int(m.group(2)), int(m.group(3)), (m.start(), m.end()))

    months = "|".join(parse_official.SOLAR_MONTHS)
    for m in re.finditer(rf"(?<!\d)(\d{{1,2}})\s*(?:م\s*)?({months})(?![آ-ی])", t):
        add(year, parse_official.SOLAR_MONTHS.index(m.group(2)) + 1, int(m.group(1)),
            (m.start(), m.end()))
    for m in re.finditer(rf"({months})\s*(\d{{1,2}})(?!\d)", t):
        add(year, parse_official.SOLAR_MONTHS.index(m.group(1)) + 1, int(m.group(2)),
            (m.start(), m.end()))
    return found, spans


def _explicit_lunar(line: str) -> list[int] | None:
    t = _norm(line)
    months = "|".join(parse_official.LUNAR_MONTHS)
    m = re.search(rf"(?<!\d)(\d{{1,2}})\s*(?:م\s*)?({months})(?![آ-ی])", t)
    if not m:
        return None
    month = parse_official.LUNAR_MONTHS.index(m.group(2)) + 1
    ym = re.search(r"(?<!\d)(1[34]\d{2})(?!\d)", t[max(0, m.start() - 8):m.end() + 12])
    return [int(ym.group(1)) if ym else None, month, int(m.group(1))]


def parse_ocr_page(text: str, year: int, page: int) -> list[dict]:
    """متنِ OCR یک صفحه را به ردیف‌های تاریخ‌دار تبدیل می‌کند.

    ابتدا همان تجزیه‌گرِ جدولِ رسمی امتحان می‌شود (اگر OCR ستون‌ها را حفظ کرده باشد)؛
    در غیر این صورت فقط سطرهایی پذیرفته می‌شوند که یک تاریخِ شمسیِ **صریح**
    (روز + نامِ ماه یا YYYY/MM/DD) دارند. سطرِ بی‌تاریخ هرگز حدس زده نمی‌شود.
    خروجی همیشه ``needsReview`` است، چون متنِ OCR خودش شاهدِ خطاپذیر است.
    """
    rows: list[dict] = []
    seen: set[tuple[int, int, str]] = set()
    lines = text.splitlines()
    offset = 0
    line_starts = []
    for line in lines:
        line_starts.append(offset)
        offset += len(line) + 1

    # مسیرِ اول: جدولِ ۸نشانه‌ای (اگر OCR ساختار را نگه داشته باشد).
    records = parse_official.parse_page(text, page)
    if records:
        parsed = []
        for rec in records:
            parsed.append({
                "solar": parse_official.read_cell(
                    rec["solar"], {m: i for i, m in enumerate(parse_official.SOLAR_MONTHS)}, True),
                "lunar": parse_official.read_cell(
                    rec["lunar"], {**{m: i for i, m in enumerate(parse_official.LUNAR_MONTHS)},
                                  **parse_official.LUNAR_ALIASES}, False),
                "greg": parse_official.read_cell(rec["greg"], parse_official.GREG_MONTHS, False),
                "wd": rec["wd"], "title": rec["title"], "page": page,
            })
        for r in parse_official.resolve(parsed, year):
            solar = r.get("solar") or [None, None, None]
            title = (r.get("title") or "").strip()
            if solar[0] != year or None in solar[1:] or not store.row_is_event(title):
                continue
            key = (solar[1], solar[2], store.identity_key(title))
            if key in seen:
                continue
            seen.add(key)
            holiday = bool(re.search("تعطیل", title))
            row = {
                "solar": solar, "gregorian": r.get("gregorian"), "lunar": r.get("lunar"),
                "weekday": r.get("weekday"), "title": title, "holiday": holiday,
                "page": page, "derived": r.get("derived", []), "locator": None,
                "bbox": None, "source": "ocr-table", "function": None,
            }
            flags = _ocr_flags(row, multiple_dates=False)
            row["confidence"] = confidence(row, flags)
            row["flags"] = flags
            row["needsReview"] = True
            rows.append(row)

    # مسیرِ دوم: سطرهای تاریخ‌دارِ آزاد (OCR جدول را به‌هم ریخته).
    for lineno, line in enumerate(lines, 1):
        norm_line = _norm(line)
        dates, spans = _explicit_dates(norm_line, year)
        if not dates:
            continue
        for date in dates:
            title = _ocr_title(norm_line, spans)
            if not store.row_is_event(title) or len(re.findall(r"[آ-یءأإؤئ]", title)) < 2:
                continue
            key = (date["solar"][1], date["solar"][2], store.identity_key(title))
            if key in seen:
                continue
            seen.add(key)
            y, m, d = date["solar"]
            g = parse_official.jalali_to_gregorian(y, m, d)
            holiday = bool(re.search("تعطیل", line))
            start, end = date["span"]
            row = {
                "solar": [y, m, d], "gregorian": list(g), "lunar": _explicit_lunar(line),
                "weekday": None, "title": title, "holiday": holiday,
                "page": page, "derived": ["gregorian"],
                "locator": {"kind": "ocr-line", "page": page, "line": lineno,
                            "charStart": line_starts[lineno - 1] + start,
                            "charEnd": line_starts[lineno - 1] + end,
                            "lineText": norm_line[:200]},
                "bbox": None, "source": "ocr-line", "function": None,
            }
            flags = _ocr_flags(row, multiple_dates=len(dates) > 1)
            row["confidence"] = confidence(row, flags)
            row["flags"] = flags
            row["needsReview"] = True
            rows.append(row)
    rows.sort(key=lambda r: (r["solar"][1], r["solar"][2], r["title"]))
    return rows


def merge_ocr_rows(rows: list[dict], ocr_rows: list[dict]) -> list[dict]:
    """ردیف‌های OCR را کنارِ ردیف‌های لایهٔ متنی می‌گذارد، بدونِ حذف یا بازنویسی."""
    out = list(rows)
    seen = {tuple((r.get("solar") or [None, None, None])[1:])
            + (store.identity_key(r.get("title", "")),) for r in out}
    for row in ocr_rows:
        key = tuple((row.get("solar") or [None, None, None])[1:]) \
            + (store.identity_key(row.get("title", "")),)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=lambda r: ((r.get("solar") or [0, 0, 0])[1],
                            (r.get("solar") or [0, 0, 0])[2], r.get("title", "")))
    return out


def is_fragment(title: str) -> bool:
    """ردیفِ شکستهٔ ناشی از خط‌شکستنِ PDF (نه یک رویدادِ مستقل)."""
    t = _norm(title)
    words = re.findall(r"[آ-یءأإؤئ]{2,}", t)
    if not words:
        return True
    stripped = re.sub(r"[()\[\]{}،,؛;:.«»\"]|ه(?:و\s+|[.\u200c\u200d\s]+)[شق]|\d+", " ", t)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if len(stripped.split()) <= 1 and len(t) <= 30:
        return True
    if t.startswith((")", "(")) and len(words) <= 3:
        return True
    return False


def build_revision(pdf: Path, year: int | None, *, do_ocr: bool = False,
                   ocr_texts: dict[int, str] | None = None,
                   original_name: str | None = None) -> dict:
    pages = page_texts(pdf)
    blob = "\n".join(pages)
    source_name = original_name or pdf.name
    detection = detect_year(blob[:20000], source_name)
    if year is None:
        year = detection["filename"] or detection["text"]
    if year is None:
        raise ValueError("سالِ تقویم تشخیص داده نشد؛ --year بدهید")
    if not YEAR_MIN <= year <= YEAR_MAX:
        raise ValueError(f"سالِ {year} بیرون از بازهٔ پشتیبانی")
    if detection["filename"] and detection["filename"] != year and not detection["conflict"]:
        raise ValueError(f"نامِ فایل سالِ {detection['filename']} می‌گوید، درخواست {year} است")
    if detection["conflict"]:
        raise ValueError(f"تناقضِ سال: نام {detection['filename']} ≠ متن {detection['text']}; --year بدهید")

    sha = store.sha256_file(pdf)
    rid = store.revision_id(year, sha)
    parsed = parse_official.build(year, pdf)
    raw_rows = parsed.get("rows", [])
    scanned_pages = scan_pages(pages)
    ocr_results: dict[int, dict] = {}
    ocr_pages: list[int] = []
    ocr_rows: list[dict] = []
    unparsed_ocr: list[int] = []
    provided = ocr_texts or {}
    for page in scanned_pages:
        text = provided.get(page)
        if text is None and do_ocr:
            result = ocr_page(pdf, page, store.INGEST_DIR / rid / "ocr")
            ocr_results[str(page)] = {k: v for k, v in result.items() if k != "text"}
            if result.get("status") == "ok":
                text = result.get("text", "")
        elif text is not None:
            ocr_results[str(page)] = {"status": "ok", "chars": len(text.strip()),
                                      "source": "provided-ocr-text"}
        if text is None:
            continue
        parsed_ocr = parse_ocr_page(text, year, page)
        ocr_pages.append(page)
        if parsed_ocr:
            ocr_rows.extend(parsed_ocr)
        else:
            unparsed_ocr.append(page)

    rows: list[dict] = []
    flags_by_row: list[list[str]] = []
    seen: set[tuple[str, tuple[int, int]]] = set()
    for row in raw_rows:
        title = row.get("title", "")
        if not store.row_is_event(title):
            continue
        solar = row.get("solar") or [year, None, None]
        flags: list[str] = []
        if not row.get("gregorian") or None in row["gregorian"]:
            flags.append("missing-gregorian")
        if not row.get("lunar") or None in (row.get("lunar") or [None, None, None]):
            flags.append("missing-lunar")
        if len(title) < 8:
            flags.append("short-title")
        if is_fragment(title):
            flags.append("fragment")
        page = row.get("page")
        locator = page_locator(pages[page - 1], title) if page and 0 < page <= len(pages) else None
        if locator:
            locator["page"] = page
        else:
            flags.append("no-locator")
        if page and page in scanned_pages:
            flags.append("ocr-page")
        bbox = bbox_for_title(pdf, page, title) if page else None
        if page and bbox is None and _BBOX_SUPPORTED is not False:
            flags.append("no-bbox")
        key = (store.identity_key(title), (solar[1] or 0, solar[2] or 0))
        if key in seen:
            flags.append("duplicate")
        seen.add(key)
        rows.append({
            "solar": solar,
            "gregorian": row.get("gregorian"),
            "lunar": row.get("lunar"),
            "weekday": row.get("weekday"),
            "title": title,
            "holiday": bool(row.get("holiday")),
            "page": page,
            "derived": row.get("derived", []),
            "locator": locator,
            "bbox": bbox,
            "confidence": 0.0,
            "flags": sorted(set(flags)),
        })
        flags_by_row.append(sorted(set(flags)))
    for row, flags in zip(rows, flags_by_row):
        row["confidence"] = confidence(row, flags)
        row["needsReview"] = row["confidence"] < 0.8 or bool(flags)
        row["source"] = "text-layer"

    text_row_count = len(rows)
    rows = merge_ocr_rows(rows, ocr_rows)
    if ocr_rows and text_row_count:
        method = "mixed"
    elif ocr_rows:
        method = "ocr"
    else:
        method = "text-layer"

    suspicious = [r for r in rows if r.get("needsReview")]
    images: dict[str, dict] = {}
    for page in sorted({r.get("page") for r in suspicious if r.get("page")})[:40]:
        images[str(page)] = render_page(pdf, page, store.INGEST_DIR / rid / "pages")

    revision = {
        "id": rid,
        "year": year,
        "document": {"file": source_name, "originalName": source_name,
                     "sha256": sha, "bytes": pdf.stat().st_size,
                     "pages": len(pages), "storedPath": str(pdf.relative_to(ROOT))
                     if pdf.is_relative_to(ROOT) else str(pdf)},
        "extraction": {
            "method": method,
            "tool": "pdftotext -table + parse_official",
            "extractedAt": store.now_iso(),
            "rowCount": len(rows),
            "rawRowCount": len(raw_rows),
            "sourceKind": "ingested-pdf",
            "ocrPages": ocr_pages,
            "ocrPagesParsed": sorted({r["page"] for r in ocr_rows}),
            "ocrRows": len(ocr_rows),
            "ocrUnparsedPages": unparsed_ocr,
            "ocrAttempts": ocr_results,
            "scannedPages": scanned_pages,
            "qcProblems": len((parsed.get("qc") or {}).get("problems", [])),
            "locator": ("page-line" if any(r.get("locator") for r in rows) else "none"),
            "bbox": ("pt" if any(r.get("bbox") for r in rows) else "unavailable"),
            "images": images,
            "yearDetection": detection,
        },
        "state": "draft",
        "approvedBy": None,
        "approvedAt": None,
        "note": "",
        "supersedes": None,
        "supersededBy": None,
    }
    return revision, rows, parsed


def write_bundle(pdf: Path, year: int | None, *, do_ocr: bool = False,
                 ocr_texts: dict[int, str] | None = None,
                 original_name: str | None = None) -> dict:
    revision, rows, parsed = build_revision(
        pdf, year, do_ocr=do_ocr, ocr_texts=ocr_texts, original_name=original_name)
    history = store.load_history()
    existing = {r["id"]: r for r in history["revisions"]}.get(revision["id"])
    active = store.active_revisions(history["revisions"]).get(revision["year"])
    old_rows = store.load_revision_rows(active) if active else []
    if existing:
        revision["duplicateOf"] = existing["id"]
        revision["duplicateState"] = existing.get("state")
    diff = revision_diff.diff_rows(old_rows, rows, year=revision["year"], new_year=revision["year"])
    bundle = {
        "revision": revision,
        "rawRows": rows,
        "oldRevisionId": active["id"] if active else None,
        "diff": diff,
        "decisions": {},
        "state": ("no-op" if existing and
                  all(v == 0 for k, v in diff["counts"].items() if k != "UNCHANGED")
                  else "pending"),
        "createdAt": store.now_iso(),
        "sourcePdf": str(pdf.relative_to(ROOT)) if pdf.is_relative_to(ROOT) else str(pdf),
    }
    store.write_json(store.CHANGES_DIR / f"{revision['id']}.json", bundle)
    store.write_json(store.INGEST_DIR / revision["id"] / "revision.json",
                     {"revision": revision, "rows": rows, "qc": parsed.get("qc", {})})
    return bundle


def main() -> int:
    ap = argparse.ArgumentParser(description="دریافتِ PDF تقویم به پیش‌نویسِ بازبینی")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--year", type=int)
    ap.add_argument("--ocr", action="store_true", help="تلاش برای OCR صفحه‌های اسکن‌شده")
    ap.add_argument("--ocr-text-dir", help="متنِ OCR از پیش تولیدشده: page-018.txt برای هر صفحهٔ اسکن‌شده")
    args = ap.parse_args()
    pdf = Path(args.pdf)
    if not pdf.is_absolute():
        pdf = (ROOT / pdf).resolve()
    if not pdf.exists():
        print(f"PDF یافت نشد: {pdf}", file=sys.stderr)
        return 1
    ocr_texts: dict[int, str] = {}
    if args.ocr_text_dir:
        text_dir = Path(args.ocr_text_dir)
        if not text_dir.is_dir():
            print(f"پوشهٔ متنِ OCR نیست: {text_dir}", file=sys.stderr)
            return 2
        for path in sorted(text_dir.glob("page-*.txt")):
            m = re.search(r"page-(\d+)\.txt$", path.name)
            if m:
                ocr_texts[int(m.group(1))] = path.read_text(encoding="utf-8")
    try:
        bundle = write_bundle(pdf, args.year, do_ocr=args.ocr, ocr_texts=ocr_texts)
    except ValueError as exc:
        print(f"خطا: {exc}", file=sys.stderr)
        return 2
    rev = bundle["revision"]
    diff = bundle["diff"]
    print(f"{rev['id']}  سال {rev['year']}  {rev['document']['pages']} صفحه  "
          f"ردیف {rev['extraction']['rowCount']}  روش {rev['extraction']['method']}"
          + (f"  OCR={rev['extraction']['ocrRows']}" if rev['extraction'].get("ocrRows") else ""))
    print("تغییرات:", ", ".join(f"{k}={v}" for k, v in diff["counts"].items() if v))
    if bundle["state"] == "no-op":
        print(f"این سند از پیش به‌عنوان {rev['duplicateOf']} ثبت شده است.")
    blocked = [p for p, r in rev["extraction"]["ocrAttempts"].items() if r.get("status") == "blocked"]
    if rev["extraction"]["scannedPages"]:
        print(f"صفحه‌های اسکن‌شده: {rev['extraction']['scannedPages']}"
              + (f" (OCR مسدود: {', '.join(blocked)})" if blocked else ""))
    print(f"پیش‌نویس: {store.CHANGES_DIR / (rev['id'] + '.json')}")
    print("هیچ داده‌ای به تاریخچه اضافه نشد؛ ابتدا بازبینی و تأیید لازم است.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
