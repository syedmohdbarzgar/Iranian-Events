#!/usr/bin/env python3
"""ساختِ سایتِ تک‌فایلیِ نمایش تقویم ۱۳۴۹–۱۴۰۶ از دادهٔ استخراج‌شده از PDFها.

ورودی:  data/official-calendar-<سال>.json، data/events.json، extracted/ref/*.json
خروجی:  web/index.html  (HTML + CSS + JS + داده، همه درونِ یک فایل)

لایه‌های نمایش:
  ۱. رویدادهای رسمیِ همان سال (از جدولِ PDF همان سال) — فقط در سالِ خودشان؛
  ۲. رویدادهای تکرارشونده: شمسی/میلادی در هر سال، قمری فقط برای سال‌هایی که PDF دارند؛
  ۳. تغییراتِ هر سال: افزوده / حذف‌شده / ویرایش‌شده نسبت به سالِ قبل؛
  ۴. برای ۱۳۴۹–۱۳۸۱ که تقویمِ رسمی در PDFها نیست: گزیدهٔ رویدادهای ویکی‌شیعه.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REF = ROOT / "extracted" / "ref"
OUT = ROOT / "web"
FIRST, LAST = 1300, 1420

CULTURAL = ("نوروز", "سیزده", "چهارشنبه‌سوری", "یلدا", "مهرگان", "سده", "تیرگان", "کوسه",
            "آب‌پاشی", "سیزده‌بدر", "جشن", "عید نوروز", "روز جهانی", "روز بین‌المللی")


def jkey(title: str) -> str:
    t = re.sub(r"\([^)]*\)", "", title)
    t = re.sub(r"[\d۰-۹]+", "", t)
    t = re.sub(r"[،؛:().«»\-\s]+", " ", t)
    return t.strip()[:70]


def main() -> int:
    years: dict[int, dict] = {}
    for path in sorted(DATA.glob("official-calendar-*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        y = d["year"]
        years[y] = {"official": d["rows"], "source": d["source"]}

    sys.path.insert(0, str(ROOT / "scripts"))
    import calendar_engine as engine

    for y in years:
        for r in years[y]["official"]:
            r["title"] = engine.clean_title(r["title"])

    catalog = engine.build_catalog()
    origins = {engine.signature(e["title"]): e["origin"] for e in catalog["catalog"] if e.get("origin")}
    exact = {engine._norm(e["title"]): e["origin"]["label"] for e in catalog["catalog"] if e.get("origin")}
    cal_exact = {engine._norm(e["title"]): e.get("calendar_display", e.get("calendar", "solar"))
                 for e in catalog["catalog"]}
    cal_sig = {engine.signature(e["title"]): e.get("calendar_display", e.get("calendar", "solar"))
               for e in catalog["catalog"]}

    def cal_for(title):
        n = engine._norm(title)
        if "روز جهانی قدس" in n or "روز قدس" in n:
            return "lunar"
        return cal_exact.get(n) or cal_sig.get(engine.signature(title)) or "solar"

    def origin_label(title, year):
        n = engine._norm(title)
        if "روز جهانی قدس" in n or "روز قدس" in n:
            return "۱۶ مرداد ۱۳۵۸"
        if n in exact:
            return exact[n]
        return (origins.get(engine.signature(title)) or {}).get("label") or f"ثبت در جدول {year}"
    for y in range(FIRST, LAST + 1):
        if y in years:
            continue
        res = engine.generate(y, catalog)
        rows = [{"solar": r["solar"], "gregorian": r["gregorian"], "lunar": [],
                 "title": r["title"], "holiday": r["holiday"], "approx": r.get("approx", False),
                 "category": r.get("category", "unknown"),
                 "origin": (r.get("origin") or {}).get("label", ""),
                 "cal": cal_for(r["title"])} for r in res["rows"]]
        years[y] = {"official": rows, "source": "قاعدهٔ تکرار (بدون PDF این سال)",
                    "generated": True, "mode": res["mode"]}
    events = json.loads((DATA / "events.json").read_text(encoding="utf-8"))
    recurring = []
    for e in events:
        if len(set(e["years"])) < 6:
            continue
        first = min(e["years"])
        cultural = any(k in e["title"] for k in CULTURAL)
        base = {"title": engine.clean_title(e["title"]), "holiday": bool(e["holiday_years"]),
                "from": FIRST if cultural else first, "cultural": cultural,
                "origin": (origins.get(engine.signature(engine.clean_title(e["title"]))) or {}).get("label", "سنت"),
                "cal": cal_for(e["title"])}
        if e["calendar"] == "solar" and len(e["solar_dates"]) == 1:
            recurring.append({**base, "m": e["solar_dates"][0][0], "d": e["solar_dates"][0][1]})
        elif e["calendar"] == "gregorian" and len(e["gregorian_dates"]) == 1:
            recurring.append({**base, "cal": base.get("cal") or "gregorian",
                              "gm": e["gregorian_dates"][0][0], "gd": e["gregorian_dates"][0][1]})

    # تغییراتِ سالانه
    order = sorted(years)
    changes = {}
    for i, y in enumerate(order):
        if i == 0:
            continue
        prev = {jkey(r["title"]): r["title"] for r in years[order[i - 1]]["official"] if r["title"]}
        cur = {jkey(r["title"]): r["title"] for r in years[y]["official"] if r["title"]}
        added = [cur[k] for k in cur if k not in prev]
        removed = [prev[k] for k in prev if k not in cur]
        edited = [{"old": prev[k], "new": cur[k]} for k in cur if k in prev and prev[k] != cur[k]]
        changes[y] = {"added": added[:40], "removed": removed[:40], "edited": edited[:40],
                      "n": [len(added), len(removed), len(edited)]}
    # سال اولِ داده هم «همه‌چیز افزوده» است
    if order:
        changes[order[0]] = {"added": [r["title"] for r in years[order[0]]["official"] if r["title"]][:40],
                             "removed": [], "edited": [], "n": [len([r for r in years[order[0]]["official"] if r["title"]]), 0, 0]}

    # مقایسهٔ سال با سال قبل (فقط سال‌های دارای جدول)
    official_years = sorted(y for y in years if not years[y].get("generated"))
    by_year = {}
    for y in official_years:
        m = {}
        for r in years[y]["official"]:
            m[engine._norm(r["title"])] = {
                "title": r["title"], "s": r["solar"][1:],
                "l": (r.get("lunar") or [0, 0, 0])[1:]}
        by_year[y] = m
    compare = {}
    for y in official_years:
        if y - 1 not in by_year:
            continue
        prev, cur = by_year[y - 1], by_year[y]
        rows_cmp = []
        for key in cur:
            if key not in prev:
                continue
            a, b = prev[key], cur[key]
            if a["l"] == b["l"] and a["s"] != b["s"]:
                typ = "lunar"
            elif a["s"] == b["s"] and a["l"] != b["l"]:
                typ = "solar"
            else:
                typ = cal_sig.get(engine.signature(b["title"]), cal_exact.get(key, "solar"))
            ps, cs = a["s"], b["s"]
            if "نوروز" in b["title"]:
                ps, cs, typ = [1, 1], [1, 1], "solar"
            rows_cmp.append({"title": b["title"], "prev": ps, "cur": cs,
                             "lprev": a["l"], "lcur": b["l"], "type": typ})
        compare[y] = rows_cmp[:250]

    # گزیدهٔ ویکی‌شیعه برای سال‌های بدون PDF تقویم
    ref_years = {}
    for p in REF.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("kind") != "wiki-year" or d.get("year") is None:
            continue
        y = d["year"]
        lines = [engine.clean_title(l) for l in d.get("key_lines", []) if 12 < len(l) < 120 and not l.startswith("سال ")]
        ref_years.setdefault(y, {"first": d.get("first_day", ""), "last": d.get("last_day", ""), "lines": lines[:10]})

    payload = {
        "range": [FIRST, LAST],
        "firstOfficial": order[0] if order else LAST,
        "lastOfficial": order[-1] if order else LAST,
        "years": {str(y): {**years[y], "official": [
            {**r, "origin": r.get("origin") or origin_label(r["title"], y),
             "cal": r.get("cal") or cal_for(r["title"])}
            for r in years[y]["official"]]} for y in sorted(years)},
        "recurring": recurring[:400],
        "compare": {str(k): v for k, v in compare.items()},
        "changes": {str(k): v for k, v in changes.items()},
        "officialRange": [order[0], order[-1]] if order else [LAST, LAST],
        "rules": [
            "R1 — سال‌های دارای PDF (۱۳۸۲–۱۴۰۶): جدولِ رسمیِ همان سال، بدون بازسازی.",
            "R2 — فرهنگی (نوروز، سیزده‌بدر، یلدا…): هر سال در تاریخ شمسیِ ثابت، از ۱۳۰۰.",
            "R3 — مذهبی: وابسته به تقویم قمری؛ در سال‌های داده از جدولِ همان سال، بیرونِ آن با تقویمِ تربیعی و پرچمِ «تقریبی ±۱ روز».",
            "R4 — تاریخی (مثل ملی‌شدن نفت ۱۳۲۹): سالروزِ شمسی، از سالِ خودِ رویداد تکرار می‌شود.",
            "R5 — رسمیِ متغیر (روز زن/مرد/اصناف…): فقط از سالِ ورودش به تقویم؛ قبل از آن تولید نمی‌شود.",
            "R6 — سال‌های بعد از ۱۴۰۶: فقط رسمی‌هایی ادامه می‌یابند که در سالِ آخر حاضرند و در ۵ سالِ اخیر ≥۲ بار دیده شده‌اند؛ بقیه «نامعلوم» می‌مانند.",
            "R7 — میلادی: روزهای جهانی با تاریخ میلادیِ ثابت، در هر سال به شمسی تبدیل می‌شوند.",
            "R8 — هیچ رویدادِ سالانه از سالِ ۱۴۰۶ به بعد کپی نمی‌شود مگر در دستهٔ تکرارشوندهٔ بالا.",
        ],
        "refs": {str(k): v for k, v in ref_years.items()},
    }
    OUT.mkdir(exist_ok=True)
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"web/index.html: {len(html) / 1024:.0f}KB, years={len(order)}, recurring={len(payload['recurring'])}, refs={len(ref_years)}")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>تقویم ایران ۱۳۰۰–۱۴۲۰</title>
<style>
:root{
  --bg:#0f1115; --panel:#171a21; --panel2:#1e232c; --line:#2a3140;
  --text:#e8edf6; --muted:#95a1b5; --solar:#f5b83d; --lunar:#4ec9b0; --greg:#6ea8fe;
  --holiday:#ff6b6b; --accent:#c9a227;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:Vazirmatn,"Segoe UI",Tahoma,system-ui,sans-serif;font-size:14px;line-height:1.7}
header{position:sticky;top:0;z-index:5;background:rgba(15,17,21,.92);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line);padding:12px 18px}
.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;max-width:1400px;margin:auto}
h1{font-size:17px;margin:0;font-weight:700;letter-spacing:.2px}
h1 small{color:var(--muted);font-weight:400;font-size:12px;margin-inline-start:8px}
.controls{display:flex;gap:8px;align-items:center;margin-inline-start:auto;flex-wrap:wrap}
button,select,input{font:inherit;color:var(--text);background:var(--panel2);border:1px solid var(--line);
  border-radius:10px;padding:7px 11px;outline:none}
button{cursor:pointer;transition:.15s}
button:hover{border-color:#3b465c;background:#232a35}
button:focus-visible,select:focus-visible,input:focus-visible{border-color:var(--accent)}
#year{min-width:96px;text-align:center;font-weight:700;font-variant-numeric:tabular-nums}
.toggles{display:flex;gap:14px;align-items:center;color:var(--muted);font-size:13px}
.toggles label{display:flex;gap:6px;align-items:center;cursor:pointer}
main{max-width:1400px;margin:auto;padding:18px;display:grid;grid-template-columns:1fr 380px;gap:18px}
@media (max-width:1000px){main{grid-template-columns:1fr}}
.summary{grid-column:1/-1;display:flex;gap:14px;flex-wrap:wrap;background:var(--panel);border:1px solid var(--line);
  border-radius:14px;padding:12px 16px}
.stat{display:flex;gap:7px;align-items:baseline;color:var(--muted)}
.stat b{color:var(--text);font-size:18px;font-variant-numeric:tabular-nums}
.months{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media (max-width:1200px){.months{grid-template-columns:repeat(2,1fr)}}
@media (max-width:700px){.months{grid-template-columns:1fr}}
.month{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px 10px 8px}
.month h2{font-size:14px;margin:0 0 8px;display:flex;justify-content:space-between;align-items:center}
.month h2 span{color:var(--muted);font-size:11px;font-weight:400}
.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}
.wd{color:var(--muted);font-size:10px;text-align:center;padding:2px 0}
.wd.fri{color:var(--holiday)}
.day{min-height:44px;border-radius:9px;border:1px solid transparent;background:var(--panel2);
  padding:3px;display:flex;flex-direction:column;gap:2px;cursor:pointer;position:relative;
  font-variant-numeric:tabular-nums}
.day:hover{border-color:#3b465c}
.day.empty{background:transparent;cursor:default}
.day.today{border-color:var(--accent)}
.day.sel{border-color:#7d8aa3;background:#242c38}
.day .n{font-size:12px;color:var(--muted)}
.day.hol .n{color:#ffb3b3;font-weight:700}
.day .dots{display:flex;gap:3px;flex-wrap:wrap}
.dot{width:5px;height:5px;border-radius:50%}
.dot.solar{background:var(--solar)} .dot.lunar{background:var(--lunar)} .dot.greg{background:var(--greg)}
.day .t{font-size:9.5px;color:#c9d3e2;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
aside{position:sticky;top:76px;align-self:start;max-height:calc(100vh - 100px);overflow:auto;
  background:var(--panel);border:1px solid var(--line);border-radius:14px}
.panel-h{padding:12px 14px;border-bottom:1px solid var(--line);font-weight:700;display:flex;justify-content:space-between;align-items:center}
.panel-h small{color:var(--muted);font-weight:400}
.list{padding:8px}
.item{padding:9px 10px;border-radius:10px;border:1px solid transparent;margin-bottom:6px;background:var(--panel2)}
.item:hover{border-color:#3b465c}
.item .title{font-size:13px}
.item .meta{color:var(--muted);font-size:11px;margin-top:2px;display:flex;gap:8px;flex-wrap:wrap}
.badge{font-size:10px;padding:1px 7px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.badge.solar{color:var(--solar);border-color:#4a3c17} .badge.lunar{color:var(--lunar);border-color:#1d4a42}
.badge.greg{color:var(--greg);border-color:#243c63} .origin{font-size:11px;color:#6b7280;font-weight:500;white-space:nowrap}
.badge.hol{color:var(--holiday);border-color:#5a2626}
.empty-state{color:var(--muted);padding:18px;text-align:center;font-size:13px}
.tabs{display:flex;gap:6px;padding:8px 10px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.tabs button{padding:4px 10px;font-size:12px;border-radius:999px;background:transparent}
.tabs button.on{background:#2a3140;border-color:#3b465c;color:#fff}
.legend{display:flex;gap:14px;color:var(--muted);font-size:12px;flex-wrap:wrap;padding:8px 14px}
.legend i{display:inline-block;width:7px;height:7px;border-radius:50%;margin-inline-end:5px}
.note{grid-column:1/-1;color:var(--muted);font-size:12px;background:var(--panel);border:1px dashed var(--line);
  border-radius:12px;padding:10px 14px}
.day-detail{display:none;border-top:1px solid var(--line);padding:10px 14px}
.day-detail.open{display:block}
.day-detail h3{margin:0 0 8px;font-size:13px}
footer{max-width:1400px;margin:auto;padding:0 18px 24px;color:var(--muted);font-size:12px}
</style>
</head>
<body>
<header>
  <div class="bar">
    <h1>تقویم ایران <small>۱۳۰۰ تا ۱۴۲۰ · ۲۲ سال جدولِ رسمی و بیرونِ آن قاعده‌محور</small></h1>
    <div class="controls">
      <button id="prev" title="سال قبل">‹</button>
      <select id="year"></select>
      <button id="next" title="سال بعد">›</button>
      <input id="q" placeholder="جست‌وجوی رویداد…" aria-label="جست‌وجو">
    </div>
  </div>
  <div class="bar" style="margin-top:8px">
    <div class="toggles">
      <label><input type="checkbox" id="onlyHol"> فقط تعطیلات</label>
      <label><input type="checkbox" id="showRec" checked> رویدادهای تکرارشونده</label>
    </div>
    <div class="legend">
      <span><i style="background:var(--solar)"></i>شمسی</span>
      <span><i style="background:var(--lunar)"></i>قمری</span>
      <span><i style="background:var(--greg)"></i>میلادی</span>
      <span><i style="background:var(--holiday)"></i>تعطیل</span>
    </div>
  </div>
</header>
<main>
  <div class="summary" id="summary"></div>
  <section>
    <div class="months" id="months"></div>
    <div class="note" id="note"></div>
  </section>
  <aside>
    <div class="panel-h"><span id="sideTitle">رویدادهای سال</span><small id="sideCount"></small></div>
    <div class="tabs" id="tabs">
      <button data-tab="events" class="on">رویدادها</button>
      <button data-tab="changes">تغییرات سال</button>
      <button data-tab="cmp">مقایسه با سال قبل</button>
      <button data-tab="refs">منابع سال</button>
      <button data-tab="rules">قاعده</button>
    </div>
    <div class="day-detail" id="dayDetail"></div>
    <div class="list" id="list"></div>
  </aside>
</main>
<footer>دادهٔ رسمی از ۱۳۸۲ تا ۱۴۰۶ (۲۲ سال)؛ ۱۳۰۰–۱۳۸۱ و ۱۴۰۷–۱۴۲۰ قاعده‌محور و با وضعیتِ موقت/سنتی نمایش داده می‌شوند.
هر رویداد فقط در سال‌هایی نمایش داده می‌شود که PDF همان سال آن را دارد؛ رویدادهای تکرارشونده (فرهنگی/میلادی) در همهٔ سال‌ها بازسازی می‌شوند.</footer>
<script>
const DATA = __DATA__;
const PERSIAN = ['فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند'];
const WD = ['ش','ی','د','س','چ','پ','ج'];

function g2j(gy, gm, gd){
  const g_d_m=[0,31,59,90,120,151,181,212,243,273,304,334];
  let jy = (gy<=1600)?0:979;
  gy -= (gy<=1600)?621:1600;
  const gy2 = (gm>2)?(gy+1):gy;
  let days = (365*gy)+Math.floor((gy2+3)/4)-Math.floor((gy2+99)/100)+Math.floor((gy2+399)/400)-80+gd+g_d_m[gm-1];
  jy += 33*Math.floor(days/12053); days %= 12053;
  jy += 4*Math.floor(days/1461); days %= 1461;
  if(days>365){ jy += Math.floor((days-1)/365); days=(days-1)%365; }
  const jm = (days<186)? 1+Math.floor(days/31) : 7+Math.floor((days-186)/30);
  const jd = 1+((days<186)? (days%31) : ((days-186)%30));
  return [jy,jm,jd];
}
function j2g(jy,jm,jd){
  jy += 1595;
  let days = -355668 + 365*jy + Math.floor(jy/33)*8 + Math.floor(((jy%33)+3)/4) + jd + (jm<7 ? (jm-1)*31 : (jm-7)*30+186);
  let gy = 400*Math.floor(days/146097); days %= 146097;
  if(days>36524){ days--; gy += 100*Math.floor(days/36524); days%=36524; if(days>=365) days++; }
  gy += 4*Math.floor(days/1461); days%=1461;
  if(days>365){ gy += Math.floor((days-1)/365); days=(days-1)%365; }
  let gd = days+1;
  const leap = (gy%4===0 && gy%100!==0)||(gy%400===0);
  const ml=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31];
  let gm=1;
  for(const m of ml){ if(gd<=m) break; gd-=m; gm++; }
  return [gy,gm,gd];
}
const jdn=(jy,jm,jd)=>{const [y,m,d]=j2g(jy,jm,jd);return Math.floor(Date.UTC(y,m-1,d)/86400000)+2440588;};
const monthLen=(jy,jm)=> jm<=6?31:(jm<=11?30:(jdn(jy+1,1,1)-jdn(jy,12,1)));
const col=(jy,jm,jd)=>(new Date(Date.UTC(...j2g(jy,jm,jd))).getUTCDay()+1)%7; // شنبه=0

const yearsOfficial = Object.keys(DATA.years).map(Number).sort((a,b)=>a-b);
const state = {year: yearsOfficial[yearsOfficial.length-1], tab:'events', day:null, q:''};
const $ = s=>document.querySelector(s);
const yearSel = $('#year');
for(let y=DATA.range[0]; y<=DATA.range[1]; y++){
  const o = document.createElement('option'); o.value=y;
  o.textContent = y + (DATA.years[y] ? '' : ' *');
  yearSel.appendChild(o);
}
yearSel.value = state.year;

function recurringFor(y){
  if(!$('#showRec').checked) return [];
  const out=[];
  for(const r of DATA.recurring){
    if(y < r.from) continue;
    if(r.cal==='solar'){
      if(r.m>12 || r.d>monthLen(y,r.m)) continue;
      out.push({m:r.m,d:r.d,title:r.title,cal:'solar',holiday:r.holiday,src:'recurring',origin:r.origin});
    } else if(r.cal==='gregorian'){
      const gs = j2g(y,1,1)[0];
      for(const gy of [gs, gs+1]){
        const [jy,jm,jd] = g2j(gy, r.gm, r.gd);
        if(jy===y) out.push({m:jm,d:jd,title:r.title,cal:'gregorian',holiday:r.holiday,src:'recurring',origin:r.origin});
      }
    }
  }
  return out;
}
function officialFor(y){
  const pack=DATA.years[y]; if(!pack) return [];
  return pack.official.map(r=>({m:r.solar[1],d:r.solar[2],title:r.title,cal:r.cal||'solar',
    holiday:r.holiday, src:'official', lunar:r.lunar, greg:r.gregorian, approx:!!r.approx,
    origin:r.origin}));
}
function normT(t){return (t||'').replace(/^(آغاز|عید|شب|سالروز)\s+/,'').replace(/\s+/g,' ').trim().slice(0,18);}
function allFor(y){
  const seen=new Set(); const out=[];
  for(const e of [...officialFor(y), ...recurringFor(y)]){
    if($('#onlyHol').checked && !e.holiday) continue;
    const k = e.m+'-'+e.d+'-'+normT(e.title);
    if(seen.has(k)) continue; seen.add(k); out.push(e);
  }
  return out;
}
function render(){
  const y=state.year; yearSel.value=y;
  const evs=allFor(y);
  $('#summary').innerHTML = `
    <div class="stat"><b>${y}</b><span>سال</span></div>
    <div class="stat"><b>${evs.length}</b><span>رویداد</span></div>
    <div class="stat"><b>${evs.filter(e=>e.holiday).length}</b><span>تعطیل</span></div>
    <div class="stat"><b>${DATA.years[y] && !DATA.years[y].generated ? 'رسمی' : 'قاعده‌محور'}</b><span>${DATA.years[y]?DATA.years[y].source:''}</span></div>`;
  const byDay=new Map();
  for(const e of evs){ const k=e.m+'-'+e.d; if(!byDay.has(k)) byDay.set(k,[]); byDay.get(k).push(e); }
  let html='';
  for(let m=1;m<=12;m++){
    const len=monthLen(y,m), start=col(y,m,1);
    const [gy] = j2g(y,m,1);
    html += `<div class="month"><h2>${PERSIAN[m-1]} <span>${gy}</span></h2><div class="grid">`;
    for(const w of WD) html+=`<div class="wd ${w==='ج'?'fri':''}">${w}</div>`;
    for(let i=0;i<start;i++) html+='<div class="day empty"></div>';
    for(let d=1;d<=len;d++){
      const list=byDay.get(m+'-'+d)||[];
      const hol=list.some(e=>e.holiday);
      const dots=[...new Set(list.map(e=>e.cal==='gregorian'?'greg':e.cal==='lunar'?'lunar':'solar'))]
        .map(c=>`<span class="dot ${c}"></span>`).join('');
      const sel = state.day && state.day.m===m && state.day.d===d ? 'sel':'';
      html += `<div class="day ${hol?'hol':''} ${sel}" data-m="${m}" data-d="${d}" role="button" tabindex="0"
        aria-label="${PERSIAN[m-1]} ${d}${hol?' تعطیل':''}">
        <span class="n">${d}</span>${dots?`<span class="dots">${dots}</span>`:''}
        ${list.length?`<span class="t">${list[0].title.slice(0,42)}</span>`:''}</div>`;
    }
    html+='</div></div>';
  }
  $('#months').innerHTML=html;
  const ref=DATA.refs[y];
  $('#note').innerHTML = DATA.years[y] && !DATA.years[y].generated
    ? `دادهٔ این سال از جدولِ رسمیِ <b>${DATA.years[y].source}</b> است — ${DATA.years[y].official.length} ردیف.`
    : (DATA.years[y] && DATA.years[y].generated
        ? `این سال با <b>قاعدهٔ تکرار</b> ساخته شده: فرهنگی/مذهبی/تاریخی هر سال تکرار می‌شوند، رسمی‌های متغیر فقط از سالِ ورودشان و با شاهدِ سال‌های اخیر؛ قمری تقریبی است.`
        : (ref ? `برای این سال تقویم رسمی در PDFها نیست؛ فقط رویدادهای تکرارشونده و گزیدهٔ ویکی‌شیعه نمایش داده می‌شود.` : `برای این سال تقویم رسمی در PDFها نیست؛ فقط رویدادهای تکرارشونده نمایش داده می‌شود.`));
  renderSide(y);
}
function renderSide(y){
  const list=$('#list');
  if(state.tab==='events'){
    let evs=allFor(y);
    if(state.q) evs=evs.filter(e=>e.title.includes(state.q));
    $('#sideTitle').textContent='رویدادهای سال'; $('#sideCount').textContent=evs.length;
    if(state.day) evs=evs.filter(e=>e.m===state.day.m && e.d===state.day.d);
    if(!evs.length){list.innerHTML='<div class="empty-state">رویدادی نیست.</div>';return;}
    evs.sort((a,b)=> a.m-b.m || a.d-b.d);
    list.innerHTML=evs.map(e=>`<div class="item"><div class="title">${e.title} <span class="origin">(${e.origin||'نامشخص'})</span></div>
      <div class="meta"><span>${PERSIAN[e.m-1]} ${e.d}</span>
      <span class="badge ${e.cal==='gregorian'?'greg':e.cal==='lunar'?'lunar':'solar'}">${e.cal==='gregorian'?'میلادی':e.cal==='lunar'?'قمری':'شمسی'}</span>
      ${e.holiday?'<span class="badge hol">تعطیل</span>':''}
      ${e.src==='recurring'?'<span class="badge">تکرارشونده</span>':''}
      ${e.lunar&&e.lunar[1]?`<span>${e.lunar[0]}/${e.lunar[1]}/${e.lunar[2]} قمری</span>`:''}
      ${e.approx?'<span class="badge">قمری تقریبی ±۱ روز</span>':''}
      ${DATA.years[y]&&DATA.years[y].generated?'<span class="badge">تولید قاعده‌محور</span>':''}</div></div>`).join('');
  } else if(state.tab==='cmp'){
    const rows=DATA.compare[y];
    $('#sideTitle').textContent=`مقایسهٔ ${y-1} و ${y}`;
    if(!rows || !rows.length){
      $('#sideCount').textContent='';
      list.innerHTML='<div class="empty-state">برای این سال دادهٔ مقایسه‌ای نیست (سالِ بدون جدول یا سالِ اول).</div>';return;
    }
    $('#sideCount').textContent=rows.length;
    const T={solar:'شمسی',lunar:'قمری',gregorian:'میلادی'};
    list.innerHTML=rows.map(r=>`<div class="item"><div class="title">${r.title}
      <span class="badge ${r.type==='gregorian'?'greg':r.type==='lunar'?'lunar':'solar'}">${T[r.type]||r.type}</span></div>
      <div class="meta"><span>${y-1}: ${r.prev[0]}/${r.prev[1]} شمسی</span>
      <span>${y}: ${r.cur[0]}/${r.cur[1]} شمسی</span>
      <span>قمری: ${r.lprev[0]}/${r.lprev[1]} → ${r.lcur[0]}/${r.lcur[1]}</span></div></div>`).join('');
  } else if(state.tab==='changes'){
    const c=DATA.changes[y];
    $('#sideTitle').textContent='تغییرات نسبت به سال قبل'; 
    if(!c){list.innerHTML='<div class="empty-state">سال پایهٔ داده است (یا داده‌ای برای مقایسه نیست).</div>';$('#sideCount').textContent='';return;}
    $('#sideCount').textContent=`+${c.n[0]} −${c.n[1]} ✎${c.n[2]}`;
    let h='';
    if(c.added.length) h+=`<div class="item"><b>افزوده (${c.n[0]})</b></div>`+c.added.map(t=>`<div class="item">＋ ${t}</div>`).join('');
    if(c.removed.length) h+=`<div class="item"><b>حذف‌شده (${c.n[1]})</b></div>`+c.removed.map(t=>`<div class="item">− ${t}</div>`).join('');
    if(c.edited.length) h+=`<div class="item"><b>ویرایش متن (${c.n[2]})</b></div>`+c.edited.map(e=>`<div class="item">✎ <s style="color:#7d8aa3">${e.old}</s><br>${e.new}</div>`).join('');
    list.innerHTML=h||'<div class="empty-state">تغییری ثبت نشده.</div>';
  } else if(state.tab==='rules'){
    $('#sideTitle').textContent='قاعدهٔ تولید'; $('#sideCount').textContent='R1–R8';
    list.innerHTML=DATA.rules.map(r=>`<div class="item">${r}</div>`).join('');
  } else {
    const r=DATA.refs[y];
    $('#sideTitle').textContent='منابع سال'; $('#sideCount').textContent=r?'ویکی‌شیعه':'—';
    if(!r){list.innerHTML='<div class="empty-state">برای این سال سند مرجعی در آرشیو نیست.</div>';return;}
    let h='';
    if(r.first) h+=`<div class="item"><b>آغاز سال</b><div class="meta">${r.first}</div></div>`;
    if(r.last) h+=`<div class="item"><b>پایان سال</b><div class="meta">${r.last}</div></div>`;
    h+=r.lines.map(l=>`<div class="item">${l}</div>`).join('');
    list.innerHTML=h;
  }
}
yearSel.addEventListener('change',()=>{state.year=+yearSel.value;state.day=null;$('#dayDetail').classList.remove('open');render();});
$('#prev').onclick=()=>{if(state.year>DATA.range[0]){state.year--;state.day=null;render();}};
$('#next').onclick=()=>{if(state.year<DATA.range[1]){state.year++;state.day=null;render();}};
$('#onlyHol').onchange=render;
$('#showRec').onchange=render;
$('#q').oninput=e=>{state.q=e.target.value.trim();renderSide(state.year);};
document.addEventListener('click',e=>{
  const b=e.target.closest('.day'); if(!b||b.classList.contains('empty'))return;
  const m=+b.dataset.m,d=+b.dataset.d;
  if(state.day && state.day.m===m && state.day.d===d){state.day=null;$('#dayDetail').classList.remove('open');}
  else{
    state.day={m,d};
    const evs=allFor(state.year).filter(x=>x.m===m&&x.d===d);
    $('#dayDetail').innerHTML=`<h3>${PERSIAN[m-1]} ${d}</h3>`+(evs.length?evs.map(x=>`<div class="item">${x.title}</div>`).join(''):'<div class="empty-state">رویدادی نیست.</div>');
    $('#dayDetail').classList.add('open');
  }
  render();
});
document.querySelectorAll('#tabs button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('#tabs button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); state.tab=b.dataset.tab; renderSide(state.year);
});
render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
