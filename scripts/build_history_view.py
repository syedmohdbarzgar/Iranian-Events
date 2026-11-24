"""نمای شفافِ تاریخِ هر رویداد برای کاربر (فاز ۵ چک‌لیست).

خروجی ``web/history.html`` تک‌فایل است و فقط از نسخه‌های تأییدشده می‌خواند:

* تاریخِ دقیقِ هر وقوع (شمسی/میلادی/قمری) و سالِ وقوع؛
* سال‌هایی که رویداد در سندهای بررسی‌شده دیده شده؛
* نخستین سالِ مشاهده در منابعِ پروژه، جدا از تاریخِ اصل/اعلام؛
* عنوانِ ثبت‌شده در هر سال (تغییرِ عنوان دیده می‌شود)؛
* منبع: فایل PDF، شمارهٔ صفحه، هشِ سند و شناسهٔ نسخه؛
* وضعیتِ اعتبار و سطحِ اطمینان با نشانِ صریح؛
* تفکیکِ «در سندِ این سال دیده نشد» از «برای این سال سندی بررسی نشده».

گزارشِ متنی: ``reports/history.md``.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402

OUT = ROOT / "web" / "history.html"
REPORT = ROOT / "reports" / "history.md"

STATUS_LABEL = {
    "verified": "تأییدشده",
    "partially_verified": "نیمه‌تأیید — فقط ردیفِ سند",
    "traditional": "سنتی",
    "unverified": "تأییدنشده",
}
KIND_LABEL = {
    "tradition": "آیینِ سنتی",
    "established": "تاریخِ اعلام/تصویب",
    "event": "تاریخِ وقوع",
    "first-seen": "نخستین ثبت",
    "unrecorded": "بدونِ سندِ اصل",
}


def _fmt_date(d: list) -> str:
    if not d or len(d) != 3 or None in d:
        return "—"
    return f"{d[0]}/{d[1]:02d}/{d[2]:02d}"


def build_payload() -> dict:
    history = store.load_history()
    active = store.active_revisions(history["revisions"])
    documents = {y: r["document"] for y, r in active.items()}
    doc_years = sorted(documents)
    events = history["events"]
    occ_by_event: dict[str, list[dict]] = {}
    for occ in history["occurrences"]:
        occ_by_event.setdefault(occ["eventId"], []).append(occ)

    payload_events = []
    for ev in events:
        occs = sorted(occ_by_event.get(ev["id"], []),
                      key=lambda o: (o["year"], o["date"]["solar"][1] or 0, o["date"]["solar"][2] or 0))
        years = [o["year"] for o in occs]
        first = min(years) if years else None
        last = max(years) if years else None
        missing = []
        if first is not None:
            seen = set(years)
            for y in doc_years:
                if first <= y <= last and y not in seen:
                    missing.append({"year": y, "reason": "not-seen"})
            before = [y for y in doc_years if y < first]
            if before:
                missing.append({"year": before[-1], "reason": "not-seen-before",
                                "note": f"در {len(before)} سندِ پیش از نخستین مشاهده هم نیامده است."})
        # تغییرِ سال‌به‌سال فقط از ردیف‌های دقیق و غیرمشترک سنجیده می‌شود؛ ردیفِ
        # چسبیده و جابه‌جاییِ خطوطِ PDF نباید «تغییرِ عنوان» جعلی بسازد.
        comparable = [o for o in occs
                      if o["match"]["kind"] == "exact" and not o["match"]["sharedRow"]]
        per_year: dict[int, dict] = {}
        for o in comparable:
            per_year.setdefault(o["year"], o)
        def bag(title: str) -> tuple:
            text = re.sub(r"\d+", " ", store.compare_text(title))
            return tuple(sorted(w for w in text.split() if len(w) >= 2))
        year_changes = []
        prev = None
        for y in sorted(per_year):
            cur = per_year[y]
            if prev is not None:
                old_title = store.display_clean(prev["observedTitle"])
                new_title = store.display_clean(cur["observedTitle"])
                old_bag, new_bag = set(bag(old_title)), set(bag(new_title))
                title_changed = old_bag != new_bag
                if title_changed:
                    union = old_bag | new_bag
                    jaccard = len(old_bag & new_bag) / len(union) if union else 1.0
                    if jaccard < 0.8 or max(len(old_title), len(new_title)) > 70:
                        title_changed = False
                date_changed = (ev["calendar"] == "solar"
                                and prev["date"]["solar"][1:] != cur["date"]["solar"][1:])
                if title_changed or date_changed:
                    year_changes.append({
                        "fromYear": prev["year"], "year": y,
                        "titleChanged": title_changed, "dateChanged": date_changed,
                        "fromTitle": old_title, "toTitle": new_title,
                        "fromDate": prev["date"]["solar"], "toDate": cur["date"]["solar"],
                    })
            prev = cur

        payload_events.append({
            "id": ev["id"],
            "title": ev["canonicalTitle"],
            "kind": ev["identityKind"],
            "category": ev["category"],
            "calendar": ev["calendar"],
            "status": ev["verificationStatus"],
            "established": ev["established"],
            "firstObservedYear": first,
            "firstRecordedDate": ev.get("firstRecordedDate"),
            "observedYears": years,
            "aliases": ev["aliases"],
            "yearChanges": year_changes,
            "needsReview": ev.get("needsReview", False),
            "occurrences": [{
                "year": o["year"],
                "solar": o["date"]["solar"],
                "gregorian": o["date"]["gregorian"],
                "lunar": o["date"]["lunar"],
                "approxLunar": o["date"]["approxLunar"],
                "title": o["observedTitle"],
                "holiday": o["holiday"],
                "page": o["evidence"]["page"],
                "document": o["evidence"]["documentId"],
                "sha": o["evidence"]["documentSha256"],
                "revisionId": o["evidence"]["revisionId"],
                "match": o["match"]["kind"],
                "sharedRow": o["match"]["sharedRow"],
                "status": o["verification"]["status"],
                "certainty": o["verification"]["dateCertainty"],
            } for o in occs],
            "missing": missing,
        })

    payload_events.sort(key=lambda e: (not e["observedYears"], e["firstObservedYear"] or 9999, e["title"]))
    changes = []
    for entry in history["changelog"][-30:]:
        changes.append({
            "id": entry["id"], "at": entry.get("at"), "action": entry.get("action"),
            "actor": entry.get("actor"), "year": entry.get("year"), "note": entry.get("note", ""),
            "changes": len(entry.get("changeIds") or []),
        })
    return {
        "generatedAt": store.now_iso(),
        "counts": {
            "events": len(events),
            "witnessed": sum(1 for e in events if e["observedYears"]),
            "occurrences": len(history["occurrences"]),
            "documents": len(doc_years),
            "needsReview": sum(1 for e in events if e.get("needsReview")),
        },
        "docYears": doc_years,
        "documents": [{
            "year": y,
            "file": documents[y].get("file"),
            "sha": documents[y].get("sha256"),
            "pages": documents[y].get("pages"),
        } for y in doc_years],
        "events": payload_events,
        "changelog": changes,
    }


TEMPLATE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>تاریخ رویدادها — Iranian Events</title>
<style>
:root{--bg:#0f1216;--card:#171c22;--line:#2a323c;--text:#e8edf3;--muted:#97a3b2;
--accent:#6ea8fe;--ok:#3ecf8e;--warn:#e0a33e;--danger:#e06c75;--chip:#1e2630}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:Tahoma,"Segoe UI",system-ui,sans-serif;line-height:1.8}
header{padding:28px 20px 18px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#12171d,#0f1216)}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
h1{margin:0 0 6px;font-size:26px;font-weight:700}
.sub{color:var(--muted);font-size:13px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 14px;font-size:13px}
.stat b{color:var(--accent);font-size:17px}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:20px 0}
input[type=search]{flex:1 1 260px;background:var(--card);border:1px solid var(--line);color:var(--text);
border-radius:10px;padding:10px 14px;font-family:inherit;font-size:14px}
button{background:var(--chip);border:1px solid var(--line);color:var(--text);border-radius:9px;
padding:8px 12px;font-family:inherit;font-size:13px;cursor:pointer}
button.active{border-color:var(--accent);color:var(--accent)}
.notice{background:#1b1f16;border:1px solid #3b4a2a;color:#c9dda8;border-radius:10px;padding:10px 14px;font-size:13px;margin:14px 0}
.event{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:12px 0;overflow:hidden}
.event>summary{cursor:pointer;padding:14px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;list-style:none}
.event>summary::-webkit-details-marker{display:none}
.title{font-weight:700;font-size:15px}
.meta{color:var(--muted);font-size:12px}
.badge{font-size:11px;padding:2px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.badge.partial{color:var(--warn);border-color:#4a3a1e;background:#241d12}
.badge.unverified,.badge.danger{color:var(--danger);border-color:#4a2226;background:#241416}
.badge.traditional{color:#b9a6e8;border-color:#33294a;background:#1d1830}
.badge.verified{color:var(--ok);border-color:#1e4a36;background:#12241b}
.badge.review{color:var(--warn);border-color:#4a3a1e}
.body{padding:0 16px 16px;border-top:1px solid var(--line)}
.est{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted);padding:12px 0}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:8px}
th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}
th{color:var(--muted);font-weight:600;background:#141a20}
tr.notseen td{color:#8d7a56}
tr.nodoc td{color:#6b7684}
.doc{color:var(--muted);font-size:11px}
.aliases{margin-top:10px;font-size:12px;color:var(--muted)}
.aliases span{display:inline-block;background:var(--chip);border:1px solid var(--line);border-radius:8px;padding:2px 8px;margin:3px}
.empty{color:var(--muted);font-size:13px;padding:8px 0}
.tabs{display:flex;gap:8px;margin:22px 0 6px}
.hidden{display:none}
footer{color:var(--muted);font-size:12px;padding:30px 0;text-align:center}
code{background:#11161c;border:1px solid var(--line);border-radius:5px;padding:1px 5px;font-size:11px}
@media(max-width:720px){th:nth-child(4),td:nth-child(4),th:nth-child(6),td:nth-child(6){display:none}}
</style>
</head>
<body>
<header><div class="wrap">
<h1>تاریخِ رویدادها</h1>
<div class="sub">هر سال، همان چیزی است که در سندِ همان سال ثبت شده؛ هیچ رویدادی به سالِ بی‌سند تعمیم داده نمی‌شود.</div>
<div class="stats" id="stats"></div>
</div></header>
<main class="wrap">
<div class="notice">«در سند دیده نشد» یعنی سندِ آن سال بررسی شده و این رویداد در آن نبوده؛ به‌معنای «در واقعیت رخ نداده» نیست. سالِ بدونِ سند جدا و با برچسبِ «سندی بررسی نشده» می‌آید.</div>
<div class="toolbar">
<input type="search" id="q" placeholder="جست‌وجوی عنوان، سال یا شناسه…">
<button id="f-all" class="active">همه</button>
<button id="f-witnessed">دارای سند</button>
<button id="f-review">نیازمند بازبینی</button>
<button id="f-nowitness">بدونِ سند</button>
</div>
<div id="list"></div>
<div class="tabs"><button id="tab-events" class="active">رویدادها</button><button id="tab-log">تغییرات تأییدشده</button></div>
<div id="log" class="hidden"></div>
<footer>ساخته‌شده از نسخه‌های تأییدشدهٔ تقویم · <span id="gen"></span><br>
هشِ هر سند و شمارهٔ صفحه در جدولِ هر رویداد آمده است.</footer>
</main>
<script id="payload" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('payload').textContent);
const STATUS = {verified:'تأییدشده',partially_verified:'نیمه‌تأیید — فقط ردیفِ سند',traditional:'سنتی',unverified:'تأییدنشده'};
const KIND = {tradition:'آیینِ سنتی',established:'تاریخِ اعلام/تصویب',event:'تاریخِ وقوع','first-seen':'نخستین ثبت',unrecorded:'بدونِ سندِ اصل'};
const el = (t,c,x)=>{const n=document.createElement(t); if(c)n.className=c; if(x!==undefined)n.textContent=x; return n;};
const fa = n => (n||0).toLocaleString('fa-IR');
const fmt = d => (!d||d.length!==3||d.includes(null)) ? '—' : `${d[0]}/${String(d[1]).padStart(2,'0')}/${String(d[2]).padStart(2,'0')}`;
const badge = s => el('span','badge '+(s==='partially_verified'?'partial':s), STATUS[s]||s||'—');
document.getElementById('stats').append(
  ...[['رویداد',DATA.counts.events],['دارای سند',DATA.counts.witnessed],['وقوعِ سالانه',DATA.counts.occurrences],
      ['سندِ تقویم',DATA.counts.documents],['نیازمند بازبینی',DATA.counts.needsReview]].map(([k,v])=>{
    const d=el('div','stat'); d.append(el('b',null,fa(v)),document.createTextNode(' '+k)); return d;}));
document.getElementById('gen').textContent = DATA.generatedAt;
const state={q:'',filter:'all'};
function row(occ){
  const tr=el('tr');
  [String(occ.year),fmt(occ.solar),fmt(occ.gregorian),fmt(occ.lunar)+(occ.approxLunar?' ≈':''),occ.title,
   occ.holiday?'تعطیل':'—',(occ.document||'')+ (occ.page?` ص${occ.page}`:'')].forEach((v,i)=>{
    const td=el('td',null,v); if(i===5)td.className='doc'; tr.append(td);});
  const td=el('td'); td.append(badge(occ.status));
  if(occ.sharedRow){const s=el('span','badge','ردیفِ مشترک'); td.append(' ',s);}
  tr.append(td); return tr;
}
function render(){
  const list=document.getElementById('list'); list.innerHTML='';
  const q=state.q.trim().toLowerCase();
  let shown=0;
  for(const e of DATA.events){
    if(state.filter==='witnessed'&&!e.occurrences.length) continue;
    if(state.filter==='nowitness'&&e.occurrences.length) continue;
    if(state.filter==='review'&&!e.needsReview) continue;
    const hay=(e.title+' '+e.id+' '+e.observedYears.join(' ')+' '+e.aliases.join(' ')).toLowerCase();
    if(q&&!hay.includes(q)) continue;
    shown++;
    const d=el('details','event'); const s=el('summary');
    s.append(el('span','title',e.title),el('span','meta',e.id),
      el('span','meta',e.occurrences.length?`${fa(e.occurrences.length)} وقوع · ${fa(e.observedYears[0])}–${fa(e.observedYears[e.observedYears.length-1])}`:'در هیچ سندِ بررسی‌شده‌ای دیده نشد'),
      badge(e.status));
    if(e.needsReview) s.append(el('span','badge review','نیازمند بازبینی'));
    d.append(s);
    const body=el('div','body');
    const est=el('div','est');
    est.append(el('span',null,'دسته: '+(e.category||'—')),el('span',null,'تقویم: '+(e.calendar||'—')),
      el('span',null,'اصل: '+(KIND[e.established.kind]||e.established.kind||'—')+(e.established.note?' — '+e.established.note:'')),
      el('span',null,'نخستین مشاهده: '+(e.firstObservedYear?fa(e.firstObservedYear):'—')));
    body.append(est);
    if(e.occurrences.length){
      const t=el('table'); const head=el('tr');
      ['سال','شمسی','میلادی','قمری','عنوانِ ثبت‌شده','تعطیل','سند','اعتبار'].forEach(h=>head.append(el('th',null,h)));
      t.append(head);
      for(const o of e.occurrences) t.append(row(o));
      for(const m of e.missing){
        const tr=el('tr',m.reason==='not-seen'||m.reason==='not-seen-before'?'notseen':'nodoc');
        tr.append(el('td',null,fa(m.year)),el('td',null,'—'),el('td',null,'—'),el('td',null,'—'));
        tr.append(el('td',null, m.reason==='not-seen'?'در سندِ این سال دیده نشد':'پیش از نخستین مشاهده هم در سند نبود'),el('td',null,'—'),el('td',null,'—'),el('td',null,'—'));
        t.append(tr);
      }
      body.append(t);
    } else {
      body.append(el('div','empty','این رویداد در هیچ‌یک از '+fa(DATA.counts.documents)+' سندِ بررسی‌شده دیده نشده است؛ بنابراین هیچ تاریخی برایش ساخته نشده.'));
    }
    if(e.aliases.length>1){
      const a=el('div','aliases'); a.append(el('b',null,'عنوان‌های ثبت‌شده: '));
      for(const x of e.aliases.slice(0,12)) a.append(el('span',null,x));
      body.append(a);
    }
    if(e.yearChanges.length){
      const a=el('div','aliases'); a.append(el('b',null,'تغییرِ سال‌به‌سال: '));
      for(const c of e.yearChanges.slice(0,15)){
        const parts=[]; if(c.titleChanged)parts.push('عنوان'); if(c.dateChanged)parts.push('تاریخ');
        a.append(el('span',null,`${fa(c.fromYear)}→${fa(c.year)}: ${parts.join(' + ')}`));
      }
      body.append(a);
    }
    d.append(body); list.append(d);
  }
  if(!shown) list.append(el('div','empty','موردی با این جست‌وجو پیدا نشد.'));
}
function renderLog(){
  const box=document.getElementById('log'); box.innerHTML='';
  if(!DATA.changelog.length){box.append(el('div','empty','هنوز تغییرِ تأییدشده‌ای ثبت نشده است.'));return;}
  const t=el('table'); const h=el('tr'); ['شناسه','زمان','سال','اقدام','تأییدکننده','تعداد تغییر','یادداشت'].forEach(x=>h.append(el('th',null,x))); t.append(h);
  for(const c of [...DATA.changelog].reverse()){
    const tr=el('tr'); [c.id,c.at||'—',fa(c.year),c.action,c.actor,fa(c.changes),c.note||'—'].forEach(v=>tr.append(el('td',null,v))); t.append(tr);}
  box.append(t);
}
document.getElementById('q').addEventListener('input',e=>{state.q=e.target.value;render();});
const filters=['all','witnessed','review','nowitness'];
for(const f of filters) document.getElementById('f-'+f).addEventListener('click',()=>{
  state.filter=f; for(const x of filters) document.getElementById('f-'+x).classList.toggle('active',x===f); render();});
document.getElementById('tab-events').addEventListener('click',()=>{
  document.getElementById('list').classList.remove('hidden');document.getElementById('log').classList.add('hidden');
  document.getElementById('tab-events').classList.add('active');document.getElementById('tab-log').classList.remove('active');});
document.getElementById('tab-log').addEventListener('click',()=>{
  document.getElementById('list').classList.add('hidden');document.getElementById('log').classList.remove('hidden');
  document.getElementById('tab-log').classList.add('active');document.getElementById('tab-events').classList.remove('active');});
render(); renderLog();
</script>
</body></html>
"""


