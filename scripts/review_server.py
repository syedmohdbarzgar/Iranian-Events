"""صفحهٔ محلیِ بازبینیِ تغییرات (فاز ۴ چک‌لیست).

یک سرورِ کوچکِ استاندارد-کتابخانه که فقط روی ``127.0.0.1`` گوش می‌دهد و
همان توابعِ ``review_changes.py`` را صدا می‌زند؛ بنابراین هیچ قاعدهٔ تأییدی
دوباره پیاده‌سازی نمی‌شود.

    py -3 scripts/review_server.py --port 8765

هر اجرا یک توکنِ تصادفی می‌سازد که در آدرسِ چاپ‌شده و صفحه تعبیه می‌شود؛
درخواست‌های POST بدونِ توکن رد می‌شوند. هیچ فایلی از بیرون سرو نمی‌شود.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import history_store as store  # noqa: E402
import review_changes as review  # noqa: E402

TOKEN = secrets.token_urlsafe(18)
MAX_BODY = 1 << 20


PAGE = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>بازبینی تغییرات تقویم</title>
<style>
:root{--bg:#101418;--card:#171d24;--line:#2a3440;--text:#e9eef5;--muted:#97a4b3;--accent:#6ea8fe;--ok:#3ecf8e;--danger:#e06c75;--warn:#e0a33e;--chip:#1e2731}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Tahoma,"Segoe UI",sans-serif;line-height:1.8}
header{padding:20px;border-bottom:1px solid var(--line);background:#12181f}
.wrap{max-width:1050px;margin:0 auto;padding:0 16px}
h1{margin:0;font-size:21px}.sub{color:var(--muted);font-size:12.5px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
input{background:var(--card);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:8px 11px;font-family:inherit;font-size:13px}
input[name=by]{flex:1 1 180px}input[name=note]{flex:2 1 240px}
button{background:var(--chip);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:7px 11px;font-family:inherit;font-size:13px;cursor:pointer}
button.ok{border-color:#245c42;color:var(--ok)}button.no{border-color:#5a2a30;color:var(--danger)}button.main{border-color:var(--accent);color:var(--accent)}
.bundle{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:16px 0;overflow:hidden}
.bhead{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.bhead b{font-size:15px}.meta{color:var(--muted);font-size:12px}
.change{padding:12px 16px;border-bottom:1px solid var(--line)}
.kind{font-size:11px;border:1px solid var(--line);border-radius:999px;padding:1px 8px;color:var(--warn)}
.kind.ADDED{color:var(--ok)}.kind.REMOVED{color:var(--danger)}.kind.UNCHANGED{color:var(--muted)}
.before,.after{font-size:13px;margin:5px 0}.before{color:#c9a0a5}.after{color:#a8d8b9}
.lbl{color:var(--muted);font-size:11px}
.decision{font-size:11px;color:var(--accent)}
.actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.editrow{display:none;gap:6px;flex-wrap:wrap;margin-top:8px}
.editrow.on{display:flex}
#msg{padding:10px 14px;margin:14px 0;border-radius:8px;font-size:13px;display:none}
#msg.err{display:block;background:#2a1518;border:1px solid #5a2a30;color:#f0b3b8}
#msg.ok{display:block;background:#13241b;border:1px solid #245c42;color:#a8e6c2}
.empty{color:var(--muted);padding:24px 0;text-align:center}
.pill{background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:1px 8px;font-size:11px;color:var(--muted)}
</style></head><body>
<header><div class="wrap"><h1>بازبینی تغییرات تقویم</h1>
<div class="sub">هیچ تغییری بدون تصمیمِ ثبت‌شده اعمال نمی‌شود. این سرور فقط روی همین رایانه گوش می‌دهد.</div></div></header>
<main class="wrap">
<div id="msg"></div>
<div class="bar">
<input name="by" placeholder="نامِ بررسی‌کننده (الزامی)">
<input name="note" placeholder="یادداشتِ تصمیم (اختیاری)">
<button class="main" onclick="allDecisions()">تأییدِ همهٔ پیش‌نویس‌ها</button>
<button onclick="reload()">بازخوانی</button>
</div>
<div id="bundles"></div>
<div class="empty" id="none" style="display:none">پیش‌نویسِ در انتظاری نیست. با <code>ingest_pdf.py</code> یک PDF تازه بسازید.</div>
</main>
<script>
const DATA = __DATA__;
const TOKEN = "__TOKEN__";
const agent = DATA.actor || '';
const el=(t,c,x)=>{const n=document.createElement(t);if(c)n.className=c;if(x!==undefined)n.textContent=x;return n;};
const fmt=d=>!d||d.length!==3||d.includes(null)?'—':`${d[0]}/${String(d[1]).padStart(2,'0')}/${String(d[2]).padStart(2,'0')}`;
function msg(text,ok){const m=document.getElementById('msg');m.textContent=text;m.className=ok?'ok':'err';setTimeout(()=>{m.className='';},6000);}
function reload(){location.reload();}
async function post(path,body){
  const by=(document.querySelector('input[name=by]').value||'').trim();
  const note=(document.querySelector('input[name=note]').value||'').trim();
  if(!by){msg('نامِ بررسی‌کننده را وارد کنید.');return;}
  body.by=by; body.note=note;
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Review-Token':TOKEN},body:JSON.stringify(body)});
  let j={}; try{j=await r.json();}catch(e){}
  if(!r.ok){msg(j.error||('خطای سرور: '+r.status));return;}
  msg('ثبت شد؛ صفحه بازخوانی می‌شود.',true); setTimeout(reload,500);
}
function decision(rev,change,action){
  const body={revision:rev,change:change,action:action};
  if(action==='edit'){
    const box=document.getElementById('edit-'+change);
    const title=box.querySelector('input[name=title]').value.trim();
    const solar=box.querySelector('input[name=solar]').value.trim();
    const hol=box.querySelector('select[name=holiday]').value;
    const edit={}; if(title)edit.title=title;
    if(solar)edit.solar=solar.split(/[-\\/]/).map(Number);
    if(hol!=='')edit.holiday=hol==='true';
    body.edit=edit;
  }
  post('/api/decide',body);
}
function approveAll(rev){post('/api/approve-all',{revision:rev});}
function finalize(rev){post('/api/finalize',{revision:rev});}
function reject(rev){post('/api/reject',{revision:rev});}
function toggleEdit(id){document.getElementById('edit-'+id).classList.toggle('on');}
function render(){
  const root=document.getElementById('bundles'); root.innerHTML='';
  if(!DATA.bundles.length){document.getElementById('none').style.display='block';return;}
  for(const b of DATA.bundles){
    const rev=b.revision, d=b.diff;
    const card=el('div','bundle');
    const head=el('div','bhead');
    head.append(el('b',null,`نسخهٔ ${rev.year} — ${rev.document.file}`),el('span','meta',rev.id));
    head.append(el('span','pill',`${rev.extraction.rowCount} ردیف`),el('span','pill',rev.extraction.method));
    const c=d.counts; head.append(el('span','meta',Object.entries(c).filter(([k,v])=>v).map(([k,v])=>`${k}=${v}`).join(' · ')));
    const decided=Object.keys(b.decisions||{}).length;
    head.append(el('span','pill',`${decided} تصمیم`));
    card.append(head);
    for(const ch of d.changes){
      if(ch.kind==='UNCHANGED') continue;
      const box=el('div','change');
      const line=el('div'); line.append(el('span','kind '+ch.kind,ch.kind),document.createTextNode(' '),el('span','meta',ch.dateKey));
      if(ch.similarity) line.append(document.createTextNode(' '),el('span','meta',`شباهت ${ch.similarity}`));
      if(ch.duplicateGroup) line.append(document.createTextNode(' '),el('span','pill','تکراری'));
      if(ch.suspectedSplit) line.append(document.createTextNode(' '),el('span','pill','احتمالاً قطعهٔ شکسته'));
      if(ch.requiresHuman) line.append(document.createTextNode(' '),el('span','pill','نیازمند تصمیم'));
      box.append(line);
      if(ch.before) box.append(el('div','before','پیش: '+ch.before.title));
      if(ch.after) box.append(el('div','after','پس: '+ch.after.title));
      const pg=(ch.after&&ch.after.page)||(ch.before&&ch.before.page);
      if(pg) box.append(el('div','lbl',`صفحهٔ ${pg} از PDF — تصویر در این محیط رندر نشد؛ عددِ صفحه را در سند ببینید.`));
      box.append(el('div','lbl',ch.reason||''));
      const dec=(b.decisions||{})[ch.id];
      if(dec) box.append(el('div','decision',`تصمیم: ${dec.action} — ${dec.by}${dec.edited?' (اصلاح‌شده)':''}`));
      const actions=el('div','actions');
      const a=el('button','ok','تأیید'); a.onclick=()=>decision(rev.id,ch.id,'approve'); actions.append(a);
      const r=el('button','no','رد'); r.onclick=()=>decision(rev.id,ch.id,'reject'); actions.append(r);
      const e=el('button',null,'اصلاح'); e.onclick=()=>toggleEdit(ch.id); actions.append(e);
      box.append(actions);
      const edit=el('div','editrow'); edit.id='edit-'+ch.id;
      const ti=el('input'); ti.name='title'; ti.placeholder='عنوانِ درست'; ti.style.flex='2 1 260px';
      const so=el('input'); so.name='solar'; so.placeholder='۱۴۰۵-۰۱-۰۱'; so.dir='ltr'; so.style.flex='1 1 120px';
      const hs=el('select'); hs.name='holiday'; hs.append(new Option('تعطیل: بدون تغییر',''),new Option('تعطیل','true'),new Option('غیرتعطیل','false'));
      const save=el('button','main','ثبتِ اصلاح'); save.onclick=()=>decision(rev.id,ch.id,'edit');
      edit.append(ti,so,hs,save); box.append(edit);
      card.append(box);
    }
    const foot=el('div','bhead');
    const ba=el('button','main','تأییدِ گروهی'); ba.onclick=()=>approveAll(rev.id); foot.append(ba);
    const fi=el('button','ok','اعمالِ نهایی'); fi.onclick=()=>{if(confirm('تغییراتِ تأییدشده اعمال شود؟'))finalize(rev.id);}; foot.append(fi);
    const rj=el('button','no','ردِ کل'); rj.onclick=()=>{if(confirm('کلِ پیش‌نویس رد شود؟'))reject(rev.id);}; foot.append(rj);
    foot.append(el('span','meta','اعمال فقط پس از تصمیم برای همهٔ تغییرهای نیازمندِ تصمیم ممکن است.'));
    card.append(foot);
    root.append(card);
  }
}
render();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "CalendarReview/1.0"

    def log_message(self, *args):  # noqa: D401 - خاموشیِ لاگِ پیش‌فرض
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _allowed(self) -> bool:
        if self.headers.get("X-Review-Token") != TOKEN:
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = urlparse(origin).hostname
            if host not in {"127.0.0.1", "localhost"}:
                return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            bundles = [review.load_bundle(b["revision"]["id"]) for b in review.pending_bundles()]
            payload = {"bundles": bundles, "generatedAt": store.now_iso()}
            data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
            page = PAGE.replace("__DATA__", data).replace("__TOKEN__", TOKEN)
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/pending":
            if not self._allowed():
                self._json(403, {"error": "توکنِ نامعتبر"})
                return
            self._json(200, {"bundles": review.pending_bundles(), "generatedAt": store.now_iso()})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed():
            self._json(403, {"error": "توکنِ نامعتبر یا مبدأِ نامجاز"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json(400, {"error": "بدنهٔ نامعتبر"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:  # noqa: BLE001
            self._json(400, {"error": "JSON نامعتبر"})
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/decide":
                review.decide(body["revision"], body["change"], body["action"],
                              by=body.get("by", ""), note=body.get("note", ""),
                              edit=body.get("edit"))
                self._json(200, {"ok": True})
            elif path == "/api/approve-all":
                review.approve_all(body["revision"], by=body.get("by", ""), note=body.get("note", ""))
                self._json(200, {"ok": True})
            elif path == "/api/finalize":
                result = review.finalize(body["revision"], by=body.get("by", ""), note=body.get("note", ""))
                self._json(200, {"ok": True, "log": result["entry"]["id"]})
            elif path == "/api/reject":
                review.reject_revision(body["revision"], by=body.get("by", ""), note=body.get("note", ""))
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, FileNotFoundError, KeyError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": f"خطای داخلی: {exc}"})


def main() -> int:
    ap = argparse.ArgumentParser(description="سرورِ محلیِ بازبینیِ تغییرات")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    port = server.server_address[1]
    if not args.quiet:
        print(f"بازبینی: http://127.0.0.1:{port}/  (فقط همین رایانه)")
        print(f"توکنِ نشست در صفحه تعبیه شده است؛ با بستنِ سرور باطل می‌شود.")
        print("پایان: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nبسته شد.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
