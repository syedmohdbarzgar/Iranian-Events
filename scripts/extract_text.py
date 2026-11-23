#!/usr/bin/env python3
"""یک فایل PDF → یک فایل متن. هیچ ادغامی انجام نمی‌شود.

ورودی:  PDF/*.pdf
خروجی:  extracted/text/<slug>.txt  +  extracted/text/_index.json

هر فایل جداگانه با `pdftotext` (poppler, UTF-8) خوانده می‌شود تا بتوان بعداً
هر PDF را مستقل بازبینی و اعتبارسنجی کرد.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "PDF"
OUT_DIR = ROOT / "extracted" / "text"

BIDI = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200b\u200c\u200d\ufeff"), None)


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFC", name)
    s = re.sub(r"\.pdf$", "", s, flags=re.I)
    s = s.replace(" ", "-")
    s = re.sub(r"[^\w\-\u0600-\u06FF]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:120] or hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def extract(pdf: Path) -> tuple[str, int]:
    proc = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(pdf), "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:400])
    text = proc.stdout.decode("utf-8", "replace")
    text = text.translate(BIDI)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    pages = text.count("\f")
    return text, pages


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        slug = slugify(pdf.name)
        try:
            text, pages = extract(pdf)
            status = "ok" if text.strip() else "empty"
        except Exception as exc:  # noqa: BLE001 - گزارش و ادامه
            text, pages, status = "", 0, f"error: {exc}"
        (OUT_DIR / f"{slug}.txt").write_text(text, encoding="utf-8")
        index.append(
            {
                "file": pdf.name,
                "slug": slug,
                "pages": pages,
                "chars": len(text),
                "bytes": pdf.stat().st_size,
                "status": status,
            }
        )
        print(f"{status:5s} {pages:3d}p {len(text):8d}c  {pdf.name}")
    (OUT_DIR / "_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    bad = [i for i in index if i["status"] != "ok"]
    print(f"\n{len(index)} PDF → {len(index) - len(bad)} ok, {len(bad)} problem")
    for i in bad:
        print("  !", i["file"], i["status"][:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
