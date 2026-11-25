"""گیتِ انتشار: تولید داده، اعتبارسنجی و تست؛ خروجِ غیرصفر روی خطای بحرانی.

اجرای پیش‌فرض `py -3 scripts/verify_all.py` هر دو مرحله را پشتِ سرِ هم اجرا می‌کند.
`--build-only` فقط اسکریپت‌های تولید داده/گزارش را می‌سازد و `--audit-only` فقط
اعتبارسنجی و تست را روی خروجی‌های موجود اجرا می‌کند؛ در هیچ حالت، اسکریپتِ
اعتبارسنجی دادهٔ منتشرشده را جایگزین نمی‌کند و خروجیِ غیرصفر انتشار را متوقف می‌کند.
"""
from __future__ import annotations

import argparse
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

BUILD_SCRIPTS = {
    "apply_identity_corrections.py",
    "build_years.py",
    "build_event_evidence.py",
    "apply_evidence_status.py",
    "sync_app_asset_evidence.py",
    "build_data_manifest.py",
    "sync_report_versions.py",
    "build_review_queue.py",
    "build_history_view.py",
    "build_web.py",
}

STEPS = [
    ("اصلاحیه‌های هویتی", "apply_identity_corrections.py"),
    ("موتور تقویم", "audit_calendar.py"),
    ("سال‌ها", "build_years.py"),
    ("شاهدِ هر رویداد", "build_event_evidence.py"),
    ("وضعیتِ مبتنی بر شاهد", "apply_evidence_status.py"),
    ("متادیتای دارایی‌های اپ", "sync_app_asset_evidence.py"),
    ("manifest داده", "build_data_manifest.py"),
    ("هم‌گام‌سازیِ نسخهٔ گزارش‌ها", "sync_report_versions.py"),
    ("رویدادها و پک‌ها", "audit_events.py"),
    ("جدول‌های درهم‌ادغام", "audit_merged_tables.py"),
    ("سازگاری کاتالوگ", "check_consistency.py"),
    ("اعتبارسنجی کاتالوگ", "audit_master.py"),
    ("ردیف‌های بدونِ تطبیق", "audit_unmatched.py"),
    ("صفِ بازبینی", "build_review_queue.py"),
    ("تکرارهای کاتالوگ", "audit_catalog_duplicates.py"),
    ("استخراجِ سال‌های مسدود", "audit_extraction_issues.py"),
    ("ممیزیِ مستقلِ تصمیم‌های هویت", "audit_identity_reviews.py"),
    ("گیتِ تاریخِ رویداد", "audit_history.py"),
    ("نمای تاریخ", "build_history_view.py"),
    ("تطبیقِ آمارِ گزارش‌ها", "audit_statistics.py"),
    ("تکلیفِ سال‌های بدونِ نسخه", "audit_year_coverage.py"),
    ("خروجیِ وب", "build_web.py"),
    ("تطبیقِ وب و JSON", "audit_web_consistency.py"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="گیت انتشار Iranian-Events")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--build-only", action="store_true",
                      help="فقط تولید داده/گزارش؛ بدون تست و اعتبارسنجی")
    mode.add_argument("--audit-only", action="store_true",
                      help="فقط اعتبارسنجی و تست روی خروجی‌های موجود؛ بدون بازتولید داده")
    args = ap.parse_args()

    failed: list[str] = []
    for name, script in STEPS:
        is_build = script in BUILD_SCRIPTS
        if args.build_only and not is_build:
            continue
        if args.audit_only and is_build:
            continue
        print(f"== {name}: {script}")
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT)
        if res.returncode != 0:
            failed.append(f"{name} ({script})")
    if args.build_only:
        if failed:
            print("\nتولید داده شکست خورد: " + "، ".join(failed))
            return 1
        print("\nتولید داده سبز است؛ اعتبارسنجی جداگانه اجرا شود.")
        return 0
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
