#!/usr/bin/env python3
"""P2-04: تطبیقِ خروجیِ وب با JSONِ منتشرشده (تعداد، تاریخ، عنوان، تعطیلی)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402

WEB = ROOT / "web" / "index.html"
OUT_MD = ROOT / "reports" / "web-consistency.md"
OUT_JSON = ROOT / "reports" / "web-consistency.json"


def payload_of(html: str) -> dict:
    marker = "const DATA = "
    start = html.find(marker)
    if start < 0:
        raise ValueError("DATA در index.html نیست")
    start += len(marker)
    end = html.find("\n", start)
    raw = html[start:end].rstrip().rstrip(";")
    return json.loads(raw)


def main() -> int:
    issues: list[dict] = []
    if not WEB.exists():
        print("web/index.html نیست؛ ابتدا build_web.py", file=sys.stderr)
        return 2
    try:
        data = payload_of(WEB.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"payload خوانده نشد: {exc}", file=sys.stderr)
        return 2
    years = data.get("years", {})
    checked = 0
    for path in sorted((ROOT / "data" / "years").glob("*.json")):
        if not path.stem.isdigit():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("mode") != "data":
            continue
        year = int(path.stem)
        web = years.get(str(year), {}).get("official", [])
        src = doc.get("rows", [])
        checked += 1
        if len(web) != len(src):
            issues.append({"code": "WEB_COUNT", "ref": str(year),
                           "message": f"{year}: وب {len(web)} ≠ JSON {len(src)}"})
            continue
        for key in ("solar", "title", "holiday"):
            a = [row.get(key) for row in web]
            b = [row.get(key) for row in src]
            if a != b:
                issues.append({"code": "WEB_FIELD", "ref": str(year),
                               "message": f"{year}: ستون {key} بین وب و JSON یکی نیست"})
                break
    payload = {"generatedAt": store.now_iso(), "checkedYears": checked,
               "issues": issues, "gate": "pass" if not issues else "fail"}
    store.write_json(OUT_JSON, payload)
    lines = ["# تطبیقِ وب و JSON", "",
             f"**نتیجه: {'سبز' if not issues else 'قرمز'}** · {checked} سالِ داده‌ای بررسی شد.", ""]
    if issues:
        lines += [f"- `{i['code']}` ({i['ref']}): {i['message']}" for i in issues]
    OUT_MD.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"web consistency gate={'PASS' if not issues else 'FAIL'} years={checked} issues={len(issues)}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
