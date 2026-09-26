"""iASPIRE Journal - Anchor 1 (J1-J10) with a ritual UX layer.
Contracts per Anchor 1 §14 are preserved at /api/aspirations, /api/aspirations/{id}/response,
/api/journal/memory. The /api/flow/* endpoints add friend-voice narration on top."""
import json, re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pipeline import Pipeline
import narrate as N

SOUL=json.load(open("soul.json"))

# Financial memory is sealed at rest when IASPIRE_MEMORY_SECRET is set. Absent a secret the
# store still works but is plaintext, and /api/health reports which mode is live - so the weak
# mode is visible rather than silent. See j9_memory.CRYPTO_NOTE for what this does and does
# not guarantee.
import os as _os
_SECRET=_os.environ.get("IASPIRE_MEMORY_SECRET") or None

def _llm_health():
    """Report the language layer honestly: whether it is on, whether it is actually reachable,
    and how arbitration is configured. Never raises - health must work when everything else
    does not."""
    try:
        import j4_llm as L
        s=L.llm_stats()
        return {"enabled":s["enabled"],"provider":s["provider"],"model":s["model"],
                "arbitration":s["arbitration"],"reachable":s["ollama_reachable"],
                "active":"model" if (s["enabled"] and s["ollama_reachable"]) else "deterministic_fallback",
                "intent_stats":s["intent"]}
    except Exception as e:
        return {"enabled":False,"active":"deterministic_fallback","error":type(e).__name__}
PIPE=Pipeline(memory_path="memory.jsonl",master_secret=_SECRET)
SESSION={"streak":0}

def _submit_flow(text):
    stages=[{"kind":"greeting","text":N.greeting(streak=SESSION["streak"])}]
    r=PIPE.submit(text)
    if r["status"]=="needs_clarification":
        stages.append({"kind":"clarify","text":N.clarify(r["intent"])})
        return {"stages":stages,"aspiration_id":r["aspiration_id"],"needs_clarification":True}
    res=r["results"][0]
    stages.append({"kind":"objective","text":N.objective(r["intent"]),
                   "confidence":r["intent"]["confidence"],"tags":["ai_hypothesis"]})
    stages.append({"kind":"evidence","lines":N.evidence(PIPE.snapshot,PIPE.behaviour,r["results"],SOUL)})
    head,body=N.verdict(res,PIPE.snapshot,challenge=r.get("challenge"))
    stages.append({"kind":"verdict","headline":head,"text":body,"outcome":res["outcome"]})
    stages.append({"kind":"options","options":N.decision_options(),
                   "alternatives":N.alternatives(r.get("alternatives",[]))})
    if r["status"]=="analysis_pending":
        stages.append({"kind":"note","text":N.pending_note(r["status"])})
    return {"stages":stages,"aspiration_id":r["aspiration_id"],"results":r["results"],
            "horizon":r["intent"]["horizon_mo"],"challenge":r.get("challenge")}

def _respond_flow(aid,response,modified):
    r=PIPE.respond(aid,response,modified)
    stages=[]
    if r["status"]=="stabilized":
        SESSION["streak"]+=1
        stages.append({"kind":"confirm","text":N.confirmation(r["goal"]),"goal":r["goal"]})
        stages.append({"kind":"memory","lines":[N.memory_line(x) for x in PIPE.memory_view()]})
    elif r["status"]=="abandoned":
        stages.append({"kind":"note","text":"Theek hai, band kar diya. Jab mann kare wapas aa jaana."})
    elif r["status"]=="re-analysed":
        head,body=N.verdict(r["results"][0],PIPE.snapshot,challenge=r.get("challenge"))
        stages.append({"kind":"evidence","lines":N.evidence(PIPE.snapshot,PIPE.behaviour,r["results"],SOUL)})
        stages.append({"kind":"verdict","headline":head,"text":body,"outcome":r["results"][0]["outcome"]})
        stages.append({"kind":"options","options":N.decision_options(),
                       "alternatives":N.alternatives(r.get("alternatives",[]))})
    else:
        stages.append({"kind":"note","text":"Ye abhi nahi ho paya. Koi baat nahi."})
    return {"stages":stages,"status":r["status"],"results":r.get("results"),"goal":r.get("goal")}