def main() -> int:
    payload = build_payload()
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")

    counts = payload["counts"]
    lines = [
        "# تاریخِ رویدادها — گزارشِ نمایش",
        "",
        f"- هویت‌ها: **{counts['events']}** · دارای وقوعِ مستند: **{counts['witnessed']}** · "
        f"بدونِ هیچ سند: {counts['events'] - counts['witnessed']}",
        f"- وقوع‌های سالانه: **{counts['occurrences']}** در {counts['documents']} سند "
        f"({payload['docYears'][0]}–{payload['docYears'][-1]})" if payload["docYears"] else "- سندی موجود نیست",
        f"- نیازمندِ بازبینی: {counts['needsReview']}",
        f"- خروجی: `web/history.html` ({OUT.stat().st_size // 1024} KB)",
        "",
        "## سندهای پوشش‌داده‌شده",
        "",
        "| سال | فایل | صفحه | هش |",
        "|---|---|---|---|",
    ]
    for doc in payload["documents"]:
        lines.append(f"| {doc['year']} | {doc['file']} | {doc['pages']} | `{doc['sha'][:12]}` |")
    annual = []
    for e in payload["events"]:
        for c in e["yearChanges"]:
            annual.append((e, c))
    if annual:
        lines += ["", "## تغییراتِ سال‌به‌سال (عنوان/تاریخ)", "",
                  "برای رویدادهای قمری، جابه‌جاییِ تاریخِ شمسی طبیعی است؛ ستونِ «نوع» آن را نشان می‌دهد.", "",
                  "| رویداد | از سال | به سال | نوع | عنوانِ پیش | عنوانِ پس |",
                  "|---|---|---|---|---|---|"]
        for e, c in annual[:200]:
            kind = " + ".join((["عنوان"] if c["titleChanged"] else []) +
                              (["تاریخ"] if c["dateChanged"] else []))
            lines.append(f"| {e['title'][:45]} | {c['fromYear']} | {c['year']} | {kind} | "
                         f"{c['fromTitle'][:45]} | {c['toTitle'][:45]} |")
    review = [e for e in payload["events"] if e["needsReview"]]
    if review:
        lines += ["", "## هویت‌های نیازمندِ بازبینی", ""]
        for e in review[:60]:
            lines.append(f"- `{e['id']}` {e['title'][:100]}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"history view: events={counts['events']} witnessed={counts['witnessed']} "
          f"occurrences={counts['occurrences']} → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
