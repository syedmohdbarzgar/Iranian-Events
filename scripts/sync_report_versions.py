#!/usr/bin/env python3
"""نسخهٔ داده در گزارش‌های ثابت را با manifest هم‌گام می‌کند (بدونِ بازسازی داده)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "reports" / "audit" / "data-manifest.json"
REPORTS = (
    "reports/dataset-report.md",
    "reports/audit/summary.md",
    "reports/audit/release-summary.md",
    "reports/master-validation.md",
    "reports/consistency.md",
)


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = manifest["dataVersion"]
    rows = (manifest.get("counts") or {}).get("officialRows")
    changed = 0
    for rel in REPORTS:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new = re.sub(r"v\d+\+[0-9a-f]{7}", version, text)
        if manifest.get("commit"):
            new = re.sub(r"commit: `[0-9a-f]{7,40}`", f"commit: `{manifest['commit']}`", new)
        if manifest.get("workingTreeDirty") is not None:
            new = re.sub(r" · \*\*درختِ کاری تمیز نیست\*\*", "", new)
            if manifest["workingTreeDirty"]:
                new = re.sub(r"(commit: `[^`]+`)", r"\1 · **درختِ کاری تمیز نیست**", new)
        if rows is not None:
            new = re.sub(r"(رسمیِ منتشرشده \(پس از اصلاحیه\): )\d+",
                         lambda m: m.group(1) + str(rows), new)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    print(f"report versions: {version} · updated={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
