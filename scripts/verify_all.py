"""گیتِ انتشار: موتور + رویدادها + سال‌ها؛ خروجِ غیرصفر روی خطای بحرانی.

اجرا: `py -3 scripts/verify_all.py`. این اسکریپت هیچ داده‌ای نمی‌سازد و فقط می‌سنجد؛
اگر خطای بحرانی یا شکستِ موتور باشد، انتشار باید متوقف شود.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# خروجیِ فارسی روی کنسولِ cp1252 ویندوز نباید گیت را بشکند.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

STEPS = [
    ("اصلاحیه‌های هویتی", "apply_identity_corrections.py"),
    ("موتور تقویم", "audit_calendar.py"),
    ("سال‌ها", "build_years.py"),
    ("شاهدِ هر رویداد", "build_event_evidence.py"),
    ("وضعیتِ مبتنی بر شاهد", "apply_evidence_status.py"),
    ("متادیتای دارایی‌های اپ", "sync_app_asset_evidence.py"),
    ("manifest داده", "build_data_manifest.py"),
    ("رویدادها و پک‌ها", "audit_events.py"),
    ("جدول‌های درهم‌ادغام", "audit_merged_tables.py"),
    ("سازگاری کاتالوگ", "check_consistency.py"),
    ("اعتبارسنجی کاتالوگ", "audit_master.py"),
    ("ردیف‌های بدونِ تطبیق", "audit_unmatched.py"),
    ("صفِ بازبینی", "build_review_queue.py"),
    ("تکرارهای کاتالوگ", "audit_catalog_duplicates.py"),
    ("استخراجِ سال‌های مسدود", "audit_extraction_issues.py"),
    ("گیتِ تاریخِ رویداد", "audit_history.py"),
    ("نمای تاریخ", "build_history_view.py"),
    ("خروجیِ وب", "build_web.py"),
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