PAGE=r"""<!doctype html><meta charset=utf-8><title>iASPIRE Journal</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#12100e;--card:#1c1917;--line:#302b28;--ink:#f5f0eb;--dim:#a8a29e;--go:#4ade80;--warn:#fbbf24;--bad:#f87171}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:640px;margin:0 auto;padding:20px 18px 80px}
h1{font-size:19px;margin:0;font-weight:600;letter-spacing:.2px}
.sub{color:var(--dim);font-size:13px;margin:2px 0 22px}
.ritual{background:linear-gradient(180deg,#1f1b18,#1c1917);border:1px solid var(--line);border-radius:16px;padding:18px}
.ritual .lamp{font-size:12px;color:var(--warn);letter-spacing:1px;text-transform:uppercase}
textarea{width:100%;min-height:88px;margin:12px 0 10px;background:#14110f;border:1px solid var(--line);
 color:var(--ink);border-radius:12px;padding:14px;font:inherit;resize:vertical}
textarea:focus{outline:none;border-color:#57534e}
button{font:inherit;cursor:pointer;border-radius:12px;padding:12px 18px;border:1px solid var(--line);
 background:#262220;color:var(--ink);width:100%;text-align:left;margin-top:8px;transition:.12s}
button:hover{border-color:#57534e;background:#2f2a27}
button b{display:block;font-weight:600}
button span{display:block;font-size:13px;color:var(--dim);margin-top:2px}
button.primary{background:#4ade80;color:#14261a;border-color:#4ade80;font-weight:600;text-align:center}
button.primary:hover{background:#22c55e}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.chip{width:auto;margin:0;padding:7px 12px;font-size:13px;border-radius:999px;background:#262220;color:var(--dim)}
.msg{padding:16px 0;border-bottom:1px solid var(--line)}
.msg:last-child{border-bottom:0}
.who{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--dim);margin-bottom:6px}
.big{font-size:17px;font-weight:600;margin:0 0 6px}
.big.go{color:var(--go)}.big.warn{color:var(--warn)}.big.bad{color:var(--bad)}
details{margin-top:10px}
summary{cursor:pointer;font-size:13px;color:var(--dim);padding:6px 0}
summary:hover{color:var(--ink)}
ul{margin:8px 0 0;padding-left:18px;color:var(--dim);font-size:14px}
li{margin:4px 0}
.alt{display:inline-block;background:#262220;border:1px solid var(--line);border-radius:999px;
 padding:5px 11px;font-size:12.5px;margin:6px 6px 0 0;color:#d6d3d1}
.locked{background:#14261a;border:1px solid #4ade80;border-radius:16px;padding:18px}
.locked .who{color:var(--go)}
.mem{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:8px;
 font-size:13.5px;color:var(--dim)}
h2{font-size:12px;letter-spacing:1.2px;text-transform:uppercase;color:var(--dim);margin:28px 0 10px;font-weight:600}
.hidden{display:none}
</style>
<div class=wrap>
<h1>iASPIRE Journal</h1>
<div class=sub>Raat ka hisaab &middot; teri financial memory. Hisab main karta hun, faisla tera.</div>

<div class=ritual>
  <div class=lamp>&#10023; Raat ka Hisaab</div>
  <textarea id=txt placeholder="Bol bhai. Aaj kya hua? Paisa, koi baat, koi dard — jo mann me hai."></textarea>
  <button class=primary onclick=send(this)><b>Bol</b></button>
  <div class=chips>
    <button class=chip onclick="q('Japan trip 2.5L in 2 months')">Japan 2.5L / 2 months</button>
    <button class=chip onclick="q('Dubai family trip 1.2L in 3 months')">Dubai 1.2L / 3 months</button>
    <button class=chip onclick="q('3L for medical emergencies')">3L medical emergency</button>
    <button class=chip onclick="q('15L car next year')">15L car</button>
    <button class=chip onclick="q('hmm paisa chahiye')">Paisa chahiye</button>
  </div>
</div>

<div id=thread></div>

<h2>Teri memory</h2>
<div id=memory></div>

<h2>Jab kuch badle</h2>
<div class=ritual>
  <button class=chip onclick="change('income_drop')" style="width:auto;margin:0 8px 0 0">Aana kam ho gaya</button>
  <button class=chip onclick="change('large_withdrawal')" style="width:auto;margin:0"> Bada kharch</button>
</div>
</div>
<script>
const T=document.getElementById('thread'),M=document.getElementById('memory');
let aid=null,horizon=12,busy=false;
const e=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const q=t=>{document.getElementById('txt').value=t;document.getElementById('txt').focus()};
const who=t=>`<div class=who>${t}</div>`;
function cls(o){return o==='feasible'?'go':(o==='at-risk'?'warn':'bad')}

function render(stages){
  stages.forEach(s=>{
    let h='';
    if(s.kind==='greeting') h=who('iASPIRE')+`<div>${e(s.text)}</div>`;
    else if(s.kind==='clarify') h=who('iASPIRE')+`<div class=big warn>${e(s.text)}</div>`+
      `<button onclick="document.getElementById('txt').focus()"><b>Theek hai, poochh lo</b></button>`;
    else if(s.kind==='objective') h=who('Maine sunha')+`<div class=big>${e(s.text)}</div>`+
      `<div style="font-size:12px;color:var(--dim)">${(s.tags||[]).map(t=>'<span class=alt>'+e(t)+'</span>').join('')}<span class=alt>${Math.round((s.confidence||0)*100)}% confident</span></div>`;
    else if(s.kind==='evidence') h=who('Maine dekha')+`<details><summary>Tera hisaab kya kehta hai</summary><ul>`+
      s.lines.map(l=>`<li>${e(l)}</li>`).join('')+`</ul></details>`;
    else if(s.kind==='verdict') h=who('Mera Faisla')+`<div class="big ${cls(s.outcome)}">${e(s.headline)}</div><div>${e(s.text)}</div>`+
      ((s.alternatives&&s.alternatives.length)?`<div style="margin-top:12px">Rasta ye bhi hai:</div>${s.alternatives.map(a=>`<span class=alt>${e(a)}</span>`).join('')}`:'');
    else if(s.kind==='options') h=who('Tera faisla')+
      (s.alternatives&&s.alternatives.length?`<div style="font-size:13px;color:var(--dim);margin-bottom:2px">Mera faisla ${e(s.alternatives.join(' / '))} hai. Tu jo bole.</div>`:'')+
      s.options.map(o=>`<button onclick="choose('${o.id}',this)"><b>${e(o.label)}</b><span>${e(o.hint)}</span></button>`).join('');
    else if(s.kind==='note') h=`<div class=msg>${who('iASPIRE')}<div style="color:var(--dim)">${e(s.text)}</div></div>`;
    else if(s.kind==='confirm') h=`<div class=locked>${who('&#10003; Locked in')}<div>${e(s.text)}</div></div>`;
    else if(s.kind==='alert') h=`<div class=msg>${who('&#9888; Neend khuli')}<div class="big warn">${e(s.text)}</div></div>`;
    else if(s.kind==='memory') h=`<h2>Yaad rakh liya</h2>`+
      s.lines.map(l=>`<div class=mem>${e(l)}</div>`).join('');
    T.insertAdjacentHTML('beforeend',`<div class=msg>${h}</div>`);
    T.lastElementChild.scrollIntoView({behavior:'smooth',block:'nearest'});
  });
  if(stages.some(s=>s.kind==='confirm')) loadMem();
}

async function send(btn){
  const t=document.getElementById('txt').value.trim();
  if(!t||busy)return; busy=true;
  document.getElementById('txt').value='';
  btn.disabled=true; btn.innerHTML='<b>Soch raha hun...</b>';
  try{
    const d=await (await fetch('/api/flow/say',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:t})})).json();
    aid=d.aspiration_id; horizon=d.horizon||12;
    render(d.stages);
  }catch(err){ alert('Kuch gadbad ho gayi.'); }
  btn.disabled=false; btn.innerHTML='<b>Bol</b>'; busy=false;
}
async function choose(resp,btn){
  if(!aid||busy)return; busy=true;
  const all=[...T.querySelectorAll('button')]; all.forEach(b=>b.disabled=true);
  const label=btn.querySelector('b').textContent;
  T.insertAdjacentHTML('beforeend',`<div class=msg>${who('Tu')}<div>${e(label)}</div></div>`);
  btn.innerHTML='<b>Soch raha hun...</b>';
  const modified=resp==='modify'?{timeline_mo:horizon+6}:null;
  try{
    const d=await (await fetch('/api/flow/say',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:'__respond__',aspiration_id:aid,response:resp,modified})})).json();
    render(d.stages);
  }catch(err){ alert('Kuch gadbad ho gayi.'); }
  all.forEach(b=>b.disabled=false); busy=false;
}
async function change(kind){
  const d=await (await fetch('/api/flow/change',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({kind:kind})})).json();
  if(!d.stages||!d.stages.length){ loadMem(); return; }
  render(d.stages); loadMem();
}
async function loadMem(){
  const d=await (await fetch('/api/journal/memory/narrated')).json();
  M.innerHTML=(d.lines&&d.lines.length)?d.lines.map(l=>`<div class=mem>${e(l)}</div>`).join('')
    :'<div class=mem>Abhi kuch nahi. Upar likh ke bol.</div>';
}
loadMem();
</script>"""

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def handle_one_request(self):
        """A handler that raises must still produce a well-formed response. Without this a
        route error closes the connection with no status line at all, which is indistinguishable
        from the app being down."""
        try: super().handle_one_request()
        except Exception as e:
            try:
                self._send(500,json.dumps({"error":"internal_error","type":type(e).__name__}))
            except Exception: pass
            try: PIPE.audit_log.emit("deterministic_engine","http.handler_error",type(e).__name__,
                                     PIPE._trace("http"))
            except Exception: pass
    def _send(self,code,body,ctype="application/json"):
        raw=body.encode() if isinstance(body,str) else body
        self.send_response(code); self.send_header("Content-Type",ctype)
        self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def _body(self):
        n=int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")
    def do_GET(self):
        if self.path=="/": return self._send(200,PAGE,"text/html")
        if self.path=="/api/boom":
            if _os.environ.get("IASPIRE_TEST_ROUTES")!="1":
                return self._send(404,'{"error":"not found"}')
            raise RuntimeError("deliberate handler fault for the guard test")
        if self.path=="/api/journal/memory": return self._send(200,json.dumps({"records":PIPE.memory_view()},default=str))
        if self.path=="/api/journal/memory/narrated":
            return self._send(200,json.dumps({"lines":[N.memory_line(x) for x in PIPE.memory_view()]}))
        if self.path=="/api/audit":
            return self._send(200,json.dumps({"funnel":PIPE.funnel(),
                "actions":PIPE.audit_log.counts_by_action(),
                "read_events":len(PIPE.audit_log.read_events()),
                "recent":PIPE.audit_log.records[-25:]},default=str))
        if self.path=="/api/health":
            from j9_memory import CRYPTO_NOTE
            return self._send(200,json.dumps({
                "memory_at_rest":"sealed" if _SECRET else "PLAINTEXT_NO_SECRET_SET",
                "crypto_scheme":CRYPTO_NOTE["scheme"],
                "crypto_status":CRYPTO_NOTE["status"],
                "llm_layer":_llm_health(),
                "audit_events":len(PIPE.audit_log.records),
                "read_events":len(PIPE.audit_log.read_events()),
                "quarantined":PIPE.quarantine.count()},indent=1))
        self._send(404,'{"error":"not found"}')
    def do_POST(self):
        b=self._body()
        if self.path=="/api/flow/say" and b.get("text")=="__respond__":
            return self._send(200,json.dumps(_respond_flow(b["aspiration_id"],b["response"],b.get("modified")),default=str))
        if self.path=="/api/flow/say":
            if not b.get("text"): return self._send(400,'{"error":"text required"}')
            return self._send(200,json.dumps(_submit_flow(b["text"]),default=str))
        if self.path=="/api/flow/change":
            out=PIPE.simulate_material_change(b.get("kind","income_drop"))
            # trigger detail comes from the single audit store, not a parallel log
            fired=[r for r in PIPE.audit_log.records
                   if r["action"] in ("reanalysis.triggered","priority.raised")]
            t=(fired[-1]["detail"].get("trigger",{"type":b.get("kind","income_drop")})
               if fired else {"type":b.get("kind","income_drop")})
            stages=([{"kind":"alert","text":N.change_alert(b.get("kind"),t,out)}] if out else [])
            return self._send(200,json.dumps({"stages":stages,"reanalysis":out},default=str))
        if self.path=="/api/aspirations":
            if not b.get("text"): return self._send(400,'{"error":"text required"}')
            return self._send(200,json.dumps(PIPE.submit(b["text"]),default=str))
        m=re.match(r"^/api/aspirations/([\w]+)/response$",self.path)
        if m:
            return self._send(200,json.dumps(PIPE.respond(m.group(1),b.get("response"),b.get("modified")),default=str))
        if self.path=="/api/simulate":
            return self._send(200,json.dumps({"reanalysis":PIPE.simulate_material_change(b.get("kind","income_drop"))},default=str))
        self._send(404,'{"error":"not found"}')

if __name__=="__main__":
    print("iASPIRE Journal  ->  http://127.0.0.1:8848")
    HTTPServer(("127.0.0.1",8848),H).serve_forever()
