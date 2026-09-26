"""iASPIRE Journal - Anchor 1 (J1-J10) with a ritual UX layer.
Contracts per Anchor 1 §14 are preserved at /api/aspirations, /api/aspirations/{id}/response,
/api/journal/memory. The /api/flow/* endpoints add friend-voice narration on top."""
import json, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pipeline import Pipeline
import narrate as N
from chat import ChatLog

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
PIPE=Pipeline(memory_path=_os.environ.get("IASPIRE_MEMORY_FILE","memory.jsonl"),master_secret=_SECRET)
CHAT=ChatLog(path=_os.environ.get("IASPIRE_CHAT_FILE","chat_log.jsonl"))
SESSION={"streak":0,"greeted":False}

def _submit_flow(text):
    """Greeting, then the shared composer - so submit and continue cannot drift apart, and
    both get transcript logging and the editable block.

    The greeting is a welcome, not a preamble: repeating "let's go through it" before every
    message is what made this read like a form instead of a conversation."""
    stages=[]
    if not SESSION.get("greeted"):
        stages.append({"kind":"greeting","text":N.greeting(streak=SESSION["streak"])})
        SESSION["greeted"]=True
    CHAT.add("user",text)
    r=PIPE.submit(text)
    if r["status"]=="smalltalk":
        msg=N.smalltalk(text,streak=SESSION["streak"])
        stages.append({"kind":"smalltalk","text":msg})
        _log_turn(stages)
        return {"stages":stages,"aspiration_id":r["aspiration_id"],"smalltalk":True}
    if r["status"]=="needs_clarification":
        stages.append({"kind":"clarify","text":N.clarify(r["intent"])})
        _log_turn(stages)
        return {"stages":stages,"aspiration_id":r["aspiration_id"],"needs_clarification":True}
    out=_stages_from(r,PIPE.signals.get(r["aspiration_id"]))
    out["stages"]=stages+out["stages"]
    out["challenge"]=r.get("challenge")
    return out

def _continue_flow(aid,text):
    CHAT.add("user",text)
    r=PIPE.continue_aspiration(aid,text)
    if r.get("status")=="unknown_aspiration" or r.get("status")=="nothing_to_continue":
        return {"stages":[{"kind":"note","text":"I don't have that in front of me. Say it again."}]}
    return _stages_from(r,PIPE.signals.get(aid))

def _stages_from(r,signal):
    """One composer for both entry paths, so submit and continue cannot drift apart."""
    stages=[]
    if r["status"]=="analysis_pending":
        stages.append({"kind":"note","text":r.get("note","Ask me again in a moment.")})
        _log_turn(stages)
        return {"stages":stages,"aspiration_id":r["aspiration_id"]}
    res=r["results"][0]
    stages.append({"kind":"objective","text":N.objective(r["intent"]),
                   "confidence":r["intent"]["confidence"],"tags":["ai_hypothesis"]})
    stages.append({"kind":"evidence","lines":N.evidence(PIPE.snapshot,PIPE.behaviour,r["results"],SOUL)})
    head,body=N.verdict(res,PIPE.snapshot,challenge=r.get("challenge"))
    stages.append({"kind":"verdict","headline":head,"text":body,"outcome":res["outcome"]})
    stages.append({"kind":"options","options":N.decision_options(),
                   "alternatives":N.alternatives(r.get("alternatives",[])),
                   "editable":_editable(r)})
    _log_turn(stages)
    return {"stages":stages,"aspiration_id":r["aspiration_id"],"results":r["results"],
            "horizon":r["intent"].get("horizon_mo",12),"candidates":r["candidates"],
            "editable":stages[-1].get("editable") if stages else None}

def _log_turn(stages):
    """Persist the assistant side of a turn, one line per bubble."""
    for s in stages:
        if s["kind"]=="clarify" or s["kind"]=="note": CHAT.add("app",s["text"],{"kind":s["kind"]})
        elif s["kind"]=="verdict": CHAT.add("app",s["headline"]+"\n"+s["text"],{"kind":s["kind"],"outcome":s["outcome"]})
        elif s["kind"]=="confirm": CHAT.add("app",s["text"],{"kind":s["kind"]})

