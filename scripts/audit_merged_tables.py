"""گزارشِ ۲۲ جدولِ رسمیِ درهم‌ادغام — فقط مستندسازی، بدونِ اصلاحِ حدسی."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AUDIT = ROOT / "reports" / "audit" / "audit.json"
OUT = ROOT / "reports" / "audit" / "merged-tables.json"
MD = ROOT / "reports" / "audit" / "merged-tables.md"


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    missing: dict[int, str] = {}
    for issue in audit.get("issues", []):
        if issue.get("check") == "Y-008" and issue.get("year"):
            missing[int(issue["year"])] = issue.get("message", "")
    rows = []
    for path in sorted(DATA.glob("official-calendar-*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        y = int(doc["year"])
        rows.append({
            "year": y,
            "rows": len(doc["rows"]),
            "pages": max((r.get("page") or 0) for r in doc["rows"]),
            "y008": y in missing,
            "finding": missing.get(y),
            "status": "needs_manual_table_rebuild" if y in missing else "no_y008",
            "note": (
                "ردیف‌های ۱۴۰۴/۱۴۰۵ فقط در موارد مستند اصلاح شدند؛ بقیهٔ ردیف‌ها بازبینیِ روزانه نشده‌اند."
                if y in (1404, 1405) else ""
            ),
        })
    doc = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(rows), "merged": sum(1 for r in rows if r["y008"]),
        "years": rows,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    lines = [
        "# جدول‌های رسمیِ درهم‌ادغام (Y-008)",
        "",
        f"- کلِ جدول: **{doc['total']}** · درهم‌ادغام: **{doc['merged']}**",
        "- هیچ ردیفی در این اجرا حذف یا با حدس جابه‌جا نشد.",
        "",
        "| سال | ردیف | صفحه | یافته | وضعیت |",
        "|---|---:|---:|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['year']} | {r['rows']} | {r['pages']} | {r['finding'] or '—'} | `{r['status']}` |"
        )
    lines += [
        "",
        "## تفسیر",
        "",
        "- ردیف‌های ۱۳۹۳/۱۳۹۶/۱۴۰۲ جدول ندارند؛ در `extraction-issues.md` مستند شده‌اند.",
        "- ۱۴۰۴/۱۴۰۵ فقط در ردیف‌های دارای شاهدِ صفحه اصلاح شدند؛ ادعای بازبینیِ کاملِ جدول نیست.",
        "- ۱۸ جدولِ دیگر برای تأییدِ روزانه قابل استناد نیستند تا بازسازیِ مختصات‌محور + بازبینیِ انسانی انجام شود.",
        "",
    ]
    MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"merged tables: {doc['merged']}/{doc['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
