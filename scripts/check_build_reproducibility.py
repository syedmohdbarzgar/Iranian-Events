#!/usr/bin/env python3
"""اجرای دوبارهٔ Build و مقایسهٔ خروجیِ محتوایی (بدونِ زمان/commit).

هدف: اثبات این‌که دو اجرای مستقل، همان داده و همان گزارش‌ها را می‌سازند.
فیلدهای provenance (``generatedAt``، ``commit``، ``workingTreeDirty``) به‌طورِ
طبیعی بین دو اجرا تغییر می‌کنند و در مقایسه نادیده گرفته می‌شوند؛ هر تغییرِ
دیگر یک ناسازگاریِ واقعی است.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "data/review/verification-queue.json",
    "reports/audit/data-manifest.json",
    "reports/audit/release-summary.md",
)
VOLATILE_KEYS = {"generatedAt", "commit", "workingTreeDirty"}


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _normalized_text(path: Path) -> str:
    if path.suffix == ".json":
        value = _strip(json.loads(path.read_text(encoding="utf-8")))
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", "<time>", text)
    text = re.sub(r"(commit[^`]*?: `)[0-9a-f]{7,40}`", r"\1<commit>`", text)
    text = text.replace(" · **درختِ کاری تمیز نیست**", "")
    return text


def digest() -> dict[str, str]:
    out = {}
    for rel in FILES:
        path = ROOT / rel
        out[rel] = hashlib.sha256(_normalized_text(path).encode("utf-8")).hexdigest()
    return out


def main() -> int:
    before = digest()
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_all.py"), "--build-only"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )
    if result.returncode:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        print("reproducibility: build failed")
        return 1
    after = digest()
    changed = [rel for rel in FILES if before[rel] != after[rel]]
    if changed:
        print("reproducibility: FAILED — content changed between two builds:")
        for rel in changed:
            print(f"  - {rel}")
        return 1
    print(f"reproducibility: PASS ({len(FILES)} outputs identical after normalizing provenance)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