def _editable(r):
    """U1: the customer is handed real, editable values - not one canned button. Prefilled
    with the engine's current numbers and the mechanisms it actually considered."""
    c=r["results"][0]; cd=r["candidates"][0]; i=r["intent"]
    return {"target":i.get("amount") or c["required_capital"],
            "timeline_mo":i.get("horizon_mo",12),
            "mechanisms":[x["mechanism"] for x in r["candidates"]],
            "mechanism":cd["mechanism"],
            "monthly_need":c["monthly_need"],
            "avail":c.get("avail_stress_monthly",c["avail_monthly"]),
            "shortfall":c["gap_amount"]}

def _respond_flow(aid,response,modified):
    r=PIPE.respond(aid,response,modified)
    stages=[]
    if r["status"]=="stabilized":
        SESSION["streak"]+=1
        stages.append({"kind":"confirm","text":N.confirmation(r["goal"]),"goal":r["goal"]})
        CHAT.add("user",(r.get("user_label") or "accepted"))
        CHAT.add("app",N.confirmation(r["goal"]),{"kind":"confirm"})
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
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<style>
:root{--bg:#0b141a;--panel:#111b21;--panel2:#202c33;--line:#2a3942;--ink:#e9edef;
      --dim:#8696a0;--out:#005c4b;--in:#202c33;--go:#25d366;--warn:#fbbf24;--bad:#f87171}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.app{display:flex;flex-direction:column;height:100dvh;max-width:720px;margin:0 auto}
header{background:var(--panel);border-bottom:1px solid var(--line);padding:11px 14px;
 display:flex;align-items:center;gap:11px;flex:0 0 auto}
.av{width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,#25d366,#0b7a5a);
 display:grid;place-items:center;font-weight:700;font-size:15px;flex:0 0 auto}
.hm{flex:1;min-width:0}
.hm b{display:block;font-size:15px;font-weight:600}
.hm span{font-size:12.5px;color:var(--dim);display:block}
.hbtn{background:transparent;border:0;color:var(--dim);font-size:12px;padding:7px 9px;
 border-radius:8px;cursor:pointer;text-decoration:none;white-space:nowrap}
.hbtn:hover{background:var(--panel2);color:var(--ink)}
#log{flex:1 1 auto;overflow-y:auto;padding:16px 12px 8px;
 background-color:var(--bg);
 background-image:radial-gradient(rgba(255,255,255,.028) 1px,transparent 1px);
 background-size:22px 22px}
.day{text-align:center;margin:12px 0 14px}
.day span{background:var(--panel2);color:var(--dim);font-size:11.5px;padding:5px 12px;border-radius:8px}
.row{display:flex;margin-bottom:7px}
.row.me{justify-content:flex-end}
.bubble{max-width:78%;padding:8px 11px 7px;border-radius:9px;position:relative;font-size:14.6px;
 word-wrap:break-word;box-shadow:0 1px .5px rgba(0,0,0,.3)}
