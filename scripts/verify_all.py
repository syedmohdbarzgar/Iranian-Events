"""گیتِ انتشار: موتور + رویدادها + سال‌ها؛ خروجِ غیرصفر روی خطای بحرانی.

اجرا: `py -3 scripts/verify_all.py`. این اسکریپت هیچ داده‌ای نمی‌سازد و فقط می‌سنجد؛
اگر خطای بحرانی یا شکستِ موتور باشد، انتشار باید متوقف شود.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ("موتور تقویم", "audit_calendar.py"),
    ("سال‌ها", "build_years.py"),
    ("رویدادها و پک‌ها", "audit_events.py"),
]


def main() -> int:
    failed: list[str] = []
    for name, script in STEPS:
        print(f"== {name}: {script}")
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT)
        if res.returncode != 0:
            failed.append(f"{name} ({script})")
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=ROOT)
    if tests.returncode != 0:
        failed.append("تست‌های خودکار")
    if failed:
        print("\nگیت شکست خورد: " + "، ".join(failed))
        return 1
    print("\nگیت سبز است: موتور، سال‌ها، رویدادها و تست‌ها بدونِ خطای بحرانی.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