.row.me .bubble{background:var(--out);border-top-right-radius:2px}
.row.app .bubble{background:var(--in);border-top-left-radius:2px}
.bubble .t{display:block}
.bubble .meta{display:block;font-size:10.5px;color:rgba(255,255,255,.45);margin-top:3px;text-align:right}
.bubble .hd{font-weight:700;display:block;margin-bottom:3px;font-size:15px}
.bubble .hd.go{color:var(--go)}.bubble .hd.warn{color:var(--warn)}.bubble .hd.bad{color:var(--bad)}
.bubble .quote{border-left:3px solid var(--go);padding-left:9px;margin-top:7px;color:rgba(255,255,255,.82)}
details{background:rgba(0,0,0,.22);border-radius:8px;padding:7px 10px;margin-top:8px}
summary{cursor:pointer;font-size:12.8px;color:#b6c3ca;list-style:none}
summary::-webkit-details-marker{display:none}
summary:before{content:"▸ ";}
details[open] summary:before{content:"▾ ";}
details ul{margin:7px 0 2px;padding-left:16px;color:#c3ced4;font-size:13.4px}
details li{margin:2px 0}
.alt{display:inline-block;background:rgba(0,0,0,.24);border-radius:999px;padding:4px 10px;
 font-size:12.3px;margin:6px 4px 0 0;color:#dbe4e8}
.pick{background:rgba(0,0,0,.24);border-radius:9px;padding:10px;margin-top:10px}
.pick .lb{font-size:10.5px;letter-spacing:.7px;text-transform:uppercase;color:#8fa1ab;margin:9px 0 4px}
.pick .lb:first-child{margin-top:0}
.rw{display:flex;gap:8px}
.rw>div{flex:1}
input[type=number],select{width:100%;background:#2a3942;border:1px solid #3b4d57;color:var(--ink);
 border-radius:7px;padding:8px 10px;font:inherit;font-size:14px}
input:focus,select:focus{outline:none;border-color:var(--go)}
.math{font-size:12.6px;color:#c3ced4;margin-top:9px;padding-top:8px;border-top:1px solid #3b4d57}
.act{width:100%;background:#0b7a5a;border:0;color:#fff;font:inherit;font-weight:600;
 padding:10px;border-radius:8px;margin-top:10px;cursor:pointer}
.act:hover{background:#0d8a66}
.choices{margin-top:9px}
.choices button{width:100%;text-align:left;background:rgba(0,0,0,.24);border:0;color:var(--ink);
 font:inherit;padding:9px 11px;border-radius:8px;margin-top:6px;cursor:pointer}
.choices button:hover{background:rgba(0,0,0,.34)}
.choices button b{display:block;font-size:14.2px}
.choices button span{display:block;font-size:12.2px;color:#93a4ad;margin-top:1px}
.choices button.pri{background:var(--go);color:#06231a;font-weight:600;text-align:center}
.choices button.pri:hover{background:#1eb857}
.locked{background:#0d3b30;border:1px solid #1c6b56;border-radius:9px;padding:9px 11px;margin:7px 0}
.sys{text-align:center;margin:11px 0}
.sys span{background:rgba(0,0,0,.32);color:var(--dim);font-size:11.8px;padding:5px 11px;border-radius:7px}
footer{flex:0 0 auto;background:var(--panel);border-top:1px solid var(--line);padding:9px 10px}
.composer{display:flex;gap:8px;align-items:flex-end}
.composer textarea{flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--ink);
 border-radius:20px;padding:10px 13px;font:inherit;resize:none;max-height:110px;min-height:40px}
.composer textarea:focus{outline:none;border-color:#3b4d57}
.send{width:42px;height:42px;flex:0 0 auto;border-radius:50%;background:var(--go);border:0;
 color:#06231a;font-size:19px;cursor:pointer;display:grid;place-items:center}
.send:disabled{background:#3b4d57;color:#8696a0;cursor:default}
.hints{display:flex;gap:7px;overflow-x:auto;padding:8px 2px 2px;scrollbar-width:none}
.hints::-webkit-scrollbar{display:none}
.hints button{white-space:nowrap;background:var(--panel2);border:0;color:#c3ced4;font:inherit;
 font-size:12.3px;padding:6px 11px;border-radius:999px;cursor:pointer}
.empty{text-align:center;color:var(--dim);padding:44px 18px;font-size:14px}
.empty b{display:block;font-size:16px;color:var(--ink);margin-bottom:7px}
.pill{font-size:10.5px;letter-spacing:.5px;text-transform:uppercase;padding:3px 8px;border-radius:999px;font-weight:600}
.pill.on_track{background:#0d3b30;color:var(--go)}
.pill.tight{background:#332a10;color:var(--warn)}
.pill.behind,.pill.at_risk{background:#3a1414;color:#fca5a5}
.pill.urgent{background:#3a1414;color:#fca5a5;animation:p 1.5s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.5}}
.goal{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:13px;margin:9px 0}
.goal .top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.goal .why{font-size:13.4px;color:var(--dim);margin-top:5px}
.goal .act2{font-size:13.4px;color:var(--go);margin-top:6px}
.sec{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:13px;margin:9px 0}
.sec h3{margin:0 0 4px;font-size:14px}
.sec p{margin:0;color:var(--dim);font-size:13.2px}
.turn{padding:9px 0;border-bottom:1px solid var(--line);font-size:14px}
.turn:last-child{border-bottom:0}
.turn .w{font-size:10.5px;letter-spacing:.6px;text-transform:uppercase;color:var(--dim);margin-bottom:3px}
.turn.me .t{color:#8ce0c4}
.tabs{display:flex;gap:7px;padding:10px 14px 0}
.tabs a{flex:1;text-align:center;padding:9px;background:var(--panel);border:1px solid var(--line);
 border-bottom:0;border-radius:9px 9px 0 0;color:var(--dim);text-decoration:none;font-size:13.4px}
.tabs a.on{background:var(--bg);color:var(--ink);font-weight:600}
</style>
<div class=app>
<header>
  <div class=av>iA</div>
  <div class=hm><b>iASPIRE Journal</b><span id=st>online</span></div>
  <a class=hbtn href="/data">Stored data</a>
  <button class=hbtn onclick="wipe()">Clear</button>
</header>
<div id=log><div class=empty><b>Say what is on your mind</b>
Money, a worry, a goal for next year. One line is enough — I will work out the rest.</div></div>
<footer>
  <div class=hints>
    <button onclick="q('Japan trip 2.5L in 2 months')">Japan 2.5L / 2 months</button>
    <button onclick="q('Dubai family trip 1.2L in 3 months')">Dubai 1.2L / 3 months</button>
    <button onclick="q('I want to save 3L for medical emergencies')">3L for medical</button>
    <button onclick="q('15L car next year')">15L car</button>
    <button onclick="q('not sure what I need')">Not sure yet</button>
  </div>
  <div class=composer style="margin-top:8px">
    <textarea id=txt rows=1 placeholder="Type a message"></textarea>
    <button class=send id=send onclick=send(this)>&#9654;</button>
  </div>
</footer>
</div>
<script>
const L=document.getElementById('log'),T=document.getElementById('txt'),S=document.getElementById('send');
let aid=null,pending=null,horizon=12,busy=false,lastEdit=null;
const e=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const cls=o=>o==='feasible'?'go':(o==='at-risk'?'warn':'bad');
function q(t){T.value=t;T.focus()}
T.addEventListener('input',()=>{T.style.height='auto';T.style.height=Math.min(T.scrollHeight,110)+'px'});
T.addEventListener('keydown',ev=>{if(ev.key==='Enter'&&!ev.shiftKey){ev.preventDefault();send(S)}});
function atBottom(){return L.scrollHeight-L.scrollTop-L.clientHeight<140}
function scroll(f){if(f!==false)L.scrollTop=L.scrollHeight}
function addMe(t){const stick=atBottom();
  L.insertAdjacentHTML('beforeend','<div class="row me"><div class=bubble><span class=t>'+e(t)+
  '</span><span class=meta>now</span></div></div>');scroll(stick)}
function addApp(html){const stick=atBottom();
  L.insertAdjacentHTML('beforeend','<div class="row app"><div class=bubble>'+html+'</div></div>');scroll(stick)}
function addSys(t){L.insertAdjacentHTML('beforeend','<div class=sys><span>'+e(t)+'</span></div>');scroll()}
function addLocked(html){L.insertAdjacentHTML('beforeend','<div class=locked>'+html+'</div>');scroll()}

/* the transcript lives on the server, so a reload restores the whole conversation */
async function load(){
  const d=await (await fetch('/api/chat')).json();
  if(!d.turns.length)return;
  L.innerHTML='<div class=day"><span>Conversation</span></div>';
  for(const t of d.turns){
    if(t.role==='user') addMe(t.text);
    else if(t.meta&&t.meta.kind==='verdict')
      addApp('<span class="hd '+cls(t.meta.outcome)+'">'+e(t.text.split('\n')[0])+'</span><span class=t>'+
        e(t.text.split('\n').slice(1).join(' '))+'</span><span class=meta>now</span>');
    else if(t.meta&&(t.meta.kind==='confirm'))
      addLocked('<span class="hd go">Locked in</span><span class=t>'+e(t.text)+'</span>');
    else if(t.meta&&t.meta.kind==='event') addSys(t.text);
    else addApp('<span class=t>'+e(t.text)+'</span><span class=meta>now</span>');
  }
  scroll();
}
function editor(ed){
  if(!ed)return '';
  const opts=ed.mechanisms.map(m=>'<option value="'+e(m)+'"'+(m===ed.mechanism?' selected':'')+'>'+e(m)+'</option>').join('');
  return '<div class=pick><div class=lb>Your call — change any of it</div>'+
   '<div class=rw><div><div class=lb>Amount (Rs)</div><input type=number id=edTarget value="'+ed.target+'" step=10000 min=0></div>'+
   '<div><div class=lb>Months</div><input type=number id=edTime value="'+ed.timeline_mo+'" min=1 max=120></div></div>'+
   '<div class=lb>Method</div><select id=edMech>'+opts+'</select>'+
   '<div class=math id=edMath></div>'+
   '<button class=act onclick="applyEdit(this)">Recalculate with these</button></div>';
}
function edMath(){
  const el=document.getElementById('edMath');if(!el)return;
  const t=+document.getElementById('edTarget').value||0,m=+document.getElementById('edTime').value||1;
  const per=t/m,gap=per-(lastEdit.avail||0);
  el.innerHTML='That is <b>'+fmt(per)+'</b> a month. Your limit is <b>'+fmt(lastEdit.avail)+'</b>. '+
   (gap>0?'<span style="color:#fca5a5">Short by '+fmt(gap)+'.</span>'
          :'<span style="color:#25d366">'+fmt(-gap)+' to spare.</span>');
}
function fmt(n){n=Math.round(n);return n>=100000?'Rs '+(n/100000).toFixed(2)+'L':'Rs '+n.toLocaleString()}
document.addEventListener('input',ev=>{if(ev.target&&ev.target.id&&ev.target.id.indexOf('ed')===0)edMath()});

function render(stages,ed){
  if(ed)lastEdit=ed;
  (stages||[]).forEach(s=>{
    if(s.kind==='greeting') addApp('<span class=t>'+e(s.text)+'</span><span class=meta>now</span>');
    else if(s.kind==='clarify')
      addApp('<span class=hd warn>One question</span><span class=t>'+e(s.text)+'</span><span class=meta>now</span>');
    else if(s.kind==='smalltalk')
      addApp('<span class=t>'+e(s.text)+'</span><span class=meta>now</span>');
    else if(s.kind==='objective')
      addApp('<span class=t>'+e(s.text)+'</span><span class=meta>now</span>');
    else if(s.kind==='evidence')
      addApp('<details><summary>What I checked ('+s.lines.length+' numbers)</summary><ul>'+
        s.lines.map(l=>'<li>'+e(l)+'</li>').join('')+'</ul></details>');
    else if(s.kind==='verdict')
      addApp('<span class="hd '+cls(s.outcome)+'">'+e(s.headline)+'</span><span class=t>'+e(s.text)+'</span>'+
        ((s.alternatives&&s.alternatives.length)?'<div style="margin-top:8px">Another way:</div>'+
          s.alternatives.map(a=>'<span class=alt>'+e(a)+'</span>').join(''):'')+'<span class=meta>now</span>');
    else if(s.kind==='options'){
      if(s.editable)edMath();
      addApp('<div class=choices>'+s.options.map(o=>
        '<button onclick="choose(\''+o.id+'\',this,false)"><b>'+e(o.label)+'</b><span>'+e(o.hint)+'</span></button>').join('')+
        '</div>'+editor(s.editable));
    }
    else if(s.kind==='note') addSys(s.text);
    else if(s.kind==='confirm') addLocked('<span class=hd go>Locked in</span><span class=t>'+e(s.text)+'</span>');
    else if(s.kind==='alert') addApp('<span class=hd warn>Heads up</span><span class=t>'+e(s.text)+'</span><span class=meta>now</span>');
  });
  scroll();
}
async function send(btn){
  const t=T.value.trim();if(!t||busy)return;busy=true;T.value='';T.style.height='auto';
  addMe(t);btn.disabled=true;
  try{
    const url=pending?('/api/aspirations/'+pending+'/continue'):'/api/flow/say';
    const d=await (await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:t})})).json();
    aid=d.aspiration_id||aid;if(d.horizon)horizon=d.horizon;
    pending=(d.stages||[]).some(s=>s.kind==='clarify')?aid:null;
    render(d.stages,d.editable);
  }catch(err){addSys('Something went wrong. Try again.')}
  btn.disabled=false;busy=false;T.focus();
}
function applyEdit(btn){choose('modify',btn,true)}
async function choose(resp,btn,fromEditor){
  if(!aid||busy)return;
  let modified=null,label='Yes, lock it in';
  if(resp==='modify'){
    if(fromEditor){
      const t=document.getElementById('edTarget'),m=document.getElementById('edTime'),me=document.getElementById('edMech');
      modified={};if(t)modified.target=+t.value||undefined;
      if(m)modified.timeline_mo=+m.value||undefined;if(me)modified.mechanism=me.value||undefined;
      label='Let us try '+fmt(modified.target||0)+' over '+(modified.timeline_mo||'?')+' months';
    } else { modified={timeline_mo:(horizon||12)+6}; label='Give it more time'; }
  } else if(resp==='reject') label='Not right now';
  if(!fromEditor) addMe(label);
  try{
    const d=await (await fetch('/api/flow/say',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:'__respond__',aspiration_id:aid,response:resp,modified:modified,
                           user_label:label})})).json();
    pending=null;render(d.stages,d.editable);
  }catch(err){addSys('Something went wrong.')}
  busy=false;
}
async function change(kind){
  const d=await (await fetch('/api/flow/change',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({kind:kind})})).json();
  if(d.stages&&d.stages.length)render(d.stages);
  else addSys('Nothing changed for your goals.');
}
async function wipe(){
  if(!confirm('Clear this conversation? Your saved goals stay.'))return;
  await fetch('/api/chat/clear',{method:'POST'});L.innerHTML='';load();
}
load();
</script>"""

DATA_PAGE=r"""<!doctype html><meta charset=utf-8><title>iASPIRE — Stored data</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b141a;--panel:#111b21;--panel2:#202c33;--line:#2a3942;--ink:#e9edef;--dim:#8696a0;--go:#25d366;--warn:#fbbf24}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.w{max-width:720px;margin:0 auto;padding:0 0 60px}
header{background:var(--panel);border-bottom:1px solid var(--line);padding:12px 14px;display:flex;
 align-items:center;gap:10px;position:sticky;top:0;z-index:5}
.av{width:34px;height:34px;border-radius:50%;background:linear-gradient(135deg,#25d366,#0b7a5a);
 display:grid;place-items:center;font-weight:700;font-size:14px}
header b{display:block;font-size:15px}
header span{font-size:12.3px;color:var(--dim)}
a.hb{color:var(--dim);text-decoration:none;font-size:12.5px;padding:7px 10px;border-radius:8px;background:var(--panel2)}
h2{font-size:11.5px;letter-spacing:1.1px;text-transform:uppercase;color:var(--dim);margin:24px 14px 8px}
.goal{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:13px;margin:9px 14px}
.goal .top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.goal .why{font-size:13.4px;color:var(--dim);margin-top:5px}
.goal .a{font-size:13.4px;color:var(--go);margin-top:6px}
.pill{font-size:10.5px;letter-spacing:.5px;text-transform:uppercase;padding:3px 8px;border-radius:999px;font-weight:600}
.on_track{background:#0d3b30;color:var(--go)}.tight{background:#332a10;color:var(--warn)}
.behind,.at_risk{background:#3a1414;color:#fca5a5}
.urgent{background:#3a1414;color:#fca5a5;animation:p 1.5s infinite}@keyframes p{0%,100%{opacity:1}50%{opacity:.5}}
.turn{padding:9px 14px;border-bottom:1px solid var(--line);font-size:14px}
.turn:last-child{border-bottom:0}
.turn .w{font-size:10.5px;letter-spacing:.6px;text-transform:uppercase;color:var(--dim);margin-bottom:3px}
.turn.me .t{color:#8ce0c4}
.turn.app .t{color:#c9d4da}
.empty{color:var(--dim);padding:16px 14px;font-size:14px}
</style>
<div class=w>
<header><div class=av>iA</div><div style=flex:1><b>Stored data</b><span>Everything the journal has kept</span></div>
<a class=hb href="/">&larr; Back to chat</a></header>
<h2>Your goals</h2><div id=g></div>
<h2>Conversation history</h2><div id=h></div>
</div>
<script>
const e=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const fmt=n=>{n=Math.round(n);return n>=100000?'Rs '+(n/100000).toFixed(2)+'L':'Rs '+n.toLocaleString()};
const LBL={on_track:'on track',tight:'tight',behind:'behind',at_risk:'at risk'};
(async()=>{
  const g=await (await fetch('/api/goals')).json();
  document.getElementById('g').innerHTML = g.goals.length ? g.goals.map(x=>
    '<div class=goal><div class=top><div><b>'+e(x.label)+'</b><br><span style="font-size:12.5px;color:var(--dim)">'+
    e(x.mechanism)+' &middot; '+fmt(x.target)+' over '+x.timeline+'mo &middot; '+e(x.state_version)+'</span></div>'+
    '<span class="pill '+(x.priority>0?'urgent':x.status)+'">'+(x.priority>0?'check now':(LBL[x.status]||x.status))+'</span></div>'+
    '<div class=why>'+e(x.why)+'</div><div class=a>&rarr; '+e(x.next_action)+'</div></div>').join('')
    : '<div class=empty>No locked goals yet. Say something in the chat and accept one.</div>';
  const h=await (await fetch('/api/chat')).json();
  document.getElementById('h').innerHTML = h.turns.length ? h.turns.map(t=>
    '<div class="turn '+t.role+'"><div class=w>'+(t.role==='user'?'You':(t.meta&&t.meta.kind==='event'?'Event':'iASPIRE'))+
    '</div><div class=t>'+e(t.text)+'</div></div>').join('')
    : '<div class=empty>No conversation stored yet.</div>';
})();
</script>"""
class H(BaseHTTPRequestHandler):
    # HTTP/1.1 with a threading server. The single-threaded default served curl fine but
    # deadlocked a real browser, which holds connections open and issues requests in
    # parallel - the page would load and then every message would hang unanswered.
    protocol_version="HTTP/1.1"
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
        """Read a request body from either Content-Length or a chunked stream.

        Previously only Content-Length was read, so a chunked request silently parsed as an
        empty body and the app answered "text required" to a perfectly valid message.
        """
        te=(self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            chunks=[]; size=int(self.headers.get("X-Chunk-Encoding",0) or 0)
            while True:
                line=self.rfile.readline().strip()
                if not line: break
                try: size=int(line.split(b";")[0],16)
                except ValueError: break
                if size==0:
                    self.rfile.readline(); break
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            raw=b"".join(chunks)
        else:
            n=int(self.headers.get("Content-Length") or 0)
            raw=self.rfile.read(n) if n else b""
        if not raw: return {}
        try: return json.loads(raw)
        except ValueError:
            raise ValueError("request body was not valid JSON")
    def do_GET(self):
        if self.path=="/": return self._send(200,PAGE,"text/html")
        if self.path=="/data": return self._send(200,DATA_PAGE,"text/html")
        if self.path=="/api/boom":
            if _os.environ.get("IASPIRE_TEST_ROUTES")!="1":
                return self._send(404,'{"error":"not found"}')
            raise RuntimeError("deliberate handler fault for the guard test")
        if self.path=="/api/chat":
            return self._send(200,json.dumps({"turns":CHAT.turns()},default=str))
        if self.path=="/api/goals":
            return self._send(200,json.dumps({"goals":PIPE.goals_view()},default=str))
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
        if self.path=="/api/chat/clear":
            CHAT.clear(); return self._send(200,json.dumps({"cleared":True}))
        if self.path=="/api/flow/change":
            CHAT.add("app","(life event: "+str(b.get("kind","income_drop"))+")",{"kind":"event"})
            out=PIPE.simulate_material_change(b.get("kind","income_drop"))
            # trigger detail comes from the single audit store, not a parallel log
            fired=[r for r in PIPE.audit_log.records
                   if r["action"] in ("reanalysis.triggered","priority.raised")]
            t=(fired[-1]["detail"].get("trigger",{"type":b.get("kind","income_drop")})
               if fired else {"type":b.get("kind","income_drop")})
            stages=([{"kind":"alert","text":N.change_alert(b.get("kind"),t,out)}] if out else [])
            return self._send(200,json.dumps({"stages":stages,"reanalysis":out},default=str))
        m2=re.match(r"^/api/aspirations/([\w]+)/continue$",self.path)
        if m2:
            if not b.get("text"): return self._send(400,'{"error":"text required"}')
            return self._send(200,json.dumps(_continue_flow(m2.group(1),b["text"]),default=str))
        if self.path=="/api/aspirations":
            if not b.get("text"): return self._send(400,'{"error":"text required"}')
            return self._send(200,json.dumps(_submit_flow(b["text"]),default=str))
        m=re.match(r"^/api/aspirations/([\w]+)/response$",self.path)
        if m:
            return self._send(200,json.dumps(PIPE.respond(m.group(1),b.get("response"),b.get("modified")),default=str))
        if self.path=="/api/simulate":
            return self._send(200,json.dumps({"reanalysis":PIPE.simulate_material_change(b.get("kind","income_drop"))},default=str))
        self._send(404,'{"error":"not found"}')

if __name__=="__main__":
    _port=int(_os.environ.get("PORT","8848"))
    print(f"iASPIRE Journal  ->  http://127.0.0.1:{_port}  (Ctrl-C to stop)",flush=True)
    srv=ThreadingHTTPServer(("127.0.0.1",_port),H)
    srv.daemon_threads=True
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally: srv.server_close()
